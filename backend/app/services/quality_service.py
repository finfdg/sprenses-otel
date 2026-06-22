"""Kalite şablon + form domain servis katmanı (HTTP'siz, dict/typed-tabanlı).

D1-2 (2026-06-22): Şablon bölüm/alan/atama KAYDETME mantığı tek kaynakta. Router (templates.py)
ve onay executor (_handle_quality_templates) AYNI bu fonksiyonları çağırır → iki kopya birleşti.
Eskiden router `_save_sections` (Pydantic erişimi) + executor `_save_template_sections` (dict erişimi)
AYRIYDI ve DRIFT etmişti: executor `options`'ı çift-serileştiriyordu → select seçenekleri parse
edilemiyordu. Service dict alır; router `model_dump()` ile, executor payload ile çağırır.

D1-2 (2026-06-22) form CRUD: `create_form` / `delete_form` — kalite formu oluştur/sil tek kaynakta.
Router (forms/crud.py) ve onay executor (_handle_quality_forms) AYNI bu fonksiyonları çağırır.
Onay payload'ı JSON olduğundan `period_date` string (json default=str) gelebilir → `_coerce_date`
ile date'e çevrilir; router typed `date` verir, o da geçer. NOT: router `FormCreate` şemasında
`notes` YOK (yalnız template_id+period_date) → form oluşturma `notes`'u set ETMEZ (model default
NULL kalır). `notes` parametresi geriye dönük/executor uyumu için opsiyonel tutulur.

Service HTTP'siz: 404/400/409 doğrulaması, response, approval, audit, broadcast/WS ROUTER'da kalır.
Service yalnız DB mutasyonu yapar; commit ETMEZ (çağıran commit eder).
"""
from datetime import date
from typing import Optional, Union

from sqlalchemy.orm import Session

from app.models.quality_form import QualityForm
from app.models.quality_template_assignee import QualityTemplateAssignee
from app.models.quality_template_field import QualityTemplateField
from app.models.quality_template_section import QualityTemplateSection


def _coerce_date(value: Union[date, str, None]) -> Optional[date]:
    """Onay payload'ı JSON → date string gelebilir; router typed `date` verir.

    String ise ISO formatından (YYYY-MM-DD) date'e çevirir; date ise olduğu gibi döner.
    """
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


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


def create_form(
    db: Session,
    template_id: int,
    period_date: Union[date, str],
    notes: Optional[str] = None,
    status: str = "draft",
) -> QualityForm:
    """Kalite formu oluştur (taslak). period_date string ise date'e coerce edilir.

    Router `FormCreate` şemasında `notes` YOK → router notes geçmez (model default NULL).
    `notes` parametresi None değilse model'e set edilir (executor payload uyumu).
    Çağıran commit eder; bu fonksiyon flush ETMEZ (router db.refresh ile id alır).
    """
    form = QualityForm(
        template_id=template_id,
        period_date=_coerce_date(period_date),
        notes=notes,
        status=status,
    )
    db.add(form)
    return form


def delete_form(db: Session, form: QualityForm) -> None:
    """Verilen form kaydını sil. Varlık doğrulaması (404) + durum/yetki kontrolü ROUTER'da."""
    db.delete(form)
