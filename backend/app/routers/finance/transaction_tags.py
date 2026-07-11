from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.exchange_rate import ExchangeRate
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
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.finance_helpers import MIN_DATE, validate_category

# Eşleştirme numarası ve ödeme yöntemi seçimi gerektiren kategoriler
CATEGORIES_WITH_MATCH = {"Cari", "Personel", "Vergi/SGK", "Kira", "Elektrik Faturası", "Su Faturası", "Aidat", "İade"}

# Faz 1 #11 — etiket kategorisi → kapatılabilecek planlı gider türleri (yalnız GİDER;
# banka çıkışı bu türlerin planlı girişini kanıtlar)
_SCHEDULED_CATEGORY_MAP = {
    "Vergi/SGK": ["tax", "sgk", "withholding"],
    "Personel": ["salary"],
    "Kira": ["rent_expense"],
}

# Karşı banka bacağı otomatik eşlenen kategoriler
CATEGORIES_AUTO_PAIR = {"Virman", "Döviz Satım"}

# Döviz Satım bacak eşlemesinde TL-değeri toleransı — banka müşteri kuru TCMB
# forex_buying'den birkaç puan sapabilir (canlı örnek: banka 53,253 ↔ TCMB ~53,4)
FX_PAIR_TOLERANCE = 0.05

router = APIRouter()


def _norm_currency(cur: Optional[str]) -> str:
    c = (cur or "TRY").strip().upper()
    return "TRY" if c in ("TL", "TRY") else c


def _rate_for(db: Session, currency: str, on_date) -> Optional[float]:
    """Para biriminin TL kuru — o tarihteki (veya öncesindeki son) TCMB forex_buying."""
    cur = _norm_currency(currency)
    if cur == "TRY":
        return 1.0
    r = (
        db.query(ExchangeRate)
        .filter(ExchangeRate.currency_code == cur, ExchangeRate.date <= on_date)
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    if not r or not r.forex_buying:
        return None
    unit = float(r.unit or 1) or 1
    return float(r.forex_buying) / unit


def _find_pair_counterpart(db: Session, tx: BankTransaction, cat_name: str) -> Optional[BankTransaction]:
    """Virman / Döviz Satım karşı banka bacağını bul.

    - **Virman:** AYNI para birimli hesaplar arası — tutar birebir, yoksa ±%2.
    - **Döviz Satım:** bacaklar FARKLI para birimli hesaplardadır (ör. EUR çıkış ↔ TL
      giriş); ham tutarlar karşılaştırılamaz — iki bacağın TL değeri TCMB kuruyla
      ±%5 içinde eşleşmelidir. (2026-07-03 bulgusu: kur gözetmeyen eski ±%2 ham-tutar
      araması, €36.428 satışına gerçek TL bacağı (₺1,94M) yerine aynı gün gelen
      €36.781'lik acente havalesini eşledi — TL bacağı ham tutarda asla bulunamazdı.)
    Birden çok aday varsa tutarı en yakın olan seçilir (.first() keyfîliği yerine).
    """
    opposite_type = "income" if tx.type == "expense" else "expense"
    candidates = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.date == tx.date,
            BankTransaction.type == opposite_type,
            BankTransaction.id != tx.id,
            BankTransaction.category_id.is_(None),
        )
        .all()
    )
    if not candidates:
        return None

    acc_cur = {a.id: _norm_currency(a.currency) for a in db.query(BankAccount).all()}
    tx_cur = acc_cur.get(tx.account_id, "TRY")
    amt = abs(float(tx.amount))

    if cat_name == "Virman":
        same_cur = [c for c in candidates if acc_cur.get(c.account_id, "TRY") == tx_cur]
        exact = [c for c in same_cur if abs(abs(float(c.amount)) - amt) < 0.01]
        if exact:
            return exact[0]
        close = [c for c in same_cur if amt * 0.98 <= abs(float(c.amount)) <= amt * 1.02]
        return min(close, key=lambda c: abs(abs(float(c.amount)) - amt)) if close else None

    # Döviz Satım — karşı bacak FARKLI para birimli hesapta, TL-değeri kurla eşleşmeli
    tx_rate = _rate_for(db, tx_cur, tx.date)
    if tx_rate is None or amt <= 0:
        return None
    tx_tl_value = amt * tx_rate
    best = None
    best_diff = None
    for c in candidates:
        c_cur = acc_cur.get(c.account_id, "TRY")
        if c_cur == tx_cur:
            continue  # aynı birimdeki hareket döviz bozma bacağı olamaz (TRAVE vakası)
        c_rate = _rate_for(db, c_cur, tx.date)
        if c_rate is None:
            continue
        diff = abs(abs(float(c.amount)) * c_rate - tx_tl_value) / tx_tl_value
        if diff <= FX_PAIR_TOLERANCE and (best_diff is None or diff < best_diff):
            best, best_diff = c, diff
    return best


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
    background_tasks: BackgroundTasks,
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
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "update")  # kategori dropdown'ları canlı tazelensin
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

        # Planlı gider köprüsü (Faz 1 #11): Vergi/SGK · Personel · Kira etiketi yalnız
        # banka bacağına numara veriyordu; scheduled_entry açık kalıp aynı dönemde
        # tahmin+gerçekleşen ÇİFT sayılıyordu. Ödeme ayına denk, tutarı ±%2 uyan TEK
        # açık giriş varsa banka kanıtıyla kapatılır; birden çok aday → öneri kuyruğu.
        if cat_name in _SCHEDULED_CATEGORY_MAP and not data.vendor_id and tx.date:
            from app.models.scheduled import ScheduledEntry
            from app.services.scheduled_service import close_entry_via_bank
            from app.utils.matching_service import _upsert_suggestion

            amt = abs(float(tx.amount))
            cands = (
                db.query(ScheduledEntry)
                .filter(ScheduledEntry.source_type.in_(_SCHEDULED_CATEGORY_MAP[cat_name]),
                        ScheduledEntry.is_paid == False,  # noqa: E712
                        ScheduledEntry.period_year == tx.date.year,
                        ScheduledEntry.period_month == tx.date.month,
                        ScheduledEntry.amount >= amt * 0.98,
                        ScheduledEntry.amount <= amt * 1.02)
                .all()
            )
            if len(cands) == 1:
                close_entry_via_bank(db, cands[0], tx)
            elif len(cands) > 1:
                for e in cands[:5]:
                    _upsert_suggestion(db, tx.id, e.source_type, e.id,
                                       float(e.amount), e.currency or "TRY", 50)

    # Virman / Döviz Satım: karşı taraftaki işlemi de otomatik etiketle
    # (kur-duyarlı arama — Virman aynı birim, Döviz Satım farklı birim + TCMB TL-değeri)
    counterpart = None
    if cat_name and cat_name in CATEGORIES_AUTO_PAIR:
        counterpart = _find_pair_counterpart(db, tx, cat_name)
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
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "tag")

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
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "tag")

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
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "auto_tag")

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
