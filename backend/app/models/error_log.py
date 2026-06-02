from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ErrorLog(Base):
    __tablename__ = "error_logs"
    __table_args__ = (
        Index("ix_error_logs_created_at", "created_at"),
        Index("ix_error_logs_level", "level"),
        Index("ix_error_logs_source", "source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20))  # ERROR, CRITICAL, WARNING
    source: Mapped[str] = mapped_column(String(100))  # module/file name
    message: Mapped[str] = mapped_column(Text)
    traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # GET, POST, etc.
    path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # URL path
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
