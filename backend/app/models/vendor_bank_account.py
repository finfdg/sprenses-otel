"""Cari (vendor) banka hesabı — ödeme talimatında kullanılacak banka + IBAN.

Sedna muhasebe DB'sinde cari IBAN'ları boş olduğundan IBAN'lar Sprenses'te yönetilir.
Bir carinin **birden çok** IBAN'ı olabilir; ödeme talimatında biri seçilir
(varsayılan `is_default` otomatik gelir).
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.vendor import Vendor


class VendorBankAccount(Base):
    """Bir carinin banka hesabı (banka adı + IBAN). Bir cari → 0..N hesap."""
    __tablename__ = "vendor_bank_accounts"
    __table_args__ = (
        Index("ix_vendor_bank_vendor", "vendor_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vendors.id", ondelete="CASCADE"),
    )
    bank_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    iban: Mapped[str] = mapped_column(String(34))           # normalize: büyük harf, boşluksuz
    account_holder: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="bank_accounts")
