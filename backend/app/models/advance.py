"""Alınan avanslar modeli."""
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.bank_transaction import BankTransaction
    from app.models.user import User


class Advance(Base):
    """Acente/operatörden alınan avans."""
    __tablename__ = "advances"
    __table_args__ = (
        Index("ix_advances_date", "advance_date"),
        Index("ix_advances_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_name: Mapped[str] = mapped_column(String(200))  # Acente/Operatör adı
    amount: Mapped[float] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(5), default="EUR")  # EUR, USD, TRY
    advance_date: Mapped[date_type] = mapped_column(Date)  # Avans tarihi (beklenen giriş)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, received, cancelled
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Banka eşleştirme
    bank_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_transactions.id", ondelete="SET NULL"), nullable=True,
    )
    received_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)  # Gerçek alındı tarihi
    received_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # Gerçek alınan tutar

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    bank_transaction: Mapped[Optional["BankTransaction"]] = relationship("BankTransaction")
    creator: Mapped[Optional["User"]] = relationship("User")
