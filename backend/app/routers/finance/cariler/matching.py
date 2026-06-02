"""Cari eşleştirme — çek eşleştirme, kaldırma, devir işaretleme."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.sync_vendor_fifo import sync_vendor_finance_events

from ._helpers import logger

router = APIRouter()


# ─── Çek Eşleştirme ──────────────────────────────────────


@router.get("/transactions/{vtx_id}/candidate-checks")
def get_candidate_checks(
    vtx_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Bir cari borç kaydı için eşleştirilebilecek çekleri getir."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    vendor = db.query(Vendor).filter(Vendor.id == vtx.vendor_id).first()

    query = db.query(Check).filter(
        Check.status == "pending",
        Check.bank_transaction_id.is_(None),
        Check.match_number.is_(None),
    )

    checks = query.order_by(Check.due_date).all()

    results = []
    vtx_amount = float(vtx.borc)
    vendor_name = (vendor.hesap_adi or "").lower() if vendor else ""

    for c in checks:
        score = 0
        check_amount = float(c.amount_tl)

        if abs(check_amount - vtx_amount) < 0.01:
            score += 50
        elif abs(check_amount - vtx_amount) / max(vtx_amount, 1) < 0.05:
            score += 20

        check_vendor = (c.vendor_name or "").lower()
        if vendor_name and check_vendor:
            vendor_words = set(vendor_name.split())
            check_words = set(check_vendor.split())
            common = vendor_words & check_words
            if len(common) >= 2:
                score += 30
            elif len(common) >= 1 and len(next(iter(common), "")) > 3:
                score += 15

        results.append({
            "id": c.id,
            "check_no": c.check_no,
            "vendor_name": c.vendor_name,
            "vendor_code": c.vendor_code,
            "due_date": c.due_date,
            "amount_tl": float(c.amount_tl),
            "currency": c.currency,
            "amount_currency": float(c.amount_currency) if c.amount_currency else None,
            "description": c.description,
            "score": score,
        })

    results.sort(key=lambda x: (-x["score"], x["due_date"]))

    return results[:50]


@router.post("/transactions/{vtx_id}/match-check/{check_id}")
def match_vendor_with_check(
    vtx_id: int,
    check_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari borç kaydını verilen çek ile eşleştir."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="Cari işlem bulunamadı")

    check = db.query(Check).filter(Check.id == check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Çek bulunamadı")

    if vtx.match_number:
        raise HTTPException(status_code=400, detail="Bu işlem zaten eşleştirilmiş")

    try:
        from sqlalchemy import text
        match_num = db.execute(text("SELECT nextval('match_number_seq')")).scalar()

        vtx.match_number = match_num
        vtx.payment_method = "cek"

        check.match_number = match_num
        check.matched_vendor_id = vtx.vendor_id
        check.vendor_code = check.vendor_code or (db.query(Vendor).filter(Vendor.id == vtx.vendor_id).first() or Vendor()).hesap_kodu

        db.flush()

        finance_event_svc.upsert_check(db, check)

        log_action(
            db, current_user.id, "match", "vendor_check",
            entity_id=vtx_id,
            details=f"Cari işlem #{vtx_id} ↔ Çek #{check.check_no} eşleştirildi (match={match_num})",
            ip_address=get_client_ip(request),
        )
        db.commit()
        sync_vendor_finance_events(db)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Çek eşleştirme hatası (vtx_id=%s, check_id=%s): %s", vtx_id, check_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Çek eşleştirme sırasında bir veritabanı hatası oluştu.")

    broadcast_finance_update(background_tasks, "cariler", "match")

    return {
        "match_number": match_num,
        "vtx_id": vtx_id,
        "check_id": check_id,
        "check_no": check.check_no,
    }


@router.delete("/transactions/{vtx_id}/unmatch-check")
def unmatch_vendor_check(
    vtx_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari borç - çek eşleştirmesini kaldır."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="Cari işlem bulunamadı")

    if not vtx.match_number or vtx.payment_method != "cek":
        raise HTTPException(status_code=400, detail="Bu işlemde çek eşleştirmesi yok")

    old_match = vtx.match_number

    try:
        matched_check = db.query(Check).filter(Check.match_number == old_match).first()
        if matched_check:
            matched_check.match_number = None
            matched_check.matched_vendor_id = None

        vtx.match_number = None
        vtx.payment_method = None

        log_action(
            db, current_user.id, "unmatch", "vendor_check",
            entity_id=vtx_id,
            details=f"Cari işlem #{vtx_id} çek eşleştirmesi kaldırıldı (eski match={old_match})",
            ip_address=get_client_ip(request),
        )
        db.commit()
        sync_vendor_finance_events(db)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Çek eşleştirme kaldırma hatası (vtx_id=%s): %s", vtx_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Çek eşleştirmesi kaldırılırken bir veritabanı hatası oluştu.")

    broadcast_finance_update(background_tasks, "cariler", "unmatch")

    return {"status": "ok"}


@router.delete("/transactions/{vtx_id}/unmatch")
def unmatch_vendor_transaction(
    vtx_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari borç - banka eşleştirmesini kaldır."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="Cari işlem bulunamadı")

    if not vtx.match_number or vtx.match_number < 0:
        raise HTTPException(status_code=400, detail="Bu işlemde eşleştirme yok")

    old_match = vtx.match_number
    old_method = vtx.payment_method

    try:
        if old_match:
            btx = db.query(BankTransaction).filter(BankTransaction.match_number == old_match).first()
            if btx:
                btx.match_number = None
                btx.payment_method = None
                btx.vendor_id = None

        vtx.match_number = None
        vtx.payment_method = None

        log_action(
            db, current_user.id, "unmatch", "vendor_bank",
            entity_id=vtx_id,
            details=f"Cari işlem #{vtx_id} eşleştirmesi kaldırıldı (eski match={old_match}, method={old_method})",
            ip_address=get_client_ip(request),
        )
        db.commit()
        sync_vendor_finance_events(db)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Banka eşleştirme kaldırma hatası (vtx_id=%s): %s", vtx_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Eşleştirme kaldırılırken bir veritabanı hatası oluştu.")

    broadcast_finance_update(background_tasks, "cariler", "unmatch")

    return {"status": "ok"}


# ─── Avans/Devir İşaretleme ──────────────────────────────


@router.patch("/transactions/{vtx_id}/devir")
def mark_as_devir(
    vtx_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari işlemi avans/devir olarak işaretle."""
    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == vtx_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    try:
        vtx.match_number = -1
        vtx.payment_method = "devir"

        vendor = db.query(Vendor).filter(Vendor.id == vtx.vendor_id).first()
        vendor_name = vendor.hesap_adi if vendor else ""

        log_action(
            db, current_user.id, "update", "vendor_transaction",
            entity_id=vtx_id,
            details=f"Avans/devir olarak işaretlendi | Cari: {vendor_name} | ₺{float(vtx.borc):,.2f}",
            ip_address=get_client_ip(request),
        )
        db.commit()
        sync_vendor_finance_events(db)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Devir işaretleme hatası (vtx_id=%s): %s", vtx_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Devir işaretlenirken bir veritabanı hatası oluştu.")

    broadcast_finance_update(background_tasks, "cariler", "match")
