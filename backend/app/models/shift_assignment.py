"""Vardiya çizelgesi (rota) — personelin hangi gün hangi vardiyada olduğu.

Tarih bazlı atama: `(personnel_id, work_date)` çifti benzersizdir — bir personel
bir günde tek vardiyada olur (split vardiya tek tanımdır, iki segmenti vardır).
Kayıt yoksa o gün **izinli/boş** demektir (ayrı "off" satırı tutulmaz).

Vardiya tanımı (`shift_definitions`) veya personel silinirse atamalar DB düzeyinde
CASCADE ile birlikte silinir.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ShiftAssignment(Base):
    """Bir personelin belirli bir gündeki vardiya ataması (rota hücresi)."""
    __tablename__ = "shift_assignments"
    __table_args__ = (
        # Bir personel bir günde tek vardiyada (composite index personnel_id'yi de karşılar)
        UniqueConstraint("personnel_id", "work_date", name="uq_shift_assignment_personnel_date"),
        Index("ix_shift_assignment_date", "work_date"),
        Index("ix_shift_assignment_shift", "shift_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    personnel_id: Mapped[int] = mapped_column(
        ForeignKey("personnel.id", ondelete="CASCADE")
    )
    shift_id: Mapped[int] = mapped_column(
        ForeignKey("shift_definitions.id", ondelete="CASCADE")
    )
    work_date: Mapped[date] = mapped_column(Date)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
