"""Kalıcı Öteleme domain servis katmanı — ödeme kaleminin ertelenmiş tarihi (HTTP'siz).

Bir ödeme kalemi (cari ödeme, çek, kredi taksiti, KK ekstresi, planlı gider/gelir)
ileri bir tarihe "ötelenince" tercih `payment_deferrals` tablosunda KALICI saklanır.
`finance_event_service._upsert` her FinanceEvent yazımında burayı sorgular (modül-içi
cache'li) → Sedna sync / FIFO yeniden yazımı ötelemeyi korur.

Fonksiyonlar commit ETMEZ — çağıran (endpoint) commit eder.

`resync_deferred_event`: ötelemenin hemen FinanceEvent.event_date'e yansıması için
ilgili kaynağı bulup uygun `upsert_*`'ı çağırır (cache invalidate edildiğinden
_upsert artık ertelenmiş tarihi okur).
"""

import logging
from datetime import date
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.payment_deferral import PaymentDeferral

logger = logging.getLogger(__name__)

# Ötelenebilir kaynak türleri — "bank" HARİÇ (gerçekleşmiş nakit; en kalabalık FE türü).
DEFERRABLE_SOURCE_TYPES = frozenset({
    "vendor_payment", "check", "credit", "cc_payment",
    "tax", "recurring", "salary", "withholding", "sgk",
    "dividend", "rent_income", "rent_expense",
})

# scheduled_entry türleri (upsert_scheduled_entry ile yazılır) → direction eşlemesi
_SCHEDULED_DIRECTION = {
    "tax": -1,
    "recurring": -1,
    "salary": -1,
    "withholding": -1,
    "sgk": -1,
    "dividend": -1,
    "rent_expense": -1,
    "rent_income": 1,   # tek gelir türü
}

# ─── Modül-içi cache (bulk sync'te her FE'de SELECT yapmamak için) ───────────
# finance_event_service._compute_cache deseni gibi basit dict cache.
_deferral_cache: Dict[str, Optional[Dict[Tuple[str, int], date]]] = {"data": None}


def get_deferral_map(db: Session) -> Dict[Tuple[str, int], date]:
    """(source_type, source_id) → deferred_to haritası (modül-içi cache'li).

    _upsert her FinanceEvent yazımında çağırır → her seferinde SELECT bulk sync'i
    yavaşlatır. apply/clear cache'i invalidate eder.
    """
    cached = _deferral_cache["data"]
    if cached is not None:
        return cached

    rows = db.query(
        PaymentDeferral.source_type,
        PaymentDeferral.source_id,
        PaymentDeferral.deferred_to,
    ).all()
    mapping: Dict[Tuple[str, int], date] = {
        (st, sid): dt for st, sid, dt in rows
    }
    _deferral_cache["data"] = mapping
    return mapping


def invalidate_deferral_cache() -> None:
    """Öteleme cache'ini boşalt (apply/clear sonrası + test izolasyonu)."""
    _deferral_cache["data"] = None


def apply_deferral(
    db: Session,
    source_type: str,
    source_id: int,
    deferred_to: date,
    user_id: Optional[int],
    note: Optional[str] = None,
) -> PaymentDeferral:
    """Öteleme upsert (doğal anahtar source_type+source_id). Commit ETMEZ."""
    existing = (
        db.query(PaymentDeferral)
        .filter(
            PaymentDeferral.source_type == source_type,
            PaymentDeferral.source_id == source_id,
        )
        .first()
    )
    if existing:
        existing.deferred_to = deferred_to
        existing.created_by = user_id
        if note is not None:
            existing.note = note
        deferral = existing
    else:
        deferral = PaymentDeferral(
            source_type=source_type,
            source_id=source_id,
            deferred_to=deferred_to,
            created_by=user_id,
            note=note,
        )
        db.add(deferral)
    db.flush()
    invalidate_deferral_cache()
    return deferral


def clear_deferral(db: Session, source_type: str, source_id: int) -> bool:
    """Ötelemeyi kaldır (varsa). Döner: silindi mi. Commit ETMEZ."""
    deleted = (
        db.query(PaymentDeferral)
        .filter(
            PaymentDeferral.source_type == source_type,
            PaymentDeferral.source_id == source_id,
        )
        .delete(synchronize_session=False)
    )
    db.flush()
    invalidate_deferral_cache()
    return bool(deleted)


def resync_deferred_event(db: Session, source_type: str, source_id: int) -> None:
    """İlgili kaynağı bulup uygun upsert_*'ı çağırarak FinanceEvent'i yeniden yaz.

    Öteleme apply/clear sonrası çağrılır → cache invalidate edildiğinden _upsert
    ertelenmiş (veya orijinal) tarihi okur ve event_date güncellenir. Commit ETMEZ.

    Kaynak bulunamazsa (silinmiş) sessizce geçer — FE zaten yoktur.
    """
    from app.utils.finance_event_service import finance_event_svc

    if source_type == "vendor_payment":
        # FIFO + amount hesabı sync ile gelir; öteleme _upsert override'ında uygulanır.
        from app.utils.sync_vendor_fifo import sync_vendor_finance_events
        sync_vendor_finance_events(db)
        return

    if source_type == "check":
        from app.models.bank_transaction import BankTransaction
        from app.models.check import Check
        check = db.query(Check).filter(Check.id == source_id).first()
        if not check:
            return
        bank_tx = None
        if check.bank_transaction_id:
            bank_tx = db.query(BankTransaction).filter(
                BankTransaction.id == check.bank_transaction_id
            ).first()
        finance_event_svc.upsert_check(db, check, bank_tx)
        return

    if source_type == "credit":
        from app.models.credit_product import CreditPayment, CreditProduct
        payment = db.query(CreditPayment).filter(CreditPayment.id == source_id).first()
        if not payment:
            return
        product = db.query(CreditProduct).filter(
            CreditProduct.id == payment.credit_product_id
        ).first()
        if product:
            finance_event_svc.upsert_credit_payment(db, payment, product)
        return

    if source_type == "cc_payment":
        from app.models.credit_card_statement import CreditCardStatement
        from app.models.credit_product import CreditProduct
        stmt = db.query(CreditCardStatement).filter(
            CreditCardStatement.id == source_id
        ).first()
        if not stmt:
            return
        product = db.query(CreditProduct).filter(
            CreditProduct.id == stmt.credit_product_id
        ).first()
        if product:
            finance_event_svc.upsert_cc_statement(db, stmt, product)
        return

    if source_type in _SCHEDULED_DIRECTION:
        from app.models.scheduled import ScheduledEntry
        entry = db.query(ScheduledEntry).filter(ScheduledEntry.id == source_id).first()
        if not entry:
            return
        finance_event_svc.upsert_scheduled_entry(
            db, entry, direction=_SCHEDULED_DIRECTION[source_type]
        )
        return

    logger.warning("resync_deferred_event: bilinmeyen source_type=%s", source_type)
