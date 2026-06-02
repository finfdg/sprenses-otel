"""Kalite şablon atama modeli (dolduran / onaylayan)."""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.quality_template import QualityTemplate
    from app.models.role import Role
    from app.models.user import User


class QualityTemplateAssignee(Base):
    __tablename__ = "quality_template_assignees"
    __table_args__ = (
        Index(
            "ix_quality_template_assignees_template_type",
            "template_id",
            "assignment_type",
        ),
        CheckConstraint(
            "(user_id IS NOT NULL AND role_id IS NULL) OR "
            "(user_id IS NULL AND role_id IS NOT NULL)",
            name="ck_assignee_user_or_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quality_templates.id", ondelete="CASCADE")
    )
    assignment_type: Mapped[str] = mapped_column(String(20))  # filler / approver
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    role_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=True
    )

    template: Mapped["QualityTemplate"] = relationship(
        "QualityTemplate", back_populates="assignees"
    )
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    role: Mapped[Optional["Role"]] = relationship("Role", foreign_keys=[role_id])
