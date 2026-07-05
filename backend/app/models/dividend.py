"""Kâr payı dağıtımı (temettü) modelleri — dağıtım + pay sahibi + taksit + ödeme.

Genel kurul kararıyla dağıtılan kâr payı; her pay sahibinin brüt payı, %15 stopaj kesintisi
ve net tutarı hesaplanır. Toplam kâr payı N taksite bölünür; her taksitte pay sahibi başına
brüt/stopaj/net ödeme satırı (dividend_payments) ayrı takip edilir.

Nakit akım: TAKSİT birimdir (dividend_installments) — her taksit İKİ finance_event üretir:
net (source_type "dividend", taksit günü) + stopaj (source_type "dividend_stopaj", ertesi ay
muhtasar 26'sı). Ödeme durumu pay sahibi × taksit satırlarından (dividend_payments) roll-up edilir.
"""

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
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


class DividendDistribution(Base):
    """Kâr payı dağıtım başlığı (genel kurul kararı)."""
    __tablename__ = "dividend_distributions"
    __table_args__ = (
        Index("ix_dividend_distributions_year", "year"),
        Index("ix_dividend_distributions_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    decision_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)  # Genel Kurul karar tarihi
    total_gross: Mapped[float] = mapped_column(Numeric(15, 2), default=0)  # dağıtılacak brüt kâr payı
    capital: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # sermaye / pay itibari değeri
    withholding_rate: Mapped[float] = mapped_column(Numeric(6, 4), default=0.15)  # 0.1500 = %15 stopaj
    installment_count: Mapped[int] = mapped_column(Integer, default=1)
    year: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active / cancelled
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    creator: Mapped[Optional["User"]] = relationship("User")
    shareholders: Mapped[List["DividendShareholder"]] = relationship(
        "DividendShareholder", back_populates="distribution",
        cascade="all, delete-orphan", order_by="DividendShareholder.sort_order",
    )
    installments: Mapped[List["DividendInstallment"]] = relationship(
        "DividendInstallment", back_populates="distribution",
        cascade="all, delete-orphan", order_by="DividendInstallment.installment_no",
    )


class DividendShareholder(Base):
    """Dağıtımdaki pay sahibi (ortak) — brüt/stopaj/net kâr payı."""
    __tablename__ = "dividend_shareholders"
    __table_args__ = (
        Index("ix_dividend_shareholders_dist", "distribution_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    distribution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dividend_distributions.id", ondelete="CASCADE"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    share_value: Mapped[float] = mapped_column(Numeric(15, 2), default=0)   # pay değeri
    share_ratio: Mapped[float] = mapped_column(Numeric(9, 6), default=0)    # pay oranı (share_value/sermaye)
    gross_dividend: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    stopaj_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    net_dividend: Mapped[float] = mapped_column(Numeric(15, 2), default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    distribution: Mapped["DividendDistribution"] = relationship(
        "DividendDistribution", back_populates="shareholders",
    )


class DividendInstallment(Base):
    """Taksit — nakit akım taşıyan birim (2 finance_event: net + stopaj)."""
    __tablename__ = "dividend_installments"
    __table_args__ = (
        Index("ix_dividend_installments_dist", "distribution_id"),
        Index("ix_dividend_installments_due", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    distribution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dividend_distributions.id", ondelete="CASCADE"),
    )
    installment_no: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date_type] = mapped_column(Date)  # net'in ortaklara ödeneceği tarih
    label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "30.06.2025"
    gross_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    stopaj_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    net_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    distribution: Mapped["DividendDistribution"] = relationship(
        "DividendDistribution", back_populates="installments",
    )


class DividendPayment(Base):
    """Pay sahibi × taksit ödeme satırı (72 = 12 ortak × 6 taksit)."""
    __tablename__ = "dividend_payments"
    __table_args__ = (
        Index("ix_dividend_payments_dist", "distribution_id"),
        Index("ix_dividend_payments_installment", "installment_id"),
        Index("ix_dividend_payments_shareholder", "shareholder_id"),
        Index("ix_dividend_payments_installment_paid", "installment_id", "is_paid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    distribution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dividend_distributions.id", ondelete="CASCADE"),
    )
    installment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dividend_installments.id", ondelete="CASCADE"),
    )
    shareholder_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dividend_shareholders.id", ondelete="CASCADE"),
    )
    gross_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    stopaj_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    net_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)

    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)          # net ortağa ödendi
    paid_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    stopaj_paid: Mapped[bool] = mapped_column(Boolean, default=False)      # stopaj vergi dairesine ödendi
    stopaj_paid_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)

    # Banka eşleştirme — net ödemenin yapıldığı banka hareketi. Doluysa net finance_event'i
    # is_matched=True olur (nakit akımda gizlenir; banka bacağı sayılır → çift sayım engellenir).
    bank_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_transactions.id", ondelete="SET NULL"), nullable=True,
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
