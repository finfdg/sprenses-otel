"""Bütçe yönetimi — Kategori ve bütçe kaydı CRUD + özet raporları."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.budget import Budget, BudgetCategory
from app.models.department import Department
from app.models.user import User
from app.models.vendor_transaction import VendorTransaction
from app.schemas.budget import (
    BudgetBulkCreate,
    BudgetCategoryCreate,
    BudgetCategoryResponse,
    BudgetCategoryUpdate,
    BudgetCreate,
    BudgetMonthlySummary,
    BudgetResponse,
    BudgetSummaryItem,
)
from app.services import budget_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.pagination import page_meta

router = APIRouter(prefix="/butce", tags=["Bütçe"])


# ─── Yardımcı ──────────────────────────────────────────


def _build_budget_response(b: Budget) -> dict:
    """Budget kaydını BudgetResponse formatına dönüştür."""
    return BudgetResponse(
        id=b.id,
        department_id=b.department_id,
        department_name=b.department.name if b.department else None,
        category_id=b.category_id,
        category_name=b.category.name if b.category else None,
        category_type=b.category.type if b.category else None,
        year=b.year,
        month=b.month,
        planned_amount=float(b.planned_amount),
        actual_amount=float(b.actual_amount),
        currency=b.currency,
        notes=b.notes,
        created_at=b.created_at,
        updated_at=b.updated_at,
    ).model_dump()


# ═══════════════════════════════════════════════════════
# KATEGORİLER
# ═══════════════════════════════════════════════════════


@router.get("/kategoriler")
def list_categories(
    type_filter: Optional[str] = Query(None, alias="type"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.butce", "view")),
):
    """Bütçe kategorilerini listele."""
    query = db.query(BudgetCategory)
    if type_filter and type_filter in ("income", "expense"):
        query = query.filter(BudgetCategory.type == type_filter)
    categories = query.order_by(BudgetCategory.sort_order, BudgetCategory.name).all()
    return [BudgetCategoryResponse.model_validate(c).model_dump() for c in categories]


@router.post("/kategoriler", status_code=status.HTTP_201_CREATED)
def create_category(
    data: BudgetCategoryCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Yeni bütçe kategorisi oluştur."""
    approval_resp = check_approval(db, "finance.butce", 0, current_user.id, "create", {"_target": "category", **data.model_dump()})
    if approval_resp:
        return approval_resp

    existing = db.query(BudgetCategory).filter(
        BudgetCategory.name == data.name.strip(),
        BudgetCategory.type == data.type,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Bu isim ve tipte bir kategori zaten mevcut.",
        )

    category = budget_service.create_category(db, data.model_dump())
    db.commit()
    db.refresh(category)

    log_action(
        db, current_user.id, "create", "budget_category",
        category.id, json.dumps({"name": category.name, "type": category.type}, ensure_ascii=False),
        get_client_ip(request),
    )

    return BudgetCategoryResponse.model_validate(category).model_dump()


