"""Verilen çekler modeli."""
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.bank_transaction import BankTransaction
    from app.models.user import User


class CheckUpload(Base):
    """Çek dosyası yükleme kaydı."""
    __tablename__ = "check_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    total_checks: Mapped[int] = mapped_column(Integer, server_default="0")
    new_checks: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped_checks: Mapped[int] = mapped_column(Integer, server_default="0")
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    uploader: Mapped[Optional["User"]] = relationship("User")
    checks: Mapped[list] = relationship("Check", back_populates="upload", cascade="all, delete-orphan")


class Check(Base):
    """Verilen çek kaydı."""
    __tablename__ = "checks"
    __table_args__ = (
        UniqueConstraint("check_no", "vendor_code", "due_date", name="uq_check_no_vendor_date"),
        Index("ix_checks_due_date", "due_date"),
        Index("ix_checks_vendor_code", "vendor_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("check_uploads.id", ondelete="CASCADE"),
    )
    check_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # Yerel
    sequence_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    check_no: Mapped[str] = mapped_column(String(50))
    vendor_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    vendor_name: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    due_date: Mapped[date_type] = mapped_column(Date)
    amount_tl: Mapped[float] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(5), server_default="TL")
    amount_currency: Mapped[float] = mapped_column(Numeric(15, 2))
    transaction_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Verilen Çek
    status: Mapped[str] = mapped_column(String(20), server_default="pending")  # pending, paid, cancelled
    bank_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_transactions.id", ondelete="SET NULL"), nullable=True,
    )
    match_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    matched_vendor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    upload: Mapped["CheckUpload"] = relationship("CheckUpload", back_populates="checks")
    bank_tx: Mapped[Optional["BankTransaction"]] = relationship("BankTransaction")
