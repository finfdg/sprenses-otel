from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vendor_transaction import VendorTransaction


class VendorUpload(Base):
    __tablename__ = "vendor_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(500))
    total_vendors: Mapped[int] = mapped_column(Integer, server_default="0")
    total_transactions: Mapped[int] = mapped_column(Integer, server_default="0")
    new_transactions: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped_transactions: Mapped[int] = mapped_column(Integer, server_default="0")
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    uploader: Mapped[Optional["User"]] = relationship("User", foreign_keys=[uploaded_by])
    transactions: Mapped[List["VendorTransaction"]] = relationship(
        "VendorTransaction", back_populates="upload", cascade="all, delete-orphan",
    )
