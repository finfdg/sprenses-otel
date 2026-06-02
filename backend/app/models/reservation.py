"""Otel rezervasyon modelleri — XLS yükleme bordrosu + rezervasyon kayıtları."""
from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

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


class ReservationUpload(Base):
    """Otel rezervasyon XLS yükleme kaydı."""
    __tablename__ = "reservation_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    hotel_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    period_checkin_start: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    period_checkin_end: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    period_record_start: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    period_record_end: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    new_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    uploader: Mapped[Optional["User"]] = relationship("User")
    reservations: Mapped[List["Reservation"]] = relationship(
        "Reservation", back_populates="upload",
    )


class Reservation(Base):
    """Otel rezervasyon kaydı (XLS satırı)."""
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_rec_id", "rec_id", unique=True),
        Index("ix_reservations_checkin_date", "checkin_date"),
        Index("ix_reservations_record_date", "record_date"),
        Index("ix_reservations_agency", "agency"),
        Index("ix_reservations_nation", "nation"),
        Index("ix_reservations_room_type", "room_type"),
        Index("ix_reservations_checkin_agency", "checkin_date", "agency"),
        Index("ix_reservations_checkin_nation", "checkin_date", "nation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rec_id: Mapped[int] = mapped_column(Integer, nullable=False)
    upload_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("reservation_uploads.id", ondelete="SET NULL"), nullable=True,
    )
    agency: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    room_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    voucher: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    guests: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checkin_date: Mapped[date_type] = mapped_column(Date)
    checkout_date: Mapped[date_type] = mapped_column(Date)
    nights: Mapped[int] = mapped_column(Integer, server_default="0")
    record_date: Mapped[date_type] = mapped_column(Date)
    board: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    vip_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    rooms: Mapped[int] = mapped_column(Integer, server_default="1")
    adult: Mapped[int] = mapped_column(Integer, server_default="0")
    child_paid: Mapped[int] = mapped_column(Integer, server_default="0")
    child_free: Mapped[int] = mapped_column(Integer, server_default="0")
    baby: Mapped[int] = mapped_column(Integer, server_default="0")
    nation: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    eur_total: Mapped[float] = mapped_column(Numeric(12, 2), server_default="0")
    per_room: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    per_adult: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    rez_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    upload: Mapped[Optional["ReservationUpload"]] = relationship(
        "ReservationUpload", back_populates="reservations",
    )
