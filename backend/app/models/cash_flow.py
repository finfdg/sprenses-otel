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
    from app.models.user import User


class CashFlow(Base):
    __tablename__ = "cash_flows"
    __table_args__ = (
        Index("ix_cash_flows_type", "type"),
        Index("ix_cash_flows_date", "date"),
        Index("ix_cash_flows_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))  # "income" veya "expense"
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date: Mapped[date_type] = mapped_column(Date, server_default=func.current_date())
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
