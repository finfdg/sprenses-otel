"""Döviz kuru modeli — TCMB verisi."""

from datetime import date as date_type
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("date", "currency_code", name="uq_exchange_rate_date_currency"),
        Index("ix_exchange_rates_date", "date"),
        Index("ix_exchange_rates_currency_code", "currency_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    currency_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    unit: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    forex_buying: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    forex_selling: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    banknote_buying: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    banknote_selling: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(20), server_default="tcmb", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
