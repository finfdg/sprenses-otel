from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.bank_account import BankAccount
    from app.models.bank_transaction import BankTransaction
    from app.models.user import User


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bank_accounts.id", ondelete="CASCADE"),
    )
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(10))  # pdf / xlsx
    period_start: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    total_transactions: Mapped[int] = mapped_column(Integer, server_default="0")
    new_transactions: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped_transactions: Mapped[int] = mapped_column(Integer, server_default="0")
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    account: Mapped["BankAccount"] = relationship("BankAccount", back_populates="statements")
    uploader: Mapped[Optional["User"]] = relationship("User", foreign_keys=[uploaded_by])
    transactions: Mapped[List["BankTransaction"]] = relationship(
        "BankTransaction", back_populates="statement",
    )
