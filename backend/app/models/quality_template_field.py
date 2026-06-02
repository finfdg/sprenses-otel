"""Kalite şablon alan modeli."""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.quality_template_section import QualityTemplateSection


class QualityTemplateField(Base):
    __tablename__ = "quality_template_fields"
    __table_args__ = (
        Index("ix_quality_template_fields_section_id", "section_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quality_template_sections.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(300))
    field_type: Mapped[str] = mapped_column(String(20))  # text, number, yes_no, select
    unit: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    is_resource: Mapped[bool] = mapped_column(Boolean, default=False)
    is_guest_count: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    is_meter: Mapped[bool] = mapped_column(Boolean, default=False)
    is_month_end_only: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    section: Mapped["QualityTemplateSection"] = relationship(
        "QualityTemplateSection", back_populates="fields"
    )
