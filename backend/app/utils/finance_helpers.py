"""Finans modülü ortak yardımcı fonksiyonlar ve sabitler."""

from datetime import date
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.transaction_category import TransactionCategory

# Nakit akım ve etiketleme için minimum tarih filtresi
MIN_DATE = date(2026, 1, 1)


def validate_category(db: Session, category_id: Optional[int]) -> Optional[TransactionCategory]:
    """Kategori ID doğrula. Geçersizse 404 fırlat, None ise None döner."""
    if category_id is None:
        return None
    cat = (
        db.query(TransactionCategory)
        .filter(TransactionCategory.id == category_id)
        .first()
    )
    if not cat:
        raise HTTPException(status_code=404, detail="Kategori bulunamadı")
    return cat
