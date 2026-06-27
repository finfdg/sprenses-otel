"""Cari listesi, detay, banka işlemleri, özet ve vade güncelleme."""

import math
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import case as sa_case
from sqlalchemy import collate, desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.exchange_rate import ExchangeRate
from app.models.user import User
from app.models.vendor import STATUS_PAYMENT_BANNED, VENDOR_STATUS_CHOICES, Vendor
from app.models.vendor_transaction import VendorTransaction
from app.schemas.vendor import (
    VendorDetailResponse,
    VendorPaymentDaysUpdate,
    VendorResponse,
    VendorStatusUpdate,
)
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.services import vendor_service
from app.utils.pagination import page_meta

from ._helpers import _build_dept_cat_user_maps, _build_tx_response, logger

router = APIRouter()


# ─── Cari Özet ───────────────────────────────────────────

@router.get("/vendors/summary")
def get_vendors_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Tüm carilerin toplam borç/alacak/bakiye özetini getir."""
    totals = (
        db.query(
            func.coalesce(func.sum(VendorTransaction.borc), 0),
            func.coalesce(func.sum(VendorTransaction.alacak), 0),
        )
        .first()
    )
    total_borc = float(totals[0])
    total_alacak = float(totals[1])

    vendor_count = db.query(func.count(Vendor.id)).scalar() or 0
    banned_count = db.query(func.count(Vendor.id)).filter(Vendor.status == STATUS_PAYMENT_BANNED).scalar() or 0

    neg_sub = (
        db.query(
            Vendor.id,
            (func.coalesce(func.sum(VendorTransaction.borc), 0) - func.coalesce(func.sum(VendorTransaction.alacak), 0)).label("bakiye"),
        )
        .outerjoin(VendorTransaction, Vendor.id == VendorTransaction.vendor_id)
        .group_by(Vendor.id)
        .having(
            func.coalesce(func.sum(VendorTransaction.borc), 0) - func.coalesce(func.sum(VendorTransaction.alacak), 0) < 0
        )
        .subquery()
    )
    neg_result = db.query(
        func.count(neg_sub.c.id),
        func.coalesce(func.sum(neg_sub.c.bakiye), 0),
    ).first()
    negative_count = int(neg_result[0])
    negative_total = float(neg_result[1])

    bakiye = total_borc - total_alacak
    negative_total_eur = None
    latest_date = db.query(func.max(ExchangeRate.date)).scalar()
    if latest_date:
        eur_obj = db.query(ExchangeRate).filter(
            ExchangeRate.date == latest_date,
            ExchangeRate.currency_code == "EUR",
        ).first()
        if eur_obj and eur_obj.forex_selling and float(eur_obj.forex_selling) > 0:
            negative_total_eur = round(abs(float(negative_total)) / float(eur_obj.forex_selling), 2)

    return {
        "total_borc": total_borc,
        "total_alacak": total_alacak,
        "bakiye": bakiye,
        "vendor_count": vendor_count,
        "negative_count": negative_count,
        "negative_total": negative_total,
        "negative_total_eur": negative_total_eur,
        "banned_count": banned_count,
    }


# ─── Cari Listesi ────────────────────────────────────────

@router.get("/vendors")
def list_vendors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, pattern="^(hesap_adi|total_borc|total_alacak|bakiye)$"),
    sort_dir: Optional[str] = Query("asc", pattern="^(asc|desc)$"),
    hide_zero: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Cari listesini getir (toplam borç/alacak/bakiye ile)."""
    total_borc_col = func.coalesce(func.sum(VendorTransaction.borc), 0).label("total_borc")
    total_alacak_col = func.coalesce(func.sum(VendorTransaction.alacak), 0).label("total_alacak")
    bakiye_col = (func.coalesce(func.sum(VendorTransaction.borc), 0) - func.coalesce(func.sum(VendorTransaction.alacak), 0)).label("bakiye")
    unmatched_col = func.sum(
        sa_case((
            (VendorTransaction.borc > 0) & (VendorTransaction.match_number.is_(None)),
            1,
        ), else_=0)
    ).label("unmatched_count")

    query = (
        db.query(
            Vendor.id,
            Vendor.hesap_kodu,
            Vendor.hesap_adi,
            Vendor.payment_days,
            Vendor.status,
            total_borc_col,
            total_alacak_col,
            bakiye_col,
            func.count(VendorTransaction.id).label("transaction_count"),
            unmatched_col,
        )
        .outerjoin(VendorTransaction, Vendor.id == VendorTransaction.vendor_id)
        .group_by(Vendor.id, Vendor.hesap_kodu, Vendor.hesap_adi, Vendor.payment_days, Vendor.status)
    )

    if search:
        s_escaped = search.strip()[:200].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_term = f"%{s_escaped}%"
        query = query.filter(
            (Vendor.hesap_kodu.ilike(search_term, escape="\\")) |
            (Vendor.hesap_adi.ilike(search_term, escape="\\"))
        )

    if hide_zero:
        query = query.having(
            (func.coalesce(func.sum(VendorTransaction.borc), 0) - func.coalesce(func.sum(VendorTransaction.alacak), 0)) != 0
        )

    hesap_adi_tr = collate(Vendor.hesap_adi, "tr-TR-x-icu")
    sort_map = {
        "hesap_adi": hesap_adi_tr,
        "total_borc": total_borc_col,
        "total_alacak": total_alacak_col,
        "bakiye": bakiye_col,
    }
    if sort_by and sort_by in sort_map:
        order_col = sort_map[sort_by]
        order_expr = desc(order_col) if sort_dir == "desc" else order_col
    else:
        order_expr = hesap_adi_tr

    total = query.count()
    rows = (
        query.order_by(order_expr)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for row in rows:
        items.append(VendorResponse(
            id=row.id,
            hesap_kodu=row.hesap_kodu,
            hesap_adi=row.hesap_adi,
            payment_days=row.payment_days,
            status=row.status,
            total_borc=float(row.total_borc),
            total_alacak=float(row.total_alacak),
            bakiye=float(row.bakiye),
            transaction_count=row.transaction_count,
            unmatched_count=int(row.unmatched_count or 0),
        ).model_dump())

    return page_meta(items, total, page, page_size)


# ─── Cari Detay ─────────────────────────────────────────

@router.get("/vendors/{vendor_id}")
def get_vendor_detail(
    vendor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Cari detayını ve işlemlerini getir."""
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")

    totals = (
        db.query(
            func.coalesce(func.sum(VendorTransaction.borc), 0),
            func.coalesce(func.sum(VendorTransaction.alacak), 0),
        )
        .filter(VendorTransaction.vendor_id == vendor_id)
        .first()
    )
    total_borc = float(totals[0])
    total_alacak = float(totals[1])

    running_balance = func.sum(VendorTransaction.borc - VendorTransaction.alacak).over(
        order_by=[VendorTransaction.date.asc(), VendorTransaction.id.asc()]
    ).label("running_balance")

    total_count = (
        db.query(func.count(VendorTransaction.id))
        .filter(VendorTransaction.vendor_id == vendor_id)
        .scalar()
        or 0
    )
    rows = (
        db.query(VendorTransaction, running_balance)
        .filter(VendorTransaction.vendor_id == vendor_id)
        .order_by(VendorTransaction.date.desc(), VendorTransaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    transactions = [row[0] for row in rows]

    dept_map, cat_map, user_map = _build_dept_cat_user_maps(db, transactions)

    items = []
    for tx, rb in rows:
        item = _build_tx_response(tx, dept_map, cat_map, user_map)
        item["bakiye"] = float(rb) if rb is not None else None
        items.append(item)

    return {
        "vendor": VendorDetailResponse(
            id=vendor.id,
            hesap_kodu=vendor.hesap_kodu,
            hesap_adi=vendor.hesap_adi,
            payment_days=vendor.payment_days,
            status=vendor.status,
            total_borc=total_borc,
            total_alacak=total_alacak,
            bakiye=total_borc - total_alacak,
        ).model_dump(),
        "transactions": {
            "items": items,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "pages": math.ceil(total_count / page_size) if total_count > 0 else 1,
        },
    }


# ─── Cari Banka İşlemleri ────────────────────────────────

@router.get("/vendors/{vendor_id}/bank-transactions")
def get_vendor_bank_transactions(
    vendor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Cariye eşlenmiş banka işlemlerini listele."""
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")

    query = (
        db.query(BankTransaction, BankAccount)
        .join(BankAccount, BankTransaction.account_id == BankAccount.id)
        .filter(BankTransaction.vendor_id == vendor_id)
    )

    total = query.count()
    rows = (
        query.order_by(BankTransaction.date.desc(), BankTransaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for tx, acc in rows:
        items.append({
            "id": tx.id,
            "date": tx.date.isoformat(),
            "description": tx.description,
            "amount": abs(float(tx.amount)),
            "type": tx.type,
            "bank_name": acc.bank_name,
            "iban": acc.iban,
            "receipt_no": tx.receipt_no,
            "tag_note": tx.tag_note,
        })

    return page_meta(items, total, page, page_size)


# ─── Ödeme Vadesi Güncelleme ─────────────────────────────

@router.patch("/vendors/{vendor_id}/payment-days")
def update_vendor_payment_days(
    vendor_id: int,
    body: VendorPaymentDaysUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari ödeme vade gün sayısını güncelle ve ödeme tarihlerini yeniden hesapla."""
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")

    approval_resp = check_approval(db, "finance.cariler", vendor_id, current_user.id, "update", body.model_dump())
    if approval_resp:
        return approval_resp

    if body.payment_days < 0:
        raise HTTPException(status_code=400, detail="Ödeme vadesi negatif olamaz")

    old_days = vendor.payment_days

    try:
        updated_count = vendor_service.apply_vendor_update(db, vendor, {"payment_days": body.payment_days})
        log_action(
            db, current_user.id, "update", "vendor",
            entity_id=vendor_id,
            details=f"Ödeme vadesi güncellendi: {old_days} → {body.payment_days} gün ({updated_count} işlem yeniden hesaplandı)",
            ip_address=get_client_ip(request),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Vade güncelleme hatası (vendor_id=%s): %s", vendor_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ödeme vadesi güncellenirken bir veritabanı hatası oluştu.")

    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "update")

    return {
        "payment_days": vendor.payment_days,
        "updated_transactions": updated_count,
    }


# ─── Firma Durumu Güncelleme ─────────────────────────────

@router.patch("/vendors/{vendor_id}/status")
def update_vendor_status(
    vendor_id: int,
    body: VendorStatusUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari firma durumunu güncelle (normal / ödeme yasaklısı)."""
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")

    if body.status not in VENDOR_STATUS_CHOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz durum. Geçerli değerler: {', '.join(VENDOR_STATUS_CHOICES)}",
        )

    approval_resp = check_approval(db, "finance.cariler", vendor_id, current_user.id, "update", body.model_dump())
    if approval_resp:
        return approval_resp

    old_status = vendor.status

    try:
        vendor_service.apply_vendor_update(db, vendor, {"status": body.status})
        log_action(
            db, current_user.id, "update", "vendor",
            entity_id=vendor_id,
            details=f"Firma durumu güncellendi: {old_status} → {body.status}",
            ip_address=get_client_ip(request),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Firma durumu güncelleme hatası (vendor_id=%s): %s", vendor_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Firma durumu güncellenirken bir hata oluştu.")

    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "update")

    return {"status": vendor.status}
