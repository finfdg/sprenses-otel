"""Vardiya tanımları (shift_definitions) — otel 7/24 vardiya sistemi.

Normal vardiya: start_time → end_time. Gece vardiyası gece yarısını geçebilir
(end_time <= start_time → ertesi gün). Split vardiya için ikinci segment
(start_time2/end_time2) — ör. 07:00-11:00 + 18:00-22:00.
"""
from datetime import datetime, time
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DEFAULT_COLOR = "#0d9488"


class ShiftDefinition(Base):
    __tablename__ = "shift_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(7), default=DEFAULT_COLOR, server_default=DEFAULT_COLOR)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    # Split vardiya ikinci segment (opsiyonel)
    start_time2: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    end_time2: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
