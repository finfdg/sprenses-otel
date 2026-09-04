"""Cari listesi, detay, banka işlemleri, özet ve vade/durum/iletişim güncelleme.

**Yeniden yapılandırma (2026-09-02):** `get_vendors_summary` ve `get_vendor_detail` gövdeleri
BİREBİR `app/services/vendor_service.py`'ye (`vendors_summary` / `vendor_detail`) taşındı;
bu iki endpoint ince sarmalayıcıdır (imza, izin kodu ve yanıt değişmedi). Taşınan adlar +
`_helpers`'tan taşınan `_build_tx_response` / `_build_dept_cat_user_maps` geriye uyumluluk için
modül düzeyinde yeniden dışa verilir (`services/audit_finance_invariants.py` endpoint
fonksiyonlarını bu yoldan `(db=db, _=None)` ile çağırır).
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import case as sa_case
from sqlalchemy import collate, desc, func
from sqlalchemy.orm import Session

from app.approval.approval_check import check_approval
from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.user import User
from app.models.vendor import STATUS_PAYMENT_BANNED, VENDOR_STATUS_CHOICES, Vendor
from app.models.vendor_transaction import VendorTransaction
from app.realtime.finance_broadcast import broadcast_finance_update
from app.schemas.vendor import (
    VendorContactUpdate,
    VendorPaymentDaysUpdate,
    VendorResponse,
    VendorStatusUpdate,
)
from app.services import vendor_service
from app.services.vendor_fifo import calculate_overdue_by_vendor
from app.services.vendor_service import (  # noqa: F401 — geriye uyumluluk: testler/parmak izi bu yoldan import eder (2026-09-02 çıkarımı)
    _build_dept_cat_user_maps,
    _build_tx_response,
    vendor_detail,
    vendors_summary,
)
from app.utils.audit import log_action
from app.utils.pagination import page_meta

from ._helpers import logger

router = APIRouter()


# ─── Cari Özet ───────────────────────────────────────────

@router.get("/vendors/summary")
def get_vendors_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Tüm carilerin toplam borç/alacak/bakiye özetini getir."""
    return vendors_summary(db)


# ─── Cari Listesi ────────────────────────────────────────

@router.get("/vendors")
def list_vendors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, pattern="^(hesap_adi|total_borc|total_alacak|bakiye|overdue)$"),
    sort_dir: Optional[str] = Query("asc", pattern="^(asc|desc)$"),
    hide_zero: bool = Query(False),
    overdue_only: bool = Query(False, description="Yalnız vadesi geçmiş (eşleşmemiş, geçmiş vadeli) faturası olan cariler"),
    banned_only: bool = Query(False, description="Yalnız ödeme yasaklısı cariler"),
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

    # Satır çipleri ("N gecikmiş") + gecikmiş sıralaması için tek FIFO haritası
    overdue_map = calculate_overdue_by_vendor(db)

    if overdue_only:
        # Vadesi geçmiş = NET ödenmemiş+gecikmiş faturası olan cariler (detay kartıyla aynı
        # FIFO kaynağı → çip ile kart tutarlı). Brüt SQL toplamı yerine net FIFO kümesi.
        overdue_ids = [vid for vid, (amt, _cnt) in overdue_map.items() if amt > 0]
        query = query.filter(Vendor.id.in_(overdue_ids or [-1]))

    if banned_only:
        query = query.filter(Vendor.status == STATUS_PAYMENT_BANNED)

    hesap_adi_tr = collate(Vendor.hesap_adi, "tr-TR-x-icu")
    sort_map = {
        "hesap_adi": hesap_adi_tr,
        "total_borc": total_borc_col,
        "total_alacak": total_alacak_col,
        "bakiye": bakiye_col,
    }
    total = query.count()

    if sort_by == "overdue":
        # Gecikmiş tutar SQL kolonunda yok (FIFO türevi) → tüm satırlar çekilip
        # Python'da sıralanır; cari sayısı küçük (≈300), maliyet ihmal edilebilir.
        rows = query.order_by(hesap_adi_tr).all()
        reverse = sort_dir == "desc"
        rows.sort(key=lambda r: overdue_map.get(r.id, (0.0, 0))[0], reverse=reverse)
        rows = rows[(page - 1) * page_size: page * page_size]
    else:
        if sort_by and sort_by in sort_map:
            order_col = sort_map[sort_by]
            order_expr = desc(order_col) if sort_dir == "desc" else order_col
        else:
            order_expr = hesap_adi_tr
        rows = (
            query.order_by(order_expr)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    items = []
    for row in rows:
        row_overdue, row_overdue_count = overdue_map.get(row.id, (0.0, 0))
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
            overdue=row_overdue,
            overdue_count=row_overdue_count,
        ).model_dump())

    return page_meta(items, total, page, page_size)


# ─── Cari Detay ─────────────────────────────────────────

@router.get("/vendors/{vendor_id}")
def get_vendor_detail(
    vendor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: Optional[str] = Query(None, pattern="^(date|evrak_no|transaction_type|borc|alacak|bakiye)$"),
    sort_dir: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Cari detayını ve işlemlerini getir.

    Varsayılan sıralama tarih DESC (en yeni üstte). `sort_by` whitelist'li kolon
    sıralaması sunar; `bakiye` sıralaması kronolojik kümülatif bakiye kolonuna göredir.
    """
    return vendor_detail(db, vendor_id, page, page_size, sort_by, sort_dir)


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


# ─── Firma İletişim Bilgileri Güncelleme ─────────────────

@router.patch("/vendors/{vendor_id}/contact")
def update_vendor_contact(
    vendor_id: int,
    body: VendorContactUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari iletişim bilgilerini (yetkili/telefon/e-posta) güncelle.

    Finansal etkisi yok (finance_events'e dokunmaz) → onaydan muaf (payment_deferral/
    manuel-banka gibi operasyonel-özel istisna); use + audit + broadcast uygulanır.
    """
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")

    fields = body.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(vendor, key, (value.strip() if isinstance(value, str) and value.strip() else None) if value is not None else None)

    try:
        log_action(
            db, current_user.id, "update", "vendor",
            entity_id=vendor_id,
            details=f"İletişim bilgileri güncellendi ({', '.join(fields.keys())})",
            ip_address=get_client_ip(request),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("İletişim güncelleme hatası (vendor_id=%s): %s", vendor_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="İletişim bilgileri güncellenirken bir hata oluştu.")

    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "update")

    return {
        "contact_person": vendor.contact_person,
        "phone": vendor.phone,
        "email": vendor.email,
    }
