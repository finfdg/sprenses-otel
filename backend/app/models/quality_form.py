"""Kalite form örneği modeli."""

from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.quality_form_value import QualityFormValue
    from app.models.quality_template import QualityTemplate
    from app.models.user import User


class QualityForm(Base):
    __tablename__ = "quality_forms"
    __table_args__ = (
        UniqueConstraint("template_id", "period_date", name="uq_template_period"),
        Index("ix_quality_forms_template_id", "template_id"),
        Index("ix_quality_forms_period_date", "period_date"),
        Index("ix_quality_forms_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quality_templates.id", ondelete="RESTRICT")
    )
    period_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    filled_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    template: Mapped["QualityTemplate"] = relationship(
        "QualityTemplate", back_populates="forms"
    )
    filler: Mapped[Optional["User"]] = relationship("User", foreign_keys=[filled_by])
    reviewer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[reviewed_by])
    values: Mapped[List["QualityFormValue"]] = relationship(
        "QualityFormValue", back_populates="form", cascade="all, delete-orphan"
    )
