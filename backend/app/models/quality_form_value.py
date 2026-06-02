"""Kalite form değer modeli."""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.quality_form import QualityForm
    from app.models.quality_template_field import QualityTemplateField


class QualityFormValue(Base):
    __tablename__ = "quality_form_values"
    __table_args__ = (
        UniqueConstraint("form_id", "field_id", name="uq_form_field"),
        Index("ix_quality_form_values_form_id", "form_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quality_forms.id", ondelete="CASCADE")
    )
    field_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quality_template_fields.id", ondelete="CASCADE")
    )
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrective_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correction_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    form: Mapped["QualityForm"] = relationship("QualityForm", back_populates="values")
    field: Mapped["QualityTemplateField"] = relationship("QualityTemplateField")
