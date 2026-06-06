"""Ödeme talimat listesi modelleri — cari ödemeleri için toplu talimat hazırlama.

Kullanıcı carileri seçip bir ödeme talimat listesine ekler; her kalemin tutarı
carinin bakiyesinden (net borç) otomatik gelir ama manuel düzenlenebilir.
Liste kalıcıdır (kaydedilir, tekrar açılır), Excel/PDF olarak dışa aktarılabilir.
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vendor import Vendor

# Liste durumu sabitleri
PI_STATUS_DRAFT = "draft"        # Taslak — üzerinde çalışılıyor
PI_STATUS_COMPLETED = "completed"  # Tamamlandı — ödeme yapıldı/kapatıldı

PI_STATUS_CHOICES = [PI_STATUS_DRAFT, PI_STATUS_COMPLETED]
PI_STATUS_LABELS = {
    PI_STATUS_DRAFT: "Taslak",
    PI_STATUS_COMPLETED: "Tamamlandı",
}


class PaymentInstructionList(Base):
    """Ödeme talimat listesi başlığı."""

    __tablename__ = "payment_instruction_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default=PI_STATUS_DRAFT)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    items: Mapped[List["PaymentInstructionItem"]] = relationship(
        "PaymentInstructionItem",
        back_populates="instruction_list",
        cascade="all, delete-orphan",
        order_by="PaymentInstructionItem.sort_order",
    )


class PaymentInstructionItem(Base):
    """Ödeme talimat listesi kalemi — tek bir cariye ödeme satırı."""

    __tablename__ = "payment_instruction_items"
    __table_args__ = (
        Index("ix_pi_items_list", "list_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payment_instruction_lists.id", ondelete="CASCADE"),
    )
    # vendor silinse de kalem kaybolmasın diye snapshot alanları tutulur
    vendor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True,
    )
    hesap_kodu: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    hesap_adi: Mapped[str] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Numeric(15, 2), server_default="0")
    balance_snapshot: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    # Seçilen banka/IBAN snapshot'ı (carinin banka hesaplarından biri; cari/hesap silinse de kalır)
    bank_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    iban: Mapped[Optional[str]] = mapped_column(String(34), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    instruction_list: Mapped["PaymentInstructionList"] = relationship(
        "PaymentInstructionList", back_populates="items",
    )
    vendor: Mapped[Optional["Vendor"]] = relationship("Vendor")
