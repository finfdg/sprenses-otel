"""Departman fatura onay iş akışı.

Carilerdeki fatura kayıtlarına (vendor_transactions) departman ataması yapılır,
ilgili departman müdürünün onayına düşer. Onaylanan faturalar bütçeye yansır.
"""
from datetime import datetime
from typing import Optional

import pytz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.budget import Budget, BudgetCategory
from app.models.department import Department
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.notification import create_and_send_notifications

router = APIRouter(prefix="/onay", tags=["Onay"])

tz_istanbul = pytz.timezone("Europe/Istanbul")


# ─── Schemas ────────────────────────────────────────────
class DeptAssignRequest(BaseModel):
    department_id: int
    budget_category_id: Optional[int] = None


class ApprovalAction(BaseModel):
    note: Optional[str] = None


class PendingResponse(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    date: str
    evrak_no: Optional[str] = None
    description: Optional[str] = None
    borc: float
    alacak: float
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    budget_category_id: Optional[int] = None
    budget_category_name: Optional[str] = None
    dept_status: Optional[str] = None
    dept_assigned_by_name: Optional[str] = None
    dept_assigned_at: Optional[str] = None
    dept_rejection_note: Optional[str] = None


# ─── Helpers ────────────────────────────────────────────
def _build_response(vtx: VendorTransaction, vendor_name: str,
                    dept_name: Optional[str] = None,
                    cat_name: Optional[str] = None,
                    assigned_by_name: Optional[str] = None) -> dict:
    return {
        "id": vtx.id,
        "vendor_id": vtx.vendor_id,
        "vendor_name": vendor_name,
        "date": str(vtx.date),
        "evrak_no": vtx.evrak_no,
        "description": vtx.description,
        "borc": float(vtx.borc),
        "alacak": float(vtx.alacak),
        "department_id": vtx.department_id,
        "department_name": dept_name,
        "budget_category_id": vtx.budget_category_id,
        "budget_category_name": cat_name,
        "dept_status": vtx.dept_status,
        "dept_assigned_by_name": assigned_by_name,
        "dept_assigned_at": str(vtx.dept_assigned_at) if vtx.dept_assigned_at else None,
        "dept_rejection_note": vtx.dept_rejection_note,
    }


# ─── Endpoints ──────────────────────────────────────────
#
# ONAY AKIŞI İSTİSNASI (2026-07-01 kararı): Bu modülün mutasyon endpoint'leri
# (assign/approve/reject/remove) bilinçli olarak `check_approval`'dan GEÇMEZ — modülün
# KENDİSİ departman onay akışıdır; işlem onaylama/reddetme eylemlerini bir başka onay
# katmanına sokmak "onaylamak için onay" kısır döngüsü yaratır. finance.onay için
# approval_executor'da handler da yoktur (bilinçli).


@router.post("/assign/{vtx_id}")
def assign_department(
    vtx_id: int,
    data: DeptAssignRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari fatura kaydına departman ata → onaya gönder."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    dept = db.query(Department).filter(Department.id == data.department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departman bulunamadı")

    if not dept.manager_id:
        raise HTTPException(status_code=400, detail="Bu departmanın müdürü atanmamış")

    now = datetime.now(tz_istanbul)
    vtx.department_id = data.department_id
    vtx.budget_category_id = data.budget_category_id
    vtx.dept_status = "pending"
    vtx.dept_assigned_by = current_user.id
    vtx.dept_assigned_at = now
    vtx.dept_approved_by = None
    vtx.dept_approved_at = None
    vtx.dept_rejection_note = None

    log_action(
        db, current_user.id, "update", "vendor_transaction",
        entity_id=vtx_id,
        details=f"Departman ataması: {dept.name}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    broadcast_finance_update(background_tasks, BroadcastModule.BUTCE, "update")

    # Departman müdürüne bildirim gönder
    vendor = db.query(Vendor).filter(Vendor.id == vtx.vendor_id).first()
    vendor_name = vendor.hesap_adi if vendor else "Bilinmeyen"
    amount = float(vtx.alacak) if vtx.alacak else float(vtx.borc)
    create_and_send_notifications(
        db,
        user_ids=[dept.manager_id],
        type="dept_approval_needed",
        title="Fatura Onayı Bekliyor",
        body=f"{vendor_name} — {amount:,.2f} ₺",
        link="/dashboard/finans/onay",
    )

    return {"status": "ok", "dept_status": "pending"}


@router.get("/my-approvals")
def get_my_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.onay", "view")),
):
    """Giriş yapan kullanıcının müdürü olduğu departmanlardaki onay bekleyen faturalar."""
    # Kullanıcının müdür olduğu departmanları bul
    my_depts = db.query(Department).filter(
        Department.manager_id == current_user.id,
        Department.is_active == True,
    ).all()

    if not my_depts:
        return []

    dept_ids = [d.id for d in my_depts]
    dept_map = {d.id: d.name for d in my_depts}

    # Onay bekleyen faturaları getir
    vtxs = (
        db.query(VendorTransaction)
        .filter(
            VendorTransaction.department_id.in_(dept_ids),
            VendorTransaction.dept_status == "pending",
        )
        .order_by(VendorTransaction.dept_assigned_at.desc())
        .all()
    )

    if not vtxs:
        return []

    # Vendor adlarını toplu çek
    vendor_ids = list(set(v.vendor_id for v in vtxs))
    vendors = db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()
    vendor_map = {v.id: v.hesap_adi for v in vendors}

    # Atayan kişi adlarını toplu çek
    assigned_ids = list(set(v.dept_assigned_by for v in vtxs if v.dept_assigned_by))
    if assigned_ids:
        users = db.query(User).filter(User.id.in_(assigned_ids)).all()
        user_map = {u.id: u.full_name for u in users}
    else:
        user_map = {}

    # Kategori adlarını toplu çek
    cat_ids = list(set(v.budget_category_id for v in vtxs if v.budget_category_id))
    if cat_ids:
        cats = db.query(BudgetCategory).filter(BudgetCategory.id.in_(cat_ids)).all()
        cat_map = {c.id: c.name for c in cats}
    else:
        cat_map = {}

    return [
        _build_response(
            vtx,
            vendor_name=vendor_map.get(vtx.vendor_id, ""),
            dept_name=dept_map.get(vtx.department_id, ""),
            cat_name=cat_map.get(vtx.budget_category_id) if vtx.budget_category_id else None,
            assigned_by_name=user_map.get(vtx.dept_assigned_by) if vtx.dept_assigned_by else None,
        )
        for vtx in vtxs
    ]


@router.get("/pending-count")
def get_pending_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.onay", "view")),
):
    """Kullanıcının onay bekleyen fatura sayısı (sidebar badge)."""
    my_dept_ids = (
        db.query(Department.id)
        .filter(Department.manager_id == current_user.id, Department.is_active == True)
        .all()
    )
    if not my_dept_ids:
        return {"count": 0}

    ids = [d[0] for d in my_dept_ids]
    count = db.query(func.count(VendorTransaction.id)).filter(
        VendorTransaction.department_id.in_(ids),
        VendorTransaction.dept_status == "pending",
    ).scalar()
    return {"count": count or 0}


