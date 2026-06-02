"""Kalite şablon bölüm modeli."""

from typing import TYPE_CHECKING, List

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.quality_template import QualityTemplate
    from app.models.quality_template_field import QualityTemplateField


class QualityTemplateSection(Base):
    __tablename__ = "quality_template_sections"
    __table_args__ = (
        Index("ix_quality_template_sections_template_id", "template_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quality_templates.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    template: Mapped["QualityTemplate"] = relationship(
        "QualityTemplate", back_populates="sections"
    )
    fields: Mapped[List["QualityTemplateField"]] = relationship(
        "QualityTemplateField",
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="QualityTemplateField.sort_order",
    )
