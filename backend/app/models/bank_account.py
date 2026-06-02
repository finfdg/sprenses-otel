from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.bank_statement import BankStatement
    from app.models.bank_transaction import BankTransaction
    from app.models.user import User


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_name: Mapped[str] = mapped_column(String(100))
    branch_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    account_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    iban: Mapped[str] = mapped_column(String(34), unique=True)
    currency: Mapped[str] = mapped_column(String(3), server_default="TRY")
    holder_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    blocked_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    statements: Mapped[List["BankStatement"]] = relationship(
        "BankStatement", back_populates="account", cascade="all, delete-orphan",
    )
    transactions: Mapped[List["BankTransaction"]] = relationship(
        "BankTransaction", back_populates="account", cascade="all, delete-orphan",
    )
