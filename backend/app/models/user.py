"""Kullanıcı modeli — kimlik, rol ilişkisi ve oturum yönetimi."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.role import Role


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    active_session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    last_online_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    role_rel: Mapped["Role"] = relationship("Role", back_populates="users")

    @property
    def full_name(self) -> str:
        """Ad ve soyadı birleştir."""
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name
