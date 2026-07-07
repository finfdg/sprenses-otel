"""Bekletme (hold) domain servis katmanı — bekleyen nakit akım kaleminin akım-dışı park durumu.

Bir BEKLEYEN kalem "beklemeye alınınca" tercih `cash_flow_holds` tablosunda KALICI saklanır
(ortak — tüm finans kullanıcıları görür). Nakit akım hesapları (t_account / runway / eur_balances)
bu kümeye bakıp future-pending held kalemleri DIŞLAR (öteleme cache deseniyle aynı; commit ETMEZ,
çağıran commit eder).

Öteleme (deferral) tarih değiştirir → `resync` gerekir; bekletme yalnız dışlar → resync GEREKMEZ.
"""

import logging
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.cash_flow_hold import CashFlowHold

logger = logging.getLogger(__name__)

# Beklemeye alınabilir kaynak türleri.
# "bank" HARİÇ (gerçekleşmiş nakit, bekletilmez); "check" HARİÇ (kullanıcı kararı 2026-07-07:
# çek ödemeleri beklemeye alınamaz — çekin ödeme takvimi banka/ciro tarafında sabittir).
# "cc_projection" DAHİL: KK ekstre tahmini rezervi (yüklenmemiş cari ay = kart limiti) kart
# bazında (source_id = CreditProduct.id) beklemeye alınabilir — gerçek FE değil ama nakit
# planlamasında park edilebilmesi kullanıcı isteği (2026-07-07, kırmızı satır bekletilemiyor bulgusu).
HOLDABLE_SOURCE_TYPES = frozenset({
    "vendor_payment", "credit", "cc_payment", "cc_projection",
    "tax", "recurring", "salary", "withholding", "sgk",
    "dividend", "dividend_stopaj", "rent_income", "rent_expense", "advance",
})

# Modül-içi cache (bulk hesaplarda her kalemde SELECT yapmamak için) — deferral deseni.
_hold_cache: Dict[str, Optional[Set[Tuple[str, int]]]] = {"data": None}


def get_hold_set(db: Session) -> Set[Tuple[str, int]]:
    """Beklemeye alınmış (source_type, source_id) kümesi (modül-içi cache'li)."""
    cached = _hold_cache["data"]
    if cached is not None:
        return cached
    rows = db.query(CashFlowHold.source_type, CashFlowHold.source_id).all()
    result = {(st, sid) for st, sid in rows}
    _hold_cache["data"] = result
    return result


def invalidate_hold_cache() -> None:
    """Bekletme cache'ini boşalt (apply/clear sonrası + test izolasyonu)."""
    _hold_cache["data"] = None


def apply_hold(db: Session, source_type: str, source_id: int, user_id: Optional[int]) -> None:
    """Kalemi beklemeye al (idempotent upsert). Commit ETMEZ."""
    exists = (
        db.query(CashFlowHold.id)
        .filter(CashFlowHold.source_type == source_type, CashFlowHold.source_id == source_id)
        .first()
    )
    if not exists:
        db.add(CashFlowHold(source_type=source_type, source_id=source_id, created_by=user_id))
        db.flush()
        invalidate_hold_cache()


def clear_hold(db: Session, source_type: str, source_id: int) -> bool:
    """Bekletmeyi kaldır (varsa). Döner: silindi mi. Commit ETMEZ."""
    deleted = (
        db.query(CashFlowHold)
        .filter(CashFlowHold.source_type == source_type, CashFlowHold.source_id == source_id)
        .delete(synchronize_session=False)
    )
    db.flush()
    if deleted:
        invalidate_hold_cache()
    return bool(deleted)


def apply_holds_batch(
    db: Session,
    items: Iterable[Tuple[str, int]],
    held: bool,
    user_id: Optional[int],
) -> int:
    """Birden çok kalemi topluca beklemeye al (held=True) veya çıkar (held=False).

    Döner: etkilenen kalem sayısı. Commit ETMEZ. Geçersiz/holdable-dışı tür atlanır.
    """
    n = 0
    for source_type, source_id in items:
        if source_type not in HOLDABLE_SOURCE_TYPES:
            continue
        if held:
            apply_hold(db, source_type, source_id, user_id)
        else:
            clear_hold(db, source_type, source_id)
        n += 1
    return n
