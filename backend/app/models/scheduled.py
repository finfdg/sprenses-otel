"""Planlı gider tanımları ve girişleri — Vergi, Düzenli Ödeme, Maaş, Stopaj.

Tek bir tanım tablosu (scheduled_definitions) ve tek bir giriş tablosu
(scheduled_entries) ile 4 modül desteklenir. source_type alanı ile ayrışır.
"""
from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
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


class ScheduledDefinition(Base):
    """Planlı gider tanımı (vergi, düzenli ödeme, maaş, stopaj)."""
    __tablename__ = "scheduled_definitions"
    __table_args__ = (
        Index("ix_scheddef_type", "source_type"),
        Index("ix_scheddef_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(30))  # tax, recurring, salary, withholding
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(3), default="TRY")
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")  # monthly, quarterly, yearly
    payment_day: Mapped[int] = mapped_column(Integer, default=1)  # 1-28
    start_month: Mapped[int] = mapped_column(Integer, default=1)  # 1-12
    year: Mapped[int] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Cari (satıcı) bağlantısı — yalnız "recurring" için anlamlı (ör. Elektrik→CK, Su→ASAT).
    # Bağlıysa giriş tutarları/ödeme durumu cari gerçek faturadan senkronlanır (bk. recurring_vendor_sync).
    vendor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    # Cari fatura gecikmesi (ay): fatura tüketim ayından sonra kesiliyorsa kaç ay geri kaydırılır.
    # Su (ASAT) faturası ay başında gelir = önceki ay tüketimi → 1. Elektrik (CK) ay sonu = aynı ay → 0.
    billing_offset_months: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # True ise dönemin ödemesi BİR SONRAKİ ayın payment_day'inde yapılır (ör. Ocak dönemi → 10 Şubat).
    # salary/sgk/withholding zaten source_type bazlı +1 ay kayar; bu, diğer türlerde (recurring vb.)
    # tanım-bazlı aynı davranışı sağlar. entry_date bu bayrağa göre hesaplanır (_payment_date).
    pay_next_month: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    entries: Mapped[list["ScheduledEntry"]] = relationship(
        "ScheduledEntry", back_populates="definition",
        cascade="all, delete-orphan", lazy="dynamic",
    )
    creator: Mapped[Optional["User"]] = relationship("User")
    vendor: Mapped[Optional["Vendor"]] = relationship("Vendor")


class ScheduledEntry(Base):
    """Planlı giderin aylık/dönemsel girişi."""
    __tablename__ = "scheduled_entries"
    __table_args__ = (
        Index("ix_schedentry_source", "source_type", "definition_id"),
        Index("ix_schedentry_date", "entry_date"),
        Index("ix_schedentry_paid", "is_paid"),
        Index("ix_schedentry_period", "source_type", "period_year", "period_month"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    definition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scheduled_definitions.id", ondelete="CASCADE"),
    )
    source_type: Mapped[str] = mapped_column(String(30))  # denormalized
    entry_date: Mapped[date_type] = mapped_column(Date)  # gerçek ödeme tarihi
    period_month: Mapped[int] = mapped_column(Integer)   # hangi ayın kaydı (1-12)
    period_year: Mapped[int] = mapped_column(Integer)    # hangi yılın kaydı
    amount: Mapped[float] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(3), default="TRY")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # True → tutar/ödeme durumu cari gerçek faturadan senkronlandı (tahmini değil).
    # Bu aylarda recurring finance_event'i silinir (cari nakit akımı temsil eder, çift sayım önlenir).
    synced_from_cari: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    definition: Mapped["ScheduledDefinition"] = relationship(
        "ScheduledDefinition", back_populates="entries",
    )
