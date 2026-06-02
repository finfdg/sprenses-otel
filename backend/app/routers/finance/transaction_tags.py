from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.bank_transaction import BankTransaction
from app.models.transaction_category import TransactionCategory
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.schemas.transaction_tag import (
    BulkTagAssignment,
    CategoryCreate,
    TagAssignment,
    TransactionCategoryResponse,
)
from app.utils.audit import log_action
from app.utils.auto_tagger import (
    PAYMENT_METHOD_LABELS,
    auto_detect_payment_methods,
    auto_match_vendors,
    auto_tag_transactions,
)
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.finance_helpers import MIN_DATE, validate_category

# Eşleştirme numarası ve ödeme yöntemi seçimi gerektiren kategoriler
CATEGORIES_WITH_MATCH = {"Cari", "Personel", "Vergi/SGK", "Kira", "Elektrik Faturası", "Su Faturası", "Aidat", "İade"}

router = APIRouter()


@router.get("/tags/categories")
def list_categories(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Tüm kategorileri listele."""
    cats = (
        db.query(TransactionCategory)
        .filter(TransactionCategory.is_active.is_(True))
        .order_by(TransactionCategory.sort_order)
        .all()
    )
    return [
        TransactionCategoryResponse.model_validate(c).model_dump()
        for c in cats
    ]


@router.post("/tags/categories")
def create_category(
    data: CategoryCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Yeni kategori oluştur."""
    # İsim tekrarı kontrolü
    existing = (
        db.query(TransactionCategory)
        .filter(TransactionCategory.name == data.name.strip())
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Bu isimde bir kategori zaten var")

    # Yeni sort_order: mevcut en yüksek + 1
    max_order = (
        db.query(func.max(TransactionCategory.sort_order)).scalar() or 0
    )

    cat = TransactionCategory(
        name=data.name.strip(),
        color=data.color,
        sort_order=max_order + 1,
    )
    db.add(cat)

    log_action(
        db, current_user.id, "create", "transaction_category",
        details=f"Yeni kategori: {cat.name}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(cat)

    return TransactionCategoryResponse.model_validate(cat).model_dump()


@router.get("/tags/untagged-count")
def untagged_count(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Etiketlenmemiş işlem sayısı (2026-01-01 sonrası)."""
    count = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.category_id.is_(None),
            BankTransaction.date >= MIN_DATE,
        )
        .count()
    )
    return {"count": count}


def _next_match_number(db: Session) -> int:
    """PostgreSQL sequence ile atomik, race-condition-safe eşleştirme numarası üret.

    MAX()+1 yerine veritabanı dizisi kullanılır — eş zamanlı çağrılarda çakışma olmaz.
    """
    return db.execute(sa_text("SELECT nextval('match_number_seq')")).scalar()


@router.patch("/tags/transactions/{tx_id}")
def tag_transaction(
    tx_id: int,
    data: TagAssignment,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Tekil işlem etiketle.

    Cari/Personel/Vergi/SGK gibi kategorilerde:
    - Otomatik eşleştirme numarası atanır
    - Ödeme yöntemi kaydedilir
    - Cari seçildiyse, carideki ilgili işleme de aynı numara + ödeme yöntemi yazılır
    """
    tx = db.query(BankTransaction).filter(BankTransaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    # Önceki eşleştirmeyi temizle (cari + banka pair tarafında da)
    if tx.match_number is not None:
        old_match = tx.match_number
        db.query(VendorTransaction).filter(
            VendorTransaction.match_number == old_match
        ).update({
            VendorTransaction.match_number: None,
            VendorTransaction.payment_method: None,
        }, synchronize_session=False)
        # Virman/Döviz Satım pair'i: karşı banka işlemini de temizle
        paired_txs = db.query(BankTransaction).filter(
            BankTransaction.match_number == old_match,
            BankTransaction.id != tx_id,
        ).all()
        for ptx in paired_txs:
            ptx.category_id = None
            ptx.tag_note = None
            ptx.tag_source = None
            ptx.match_number = None
            ptx.payment_method = None
            ptx.vendor_id = None
            db.flush()
            finance_event_svc.sync_tag(
                db, ptx.id,
                category_id=None, category_name=None, category_color=None,
                tag_note=None, tag_source=None, payment_method=None,
                match_number=None, vendor_id=None,
            )
        tx.match_number = None

    cat = validate_category(db, data.category_id)
    cat_name = cat.name if cat else None

    tx.category_id = data.category_id
    tx.tag_note = data.tag_note
    tx.tag_source = "manual" if data.category_id is not None else None

    # Cari eşleştirme
    vendor_name = None
    if data.vendor_id is not None:
        vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Cari bulunamadı")
        tx.vendor_id = data.vendor_id
        vendor_name = vendor.hesap_adi
        if not data.tag_note:
            tx.tag_note = vendor.hesap_adi
    else:
        tx.vendor_id = None

    # Ödeme yöntemi
    if data.payment_method is not None:
        tx.payment_method = data.payment_method

    # Eşleştirme numarası — belirli kategorilerde otomatik ata
    match_number = None
    if cat_name and cat_name in CATEGORIES_WITH_MATCH and data.payment_method:
        match_number = _next_match_number(db)
        tx.match_number = match_number

        # Cari seçildiyse → carideki aynı tarih+tutar işleme de yaz
        if data.vendor_id and tx.date:
            amt = abs(float(tx.amount))
            if cat_name == "İade":
                # İade: banka tarafında gelir (income), cari tarafında alacak
                vendor_tx = (
                    db.query(VendorTransaction)
                    .filter(
                        VendorTransaction.vendor_id == data.vendor_id,
                        VendorTransaction.alacak == amt,
                        VendorTransaction.match_number.is_(None),
                    )
                    .order_by(func.abs(VendorTransaction.date - tx.date))
                    .first()
                )
            else:
                # Normal: banka tarafında gider (expense), cari tarafında borç
                vendor_tx = (
                    db.query(VendorTransaction)
                    .filter(
                        VendorTransaction.vendor_id == data.vendor_id,
                        VendorTransaction.date == tx.date,
                        VendorTransaction.borc == amt,
                        VendorTransaction.match_number.is_(None),
                    )
                    .first()
                )
            if vendor_tx:
                vendor_tx.match_number = match_number
                vendor_tx.payment_method = data.payment_method

    # Virman / Döviz Satım: karşı taraftaki işlemi de otomatik etiketle
    CATEGORIES_AUTO_PAIR = {"Virman", "Döviz Satım"}
    counterpart = None
    if cat_name and cat_name in CATEGORIES_AUTO_PAIR:
        opposite_type = "income" if tx.type == "expense" else "expense"
        counterpart = (
            db.query(BankTransaction)
            .filter(
                BankTransaction.date == tx.date,
                BankTransaction.type == opposite_type,
                func.abs(BankTransaction.amount) == func.abs(tx.amount),
                BankTransaction.id != tx.id,
                BankTransaction.category_id.is_(None),
            )
            .first()
        )
        if not counterpart:
            # Tutam tam eşleşmiyorsa %2 toleransla ara
            amt = abs(float(tx.amount))
            counterpart = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.date == tx.date,
                    BankTransaction.type == opposite_type,
                    func.abs(BankTransaction.amount) >= amt * 0.98,
                    func.abs(BankTransaction.amount) <= amt * 1.02,
                    BankTransaction.id != tx.id,
                    BankTransaction.category_id.is_(None),
                )
                .first()
            )
        if counterpart:
            if not match_number:
                match_number = _next_match_number(db)
                tx.match_number = match_number
            counterpart.category_id = data.category_id
            counterpart.tag_note = data.tag_note
            counterpart.tag_source = "manual"
            counterpart.match_number = match_number
            counterpart.payment_method = tx.payment_method
            # Karşı tarafın finance_event'ini de güncelle
            db.flush()
            finance_event_svc.sync_tag(
                db, counterpart.id,
                category_id=counterpart.category_id,
                category_name=cat_name,
                category_color=cat.color if cat else None,
                tag_note=counterpart.tag_note,
                tag_source="manual",
                payment_method=counterpart.payment_method,
                match_number=match_number,
                vendor_id=None,
            )

    # Etiket kaldırma — karşı taraftaki pair'i de temizle
    if data.category_id is None:
        tx.payment_method = None
        tx.match_number = None
        tx.vendor_id = None
        # match_number ile eşleşen karşı tarafı da temizle (önceki adımda zaten
        # tx.match_number temizleniyor ama 138-146 satırlarında pair VendorTransaction
        # temizleniyor, BankTransaction pair'i de temizleyelim)

    if cat_name:
        details = f"Etiketlendi: {cat_name}"
        if match_number:
            details += f" [#{match_number}]"
        if vendor_name:
            details += f" | Cari: {vendor_name}"
        if data.payment_method:
            details += f" | Ödeme: {data.payment_method}"
    else:
        details = "Etiket kaldırıldı"

    log_action(
        db, current_user.id, "update", "bank_transaction",
        entity_id=tx_id, details=details,
        ip_address=get_client_ip(request),
    )
    db.flush()
    # finance_events etiket senkronizasyonu
    finance_event_svc.sync_tag(
        db, tx_id,
        category_id=tx.category_id,
        category_name=cat.name if cat else None,
        category_color=cat.color if cat else None,
        tag_note=tx.tag_note,
        tag_source=tx.tag_source,
        payment_method=tx.payment_method,
        match_number=tx.match_number,
        vendor_id=tx.vendor_id,
    )
    db.commit()
    broadcast_finance_update(background_tasks, "cash_flow", "tag")

    # Virman/Döviz pair'in ID'sini döndür — frontend karşı tarafı da güncellesin
    paired_tx_id = None
    if cat_name and cat_name in CATEGORIES_AUTO_PAIR and counterpart:
        paired_tx_id = counterpart.id

    return {"ok": True, "vendor_name": vendor_name, "match_number": match_number, "paired_tx_id": paired_tx_id}


@router.post("/tags/transactions/bulk")
def bulk_tag_transactions(
    data: BulkTagAssignment,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Toplu etiket atama."""
    if not data.transaction_ids:
        raise HTTPException(status_code=400, detail="İşlem listesi boş")

    cat = validate_category(db, data.category_id)
    cat_name = cat.name if cat else None

    txs = (
        db.query(BankTransaction)
        .filter(BankTransaction.id.in_(data.transaction_ids))
        .all()
    )

    # Cari doğrulama
    vendor_name = None
    if data.vendor_id is not None:
        vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Cari bulunamadı")
        vendor_name = vendor.hesap_adi

    for tx in txs:
        tx.category_id = data.category_id
        tx.tag_note = data.tag_note
        tx.tag_source = "manual" if data.category_id is not None else None
        tx.vendor_id = data.vendor_id

    details = f"Toplu etiketleme: {len(txs)} işlem"
    if cat_name:
        details += f" - {cat_name}"
    if vendor_name:
        details += f" | Cari: {vendor_name}"

    log_action(
        db, current_user.id, "update", "bank_transaction",
        details=details,
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, "cash_flow", "tag")

    return {"ok": True, "count": len(txs)}


@router.post("/tags/auto-tag")
def run_auto_tag(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Etiketlenmemiş işlemlere otomatik kural uygula + ödeme yöntemlerini tespit et."""
    tagged, total = auto_tag_transactions(db)

    # Ödeme yöntemi tespiti (boş olanları doldur)
    pm_counts = auto_detect_payment_methods(db)
    pm_total = sum(pm_counts.values())

    details = f"Otomatik etiketleme: {tagged}/{total} işlem etiketlendi"
    if pm_total > 0:
        details += f", {pm_total} işlemde ödeme yöntemi tespit edildi"

    log_action(
        db, current_user.id, "update", "bank_transaction",
        details=details,
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, "cash_flow", "auto_tag")

    return {"tagged": tagged, "total_untagged": total, "payment_methods_detected": pm_total}


@router.get("/tags/payment-methods")
def list_payment_methods(
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Ödeme yöntemi listesini döndür."""
    return PAYMENT_METHOD_LABELS


@router.post("/tags/auto-match-vendors")
def run_auto_match_vendors(
    request: Request,
    mode: Optional[str] = Query("name", pattern="^(name|amount|both)$"),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Etiketsiz banka işlemlerini cari hesaplarla otomatik eşleştir.

    Modlar:
    - name: Cari adı banka açıklamasında geçiyor
    - amount: Aynı tarih + aynı tutar eşleşmesi
    - both: Hem isim hem tutar eşleşmeli (en güvenilir)

    dry_run=true ile önce sonucu görebilirsiniz.
    """
    result = auto_match_vendors(db, mode=mode, dry_run=dry_run)

    if not dry_run and result["matched"] > 0:
        log_action(
            db, current_user.id, "update", "bank_transaction",
            details=f"Cari otomatik eşleştirme ({mode}): {result['matched']} işlem, {result['vendors_used']} cari",
            ip_address=get_client_ip(request),
        )
        db.commit()

    return result
