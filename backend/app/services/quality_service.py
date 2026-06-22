"""Kalite şablon domain servis katmanı — bölüm/alan + atama kaydetme (HTTP'siz, dict-tabanlı).

D1-2 (2026-06-22): Şablon bölüm/alan/atama KAYDETME mantığı tek kaynakta. Router (templates.py)
ve onay executor (_handle_quality_templates) AYNI bu fonksiyonları çağırır → iki kopya birleşti.
Eskiden router `_save_sections` (Pydantic erişimi) + executor `_save_template_sections` (dict erişimi)
AYRIYDI ve DRIFT etmişti: executor `options`'ı çift-serileştiriyordu → select seçenekleri parse
edilemiyordu. Service dict alır; router `model_dump()` ile, executor payload ile çağırır.
"""
from sqlalchemy.orm import Session

from app.models.quality_template_assignee import QualityTemplateAssignee
from app.models.quality_template_field import QualityTemplateField
from app.models.quality_template_section import QualityTemplateSection


def save_sections(db: Session, template_id: int, sections_data: list) -> None:
    """Şablon bölümlerini + alanlarını kaydet. sections_data: dict listesi (router model_dump / executor payload)."""
    for i, sec in enumerate(sections_data):
        section = QualityTemplateSection(
            template_id=template_id,
            name=sec.get("name") or sec.get("title") or "",
            sort_order=sec.get("sort_order") or i,
        )
        db.add(section)
        db.flush()
        for j, fld in enumerate(sec.get("fields") or []):
            db.add(QualityTemplateField(
                section_id=section.id,
                label=fld.get("label", ""),
                field_type=fld.get("field_type", "text"),
                unit=fld.get("unit"),
                # options payload'da zaten JSON string (şema Optional[str]) — tekrar dumps ETME
                options=fld.get("options"),
                is_required=fld.get("is_required", False),
                is_resource=fld.get("is_resource", False),
                is_guest_count=fld.get("is_guest_count", False),
                is_meter=fld.get("is_meter", False),
                is_month_end_only=fld.get("is_month_end_only", False),
                sort_order=fld.get("sort_order") or j,
            ))


def save_assignees(db: Session, template_id: int, assignees_data: list) -> None:
    """Şablon dolduran/onaylayan atamalarını kaydet. assignees_data: dict listesi.

    assignment_type ZORUNLU (NOT NULL, default yok); user_id XOR role_id (CHECK) — payload ikisini de taşımalı.
    """
    for a in assignees_data:
        db.add(QualityTemplateAssignee(
            template_id=template_id,
            assignment_type=a.get("assignment_type"),
            user_id=a.get("user_id"),
            role_id=a.get("role_id"),
        ))
