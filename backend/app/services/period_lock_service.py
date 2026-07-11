"""Dönem kilidi servisi (Faz C) — UYARI modu, bloklamayan.

`lock_date` (dahil) öncesi dönem kapatılmış sayılır. Kilit senkron/mutabakatı
DURDURMAZ; yalnız kilit-öncesi tarihli yeni uyuşmazlıklar ayrı vurgulu bildirimle
işaretlenir. Router + onay executor'ı AYNI fonksiyonları çağırır (D1-2).
"""
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models import FinancePeriodLock

logger = logging.getLogger(__name__)

# Süreç-içi cache (hold/deferral service deseni — tek-worker varsayımı)
_lock_cache: dict = {}


def invalidate_lock_cache() -> None:
    _lock_cache.clear()


def get_lock_date(db: Session) -> Optional[date]:
    """Aktif kilit tarihi (yoksa None). Süreç-içi cache'li."""
    if "d" in _lock_cache:
        return _lock_cache["d"]
    row = db.query(FinancePeriodLock).order_by(FinancePeriodLock.id).first()
    _lock_cache["d"] = row.lock_date if row else None
    return _lock_cache["d"]


def set_lock_date(db: Session, lock_date: Optional[date], user_id: Optional[int]) -> Optional[date]:
    """Kilit tarihini ata/temizle (None = kaldır). Tek satır upsert. Commit ETMEZ."""
    row = db.query(FinancePeriodLock).order_by(FinancePeriodLock.id).first()
    if lock_date is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(FinancePeriodLock(lock_date=lock_date, updated_by=user_id))
    else:
        row.lock_date = lock_date
        row.updated_by = user_id
    db.flush()
    invalidate_lock_cache()
    return lock_date
