"""Kredi ürünleri ve ödeme planı modelleri."""

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
    from app.models.bank_transaction import BankTransaction
    from app.models.user import User


# Geçerli kredi ürün tipleri
CREDIT_PRODUCT_TYPES = {
    "kredi_karti",
    "kmh",
    "bch",
    "spot_kredi",
    "taksitli_kredi",
    "leasing",
}

# Türkçe etiketler
CREDIT_TYPE_LABELS = {
    "kredi_karti": "Kredi Kartı",
    "kmh": "KMH",
    "bch": "BCH",
    "spot_kredi": "Spot Kredi",
    "taksitli_kredi": "Taksitli Kredi",
    "leasing": "Leasing",
}


class CreditProduct(Base):
    __tablename__ = "credit_products"
    __table_args__ = (
        Index("ix_credit_products_type", "type"),
        Index("ix_credit_products_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    bank_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(5), default="TRY")
    total_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    remaining_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    interest_rate: Mapped[Optional[float]] = mapped_column(Numeric(6, 4), nullable=True)
    bsmv_rate: Mapped[Optional[float]] = mapped_column(Numeric(6, 4), nullable=True)  # BSMV oranı (%)
    commission_rate: Mapped[Optional[float]] = mapped_column(Numeric(6, 4), nullable=True)  # Komisyon oranı (%)
    # KMH için zorunlu — bağlı banka hesabı; bu hesabın bakiyesi negatife düştüğünde KMH kullanımı sayılır
    linked_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True,
    )
    start_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    closed_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)  # status='closed' olunca dolu

    # Tip-spesifik alanlar (JSON)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
    payments: Mapped[List["CreditPayment"]] = relationship(
        "CreditPayment", back_populates="credit_product",
        cascade="all, delete-orphan", order_by="CreditPayment.due_date",
    )


class CreditPayment(Base):
    __tablename__ = "credit_payments"
    __table_args__ = (
        Index("ix_credit_payments_due_date", "due_date"),
        Index("ix_credit_payments_product", "credit_product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("credit_products.id", ondelete="CASCADE"),
    )
    installment_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date_type] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Numeric(15, 2))
    principal: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    interest: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    bsmv: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    commission: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)

    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)

    # Banka eşleştirme
    bank_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_transactions.id", ondelete="SET NULL"), nullable=True,
    )
    match_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    credit_product: Mapped["CreditProduct"] = relationship(
        "CreditProduct", back_populates="payments",
    )
    bank_tx: Mapped[Optional["BankTransaction"]] = relationship("BankTransaction")
