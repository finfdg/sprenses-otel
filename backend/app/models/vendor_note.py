"""Cari notu (vendor note) modeli — cari hakkında serbest görüşme/takip notları.

Tasarım (2026-07-04, "Sprenses Tasarımlar" · Cariler yeniden tasarımı): cari detayında
"Notlar" sekmesi — ekle / düzenle / sil / "yapıldı" işaretle. Finansal etkisi YOKTUR
(finance_events'e yazılmaz); yalnızca ilişki/görüşme metadatasıdır → onaydan muaftır
(payment_deferral notu gibi). `author_name` snapshot'tır — not sahibi kullanıcı silinse
bile görüntülemede korunur (`author_id` SET NULL).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.vendor import Vendor


class VendorNote(Base):
    __tablename__ = "vendor_notes"
    __table_args__ = (
        Index("ix_vendor_notes_vendor_id", "vendor_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"),
    )
    text: Mapped[str] = mapped_column(Text)
    author_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    author_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="notes")
