from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RoleModulePermission(Base):
    __tablename__ = "role_module_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "module_id", name="uq_role_module"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id", ondelete="CASCADE")
    )
    module_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("modules.id", ondelete="CASCADE")
    )
    can_view: Mapped[bool] = mapped_column(Boolean, default=False)
    can_use: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    role = relationship("Role", back_populates="permissions")
    module = relationship("Module", back_populates="permissions")
