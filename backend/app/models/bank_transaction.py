"""Banka işlemi modeli — ekstre satırları, etiketleme ve eşleştirme."""

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.bank_account import BankAccount
    from app.models.bank_statement import BankStatement
    from app.models.transaction_category import TransactionCategory
    from app.models.vendor import Vendor


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bank_accounts.id", ondelete="CASCADE"),
    )
    statement_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_statements.id", ondelete="SET NULL"), nullable=True,
    )
    date: Mapped[date_type] = mapped_column(Date)
    receipt_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Numeric(15, 2))
    balance: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    type: Mapped[str] = mapped_column(String(10))  # income / expense
    # Kaynak: 'statement' (ekstreden gelir) | 'manual' (elle, ekstre-dışı düzeltme).
    # Manuel satırlar, ilgili ekstre yüklenince o ekstrenin tarih aralığında OTOMATİK
    # silinir (finance_event'i de invalidate edilir) → ekstre asıl kaynak, çift kayıt olmaz.
    source: Mapped[str] = mapped_column(String(20), default="statement", server_default="statement")
    tx_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    # Ödeme yöntemi ve eşleştirme
    payment_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    match_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Etiketleme
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("transaction_categories.id", ondelete="SET NULL"), nullable=True,
    )
    tag_note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    tag_source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Cari eşleştirme
    vendor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True,
    )

    account: Mapped["BankAccount"] = relationship("BankAccount", back_populates="transactions")
    statement: Mapped[Optional["BankStatement"]] = relationship(
        "BankStatement", back_populates="transactions",
    )
    category: Mapped[Optional["TransactionCategory"]] = relationship(
        "TransactionCategory", back_populates="transactions",
    )
    vendor: Mapped[Optional["Vendor"]] = relationship("Vendor")

    __table_args__ = (
        UniqueConstraint("account_id", "tx_hash", name="uq_bank_tx_account_hash"),
        Index("ix_bank_tx_date", "date"),
        Index("ix_bank_tx_account", "account_id"),
        Index("ix_bank_tx_type", "type"),
        Index("ix_bank_tx_category", "category_id"),
        Index("ix_bank_tx_match_number", "match_number"),
    )
