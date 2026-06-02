"""Kalite şablon modeli."""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.quality_form import QualityForm
    from app.models.quality_template_assignee import QualityTemplateAssignee
    from app.models.quality_template_section import QualityTemplateSection
    from app.models.user import User


class QualityTemplate(Base):
    __tablename__ = "quality_templates"
    __table_args__ = (
        Index("ix_quality_templates_is_active", "is_active"),
        Index("ix_quality_templates_frequency", "frequency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    frequency: Mapped[str] = mapped_column(String(20), default="daily")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    footer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    increase_threshold: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=10.0
    )
    decrease_threshold: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=10.0
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    sections: Mapped[List["QualityTemplateSection"]] = relationship(
        "QualityTemplateSection",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="QualityTemplateSection.sort_order",
    )
    assignees: Mapped[List["QualityTemplateAssignee"]] = relationship(
        "QualityTemplateAssignee",
        back_populates="template",
        cascade="all, delete-orphan",
    )
    forms: Mapped[List["QualityForm"]] = relationship(
        "QualityForm", back_populates="template"
    )