@router.patch("/kategoriler/{cat_id}")
def update_category(
    cat_id: int,
    data: BudgetCategoryUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Bütçe kategorisi güncelle."""
    category = db.query(BudgetCategory).filter(BudgetCategory.id == cat_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Kategori bulunamadı.")

    approval_resp = check_approval(db, "finance.butce", cat_id, current_user.id, "update", {"_target": "category", **data.model_dump(exclude_unset=True)})
    if approval_resp:
        return approval_resp

    changes = budget_service.apply_category_update(db, category, data.model_dump(exclude_unset=True))

    if not changes:
        raise HTTPException(status_code=400, detail="Güncellenecek alan belirtilmedi.")

    db.commit()
    db.refresh(category)

    log_action(
        db, current_user.id, "update", "budget_category",
        category.id, json.dumps(changes, ensure_ascii=False, default=str),
        get_client_ip(request),
    )

    return BudgetCategoryResponse.model_validate(category).model_dump()


@router.delete("/kategoriler/{cat_id}", status_code=status.HTTP_200_OK)
def delete_category(
    cat_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Bütçe kategorisi sil. Bütçe veya faturada kullanılıyorsa silinemez."""
    category = db.query(BudgetCategory).filter(BudgetCategory.id == cat_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Kategori bulunamadı.")

    approval_resp = check_approval(db, "finance.butce", cat_id, current_user.id, "delete", {"_target": "category"})
    if approval_resp:
        return approval_resp

    # Bütçelerde kullanılıyor mu?
    budget_count = db.query(func.count(Budget.id)).filter(
        Budget.category_id == cat_id
    ).scalar()
    if budget_count:
        raise HTTPException(
            status_code=400,
            detail=f"Bu kategori {budget_count} bütçe kaydında kullanılıyor. Önce ilgili kayıtları silin.",
        )

    # Cari işlemlerde kullanılıyor mu?
    vtx_count = db.query(func.count(VendorTransaction.id)).filter(
        VendorTransaction.budget_category_id == cat_id
    ).scalar()
    if vtx_count:
        raise HTTPException(
            status_code=400,
            detail=f"Bu kategori {vtx_count} cari işlemde kullanılıyor. Önce ilgili işlemleri güncelleyin.",
        )

    cat_name = category.name
    budget_service.delete_category(db, category)
    db.commit()

    log_action(
        db, current_user.id, "delete", "budget_category",
        cat_id, json.dumps({"name": cat_name}, ensure_ascii=False),
        get_client_ip(request),
    )

    return {"message": "Kategori silindi."}


# ═══════════════════════════════════════════════════════
# BÜTÇE KAYITLARI
# ═══════════════════════════════════════════════════════


@router.get("/")
def list_budgets(
    year: int = Query(...),
    month: Optional[int] = Query(None, ge=1, le=12),
    department_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.butce", "view")),
):
    """Bütçe kayıtlarını listele (yıl zorunlu, ay ve departman opsiyonel)."""
    query = db.query(Budget).filter(Budget.year == year)
    if month is not None:
        query = query.filter(Budget.month == month)
    if department_id is not None:
        query = query.filter(Budget.department_id == department_id)

    total = query.count()
    budgets = (
        query
        .options(joinedload(Budget.department), joinedload(Budget.category))
        .order_by(Budget.department_id, Budget.month, Budget.category_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return page_meta([_build_budget_response(b) for b in budgets], total, page, page_size)


@router.post("/", status_code=status.HTTP_200_OK)
def upsert_budget(
    data: BudgetCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Bütçe kaydı oluştur veya güncelle (upsert)."""
    approval_resp = check_approval(db, "finance.butce", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    # Departman ve kategori kontrolü
    dept = db.query(Department).filter(Department.id == data.department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departman bulunamadı.")
    cat = db.query(BudgetCategory).filter(BudgetCategory.id == data.category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Bütçe kategorisi bulunamadı.")

    budget = budget_service.upsert_budget(
        db,
        department_id=data.department_id,
        category_id=data.category_id,
        year=data.year,
        month=data.month,
        planned_amount=data.planned_amount,
        currency=data.currency,
        notes=data.notes,
        created_by=current_user.id,
    )
    db.commit()
    db.refresh(budget)

    log_action(
        db, current_user.id, "update" if budget.updated_at else "create", "budget",
        budget.id,
        json.dumps({
            "department": dept.name,
            "category": cat.name,
            "year": data.year,
            "month": data.month,
            "planned_amount": data.planned_amount,
        }, ensure_ascii=False, default=str),
        get_client_ip(request),
    )

    # Reload relationships
    budget = (
        db.query(Budget)
        .options(joinedload(Budget.department), joinedload(Budget.category))
        .filter(Budget.id == budget.id)
        .first()
    )

    return _build_budget_response(budget)


@router.post("/bulk", status_code=status.HTTP_200_OK)
def bulk_upsert_budgets(
    data: BudgetBulkCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Toplu bütçe kaydı oluştur veya güncelle."""
    if not data.items:
        raise HTTPException(status_code=400, detail="En az bir kayıt gerekli.")

    # Onay akışı — /bulk grid'deki her hücre kaydının normal yoludur (operasyonel
    # toplu içe-aktarma değil), bu yüzden onay kontrolünden geçer. Eşleşen workflow
    # yoksa no-op'tur. Executor `_target="bulk"` dalı bu payload'ı birebir yeniden uygular.
    approval_resp = check_approval(
        db, "finance.butce", 0, current_user.id, "create",
        {"_target": "bulk", **data.model_dump()},
    )
    if approval_resp:
        return approval_resp

    created_count = 0
    updated_count = 0

    for item in data.items:
        existing = db.query(Budget).filter(
            Budget.department_id == item.department_id,
            Budget.category_id == item.category_id,
            Budget.year == item.year,
            Budget.month == item.month,
        ).first()
        # Ortak service (kompozit-anahtar upsert) — elle Budget() insert/update yerine.
        budget_service.upsert_budget(
            db,
            department_id=item.department_id,
            category_id=item.category_id,
            year=item.year,
            month=item.month,
            planned_amount=item.planned_amount,
            currency=item.currency,
            notes=getattr(item, "notes", None),
            created_by=current_user.id,
        )
        if existing:
            updated_count += 1
        else:
            created_count += 1

    db.commit()

    log_action(
        db, current_user.id, "create", "budget",
        None,
        json.dumps({
            "bulk": True,
            "created": created_count,
            "updated": updated_count,
            "total_items": len(data.items),
        }, ensure_ascii=False),
        get_client_ip(request),
    )

    return {
        "message": f"{created_count} kayıt oluşturuldu, {updated_count} kayıt güncellendi.",
        "created": created_count,
        "updated": updated_count,
    }


@router.delete("/{budget_id}", status_code=status.HTTP_200_OK)
def delete_budget(
    budget_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Bütçe kaydını sil."""
    budget = (
        db.query(Budget)
        .options(joinedload(Budget.department), joinedload(Budget.category))
        .filter(Budget.id == budget_id)
        .first()
    )
    if not budget:
        raise HTTPException(status_code=404, detail="Bütçe kaydı bulunamadı.")

    approval_resp = check_approval(db, "finance.butce", budget_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    details = {
        "department": budget.department.name if budget.department else None,
        "category": budget.category.name if budget.category else None,
        "year": budget.year,
        "month": budget.month,
        "planned_amount": float(budget.planned_amount),
    }

    budget_service.delete_budget(db, budget)
    db.commit()

    log_action(
        db, current_user.id, "delete", "budget",
        budget_id, json.dumps(details, ensure_ascii=False, default=str),
        get_client_ip(request),
    )

    return {"message": "Bütçe kaydı silindi."}


# ═══════════════════════════════════════════════════════
# ÖZET RAPORLARI
# ═══════════════════════════════════════════════════════


@router.get("/summary")
def annual_summary(
    year: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.butce", "view")),
):
    """Yıllık bütçe özeti: departman bazında planlanan/gerçekleşen gelir-gider toplamları."""
    rows = (
        db.query(
            Budget.department_id,
            Department.name.label("department_name"),
            BudgetCategory.type.label("cat_type"),
            func.sum(Budget.planned_amount).label("total_planned"),
            func.sum(Budget.actual_amount).label("total_actual"),
        )
        .join(Department, Budget.department_id == Department.id)
        .join(BudgetCategory, Budget.category_id == BudgetCategory.id)
        .filter(Budget.year == year)
        .group_by(Budget.department_id, Department.name, BudgetCategory.type)
        .all()
    )

    # Departman bazında topla
    dept_map = {}
    for row in rows:
        key = row.department_id
        if key not in dept_map:
            dept_map[key] = BudgetSummaryItem(
                department_id=row.department_id,
                department_name=row.department_name,
            )
        item = dept_map[key]
        planned = float(row.total_planned or 0)
        actual = float(row.total_actual or 0)
        if row.cat_type == "income":
            item.total_planned_income += planned
            item.total_actual_income += actual
        else:
            item.total_planned_expense += planned
            item.total_actual_expense += actual

    return [item.model_dump() for item in dept_map.values()]


@router.get("/monthly-summary")
def monthly_summary(
    year: int = Query(...),
    department_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.butce", "view")),
):
    """Aylık bütçe özeti: 12 aylık planlanan/gerçekleşen gelir-gider dağılımı."""
    query = (
        db.query(
            Budget.month,
            BudgetCategory.type.label("cat_type"),
            func.sum(Budget.planned_amount).label("total_planned"),
            func.sum(Budget.actual_amount).label("total_actual"),
        )
        .join(BudgetCategory, Budget.category_id == BudgetCategory.id)
        .filter(Budget.year == year)
    )
    if department_id is not None:
        query = query.filter(Budget.department_id == department_id)

    rows = query.group_by(Budget.month, BudgetCategory.type).all()

    # 12 aylık şablon
    monthly = {m: BudgetMonthlySummary(month=m) for m in range(1, 13)}
    for row in rows:
        item = monthly[row.month]
        planned = float(row.total_planned or 0)
        actual = float(row.total_actual or 0)
        if row.cat_type == "income":
            item.planned_income += planned
            item.actual_income += actual
        else:
            item.planned_expense += planned
            item.actual_expense += actual

    return [monthly[m].model_dump() for m in range(1, 13)]
