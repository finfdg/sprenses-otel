"""Cari hesap (vendor) modeli — hesap bilgileri ve vade yönetimi."""

from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.vendor_transaction import VendorTransaction

# Firma durumu sabitleri
STATUS_NORMAL = "normal"
STATUS_PAYMENT_BANNED = "odeme_yasaklisi"

VENDOR_STATUS_CHOICES = [STATUS_NORMAL, STATUS_PAYMENT_BANNED]
VENDOR_STATUS_LABELS = {
    STATUS_NORMAL: "Normal",
    STATUS_PAYMENT_BANNED: "Ödeme Yasaklısı",
}


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        Index("ix_vendors_hesap_kodu", "hesap_kodu"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hesap_kodu: Mapped[str] = mapped_column(String(50), unique=True)
    hesap_adi: Mapped[str] = mapped_column(String(300))
    payment_days: Mapped[int] = mapped_column(Integer, server_default="90")
    status: Mapped[str] = mapped_column(String(30), server_default="normal")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    transactions: Mapped[List["VendorTransaction"]] = relationship(
        "VendorTransaction", back_populates="vendor", cascade="all, delete-orphan",
    )
