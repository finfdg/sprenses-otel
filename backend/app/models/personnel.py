"""Personel devam takip (PDKS) modelleri — personel kaydı + giriş/çıkış logları.

Personel, uygulama kullanıcılarından (users) bağımsızdır: otel çalışanları
(temizlik, mutfak, resepsiyon...) burada tutulur. Her personelin kişisel bir
`access_token`'ı vardır — telefonda bir kez açılan kurulum linkiyle kimlik çerezi
oturur, sonraki basışlarda kim olduğu buradan bilinir.
"""
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User

# Giriş/çıkış tipleri
TYPE_IN = "in"
TYPE_OUT = "out"

# Kayıt kaynağı
SOURCE_PHONE = "phone_qr"   # personel telefonuyla kiosk QR'ı okuttu
SOURCE_MANUAL = "manual"    # yönetici elle girdi


class Personnel(Base):
    """Otel çalışanı (devam takip için) — app kullanıcısından bağımsız kayıt."""
    __tablename__ = "personnel"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    employee_code: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # sicil no
    department: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # Kişisel kimlik/kurulum token'ı — telefon çerezi bununla set edilir
    access_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    logs: Mapped[List["AttendanceLog"]] = relationship(
        "AttendanceLog", back_populates="personnel", cascade="all, delete-orphan"
    )


class AttendanceLog(Base):
    """Tek bir giriş veya çıkış basışı."""
    __tablename__ = "attendance_logs"
    __table_args__ = (
        Index("ix_attendance_personnel_time", "personnel_id", "punched_at"),
        Index("ix_attendance_punched_at", "punched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    personnel_id: Mapped[int] = mapped_column(
        ForeignKey("personnel.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(5))  # in / out
    punched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(20), default=SOURCE_PHONE, server_default=SOURCE_PHONE)
    # Manuel kayıtsa giren yönetici (app user)
    recorded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Elle düzenlendiyse zaman damgası (panoda farklı renk + "düzenlendi" rozeti)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft delete — silinen kayıt DB'de kalır, Geçmiş'te soluk gösterilir; aktif hesaplara girmez
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    personnel: Mapped["Personnel"] = relationship("Personnel", back_populates="logs")
