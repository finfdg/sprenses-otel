"""Oda tipi master modeli — doluluk hesaplamasında payda olarak kullanılır.

Oda tipi kodu (`code`) rezervasyon kayıtlarındaki `reservations.room_type`
değeriyle eşleşir (örn. 'STD KARA', 'J.SUITE'). Bu tablo fiziksel oda
envanterini tutar; `total_rooms` toplamı otelin kapasitesini verir.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RoomType(Base):
    __tablename__ = "room_types"
    __table_args__ = (
        CheckConstraint("total_rooms >= 0", name="ck_room_types_total_rooms_positive"),
        CheckConstraint("max_occupancy >= 1", name="ck_room_types_max_occupancy_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    total_rooms: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    max_occupancy: Mapped[int] = mapped_column(Integer, server_default="2", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