@router.post("/approve/{vtx_id}")
def approve_transaction(
    vtx_id: int,
    data: ApprovalAction,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.onay", "use")),
):
    """Fatura onaylama — sadece departman müdürü yapabilir."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    if vtx.dept_status != "pending":
        raise HTTPException(status_code=400, detail="Bu işlem onay bekleyen durumda değil")

    # Müdür kontrolü
    dept = db.query(Department).filter(Department.id == vtx.department_id).first()
    if not dept or dept.manager_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu departmanın onay yetkiniz yok")

    now = datetime.now(tz_istanbul)
    vtx.dept_status = "approved"
    vtx.dept_approved_by = current_user.id
    vtx.dept_approved_at = now
    vtx.dept_rejection_note = None

    # Bütçeye yansıt: actual_amount güncelle
    if vtx.budget_category_id:
        amount = float(vtx.alacak) if vtx.alacak else float(vtx.borc)
        budget = db.query(Budget).filter(
            Budget.department_id == vtx.department_id,
            Budget.category_id == vtx.budget_category_id,
            Budget.year == vtx.date.year,
            Budget.month == vtx.date.month,
        ).first()
        if budget:
            budget.actual_amount = float(budget.actual_amount) + amount
        else:
            # Bütçe kaydı yoksa oluştur
            new_budget = Budget(
                department_id=vtx.department_id,
                category_id=vtx.budget_category_id,
                year=vtx.date.year,
                month=vtx.date.month,
                planned_amount=0,
                actual_amount=amount,
                currency="TRY",
            )
            db.add(new_budget)

    log_action(
        db, current_user.id, "approve", "vendor_transaction",
        entity_id=vtx_id,
        details=f"Fatura onaylandı — {dept.name}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    broadcast_finance_update(background_tasks, BroadcastModule.BUTCE, "update")

    # Gönderene bildirim
    if vtx.dept_assigned_by:
        vendor = db.query(Vendor).filter(Vendor.id == vtx.vendor_id).first()
        create_and_send_notifications(
            db,
            user_ids=[vtx.dept_assigned_by],
            type="dept_approved",
            title="Fatura Onaylandı",
            body=f"{vendor.hesap_adi if vendor else ''} — {dept.name}",
            link="/dashboard/finans/cariler",
        )

    return {"status": "ok", "dept_status": "approved"}


@router.post("/reject/{vtx_id}")
def reject_transaction(
    vtx_id: int,
    data: ApprovalAction,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.onay", "use")),
):
    """Fatura reddetme — sadece departman müdürü yapabilir."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    if vtx.dept_status != "pending":
        raise HTTPException(status_code=400, detail="Bu işlem onay bekleyen durumda değil")

    dept = db.query(Department).filter(Department.id == vtx.department_id).first()
    if not dept or dept.manager_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu departmanın onay yetkiniz yok")

    if not data.note:
        raise HTTPException(status_code=400, detail="Red gerekçesi zorunludur")

    now = datetime.now(tz_istanbul)
    vtx.dept_status = "rejected"
    vtx.dept_approved_by = current_user.id
    vtx.dept_approved_at = now
    vtx.dept_rejection_note = data.note

    log_action(
        db, current_user.id, "reject", "vendor_transaction",
        entity_id=vtx_id,
        details=f"Fatura reddedildi — {dept.name}: {data.note}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    broadcast_finance_update(background_tasks, BroadcastModule.BUTCE, "update")

    # Gönderene bildirim
    if vtx.dept_assigned_by:
        create_and_send_notifications(
            db,
            user_ids=[vtx.dept_assigned_by],
            type="dept_rejected",
            title="Fatura Reddedildi",
            body=data.note[:100],
            link="/dashboard/finans/cariler",
        )

    return {"status": "ok", "dept_status": "rejected"}


@router.post("/remove/{vtx_id}")
def remove_assignment(
    vtx_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Departman atamasını kaldır (sadece pending veya rejected durumda)."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    if vtx.dept_status == "approved":
        raise HTTPException(status_code=400, detail="Onaylanmış atama kaldırılamaz")

    vtx.department_id = None
    vtx.budget_category_id = None
    vtx.dept_status = None
    vtx.dept_assigned_by = None
    vtx.dept_assigned_at = None
    vtx.dept_approved_by = None
    vtx.dept_approved_at = None
    vtx.dept_rejection_note = None

    log_action(
        db, current_user.id, "update", "vendor_transaction",
        entity_id=vtx_id,
        details="Departman ataması kaldırıldı",
        ip_address=get_client_ip(request),
    )
    db.commit()

    broadcast_finance_update(background_tasks, BroadcastModule.BUTCE, "update")

    return {"status": "ok"}
