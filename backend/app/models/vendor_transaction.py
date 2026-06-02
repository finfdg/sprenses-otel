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
    from app.models.budget import BudgetCategory
    from app.models.department import Department
    from app.models.vendor import Vendor
    from app.models.vendor_upload import VendorUpload


class VendorTransaction(Base):
    __tablename__ = "vendor_transactions"
    __table_args__ = (
        UniqueConstraint("vendor_id", "tx_hash", name="uq_vendor_tx_hash"),
        Index("ix_vendor_tx_vendor", "vendor_id"),
        Index("ix_vendor_tx_date", "date"),
        Index("ix_vendor_tx_upload", "upload_id"),
        Index("ix_vendor_tx_payment_due", "payment_due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vendors.id", ondelete="CASCADE"),
    )
    upload_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vendor_uploads.id", ondelete="CASCADE"),
    )
    date: Mapped[date_type] = mapped_column(Date)
    evrak_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    transaction_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fis_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    borc: Mapped[float] = mapped_column(Numeric(15, 2), server_default="0")
    alacak: Mapped[float] = mapped_column(Numeric(15, 2), server_default="0")
    bakiye: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    tx_hash: Mapped[str] = mapped_column(String(64))
    payment_due_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    match_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Departman ataması ve onay
    department_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True,
    )
    budget_category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("budget_categories.id", ondelete="SET NULL"), nullable=True,
    )
    dept_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
    )  # None=atanmamış, pending=onay bekliyor, approved=onaylandı, rejected=reddedildi
    dept_assigned_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    dept_assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    dept_approved_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    dept_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    dept_rejection_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="transactions")
    upload: Mapped["VendorUpload"] = relationship("VendorUpload", back_populates="transactions")
    department: Mapped[Optional["Department"]] = relationship("Department", foreign_keys=[department_id])
    budget_category: Mapped[Optional["BudgetCategory"]] = relationship("BudgetCategory", foreign_keys=[budget_category_id])
