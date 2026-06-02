"""Kalite formları paketinde paylaşılan yardımcı fonksiyonlar."""

import asyncio
import calendar
import logging
from datetime import date, timedelta
from typing import List, Optional

import pytz
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from app.models.quality_form import QualityForm
from app.models.quality_template import QualityTemplate
from app.models.quality_template_assignee import QualityTemplateAssignee
from app.models.quality_template_section import QualityTemplateSection
from app.models.user import User
from app.schemas.quality import (
    FormDetailResponse,
    FormValueResponse,
    TemplateFieldResponse,
    TemplateSectionResponse,
)
from app.websocket.manager import manager as ws_manager

logger = logging.getLogger(__name__)

tz_istanbul = pytz.timezone("Europe/Istanbul")


async def _notify_quality_event_async(
    event_type: str,
    form_id: int,
    template_name: str,
    period_date,
    actor_name: str,
    exclude_user_id: Optional[int] = None,
) -> None:
    """Kalite form olayını tüm bağlı kullanıcılara bildir (aktörü hariç tut)."""
    event = {
        "type": "quality_form_update",
        "event": event_type,
        "form_id": form_id,
        "template_name": template_name,
        "period_date": str(period_date),
        "actor_name": actor_name,
    }
    online_ids = ws_manager.get_online_user_ids()
    target_ids = [uid for uid in online_ids if uid != exclude_user_id]
    if target_ids:
        await ws_manager.send_to_users(target_ids, event)


def _notify_quality_event(
    event_type: str,
    form_id: int,
    template_name: str,
    period_date,
    actor_name: str,
    exclude_user_id: Optional[int] = None,
) -> None:
    """Sync wrapper — BackgroundTasks ile kullanılır."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_notify_quality_event_async(
            event_type, form_id, template_name, period_date,
            actor_name, exclude_user_id,
        ))
    except RuntimeError:
        logger.debug("WS bildirim gönderilemedi: event loop bulunamadı")


def _user_display(u) -> str:
    """Kullanıcı adını döndür."""
    if not u:
        return None
    return f"{u.first_name} {u.last_name}" if u.last_name else u.first_name


def _form_values_to_list(form_obj: QualityForm) -> List[dict]:
    """Form değerlerini FormValueResponse listesine çevir."""
    return [
        FormValueResponse(
            id=v.id,
            field_id=v.field_id,
            value=v.value,
            corrective_action=v.corrective_action,
            correction_note=v.correction_note,
        ).model_dump()
        for v in form_obj.values
    ]


def _find_comparison_forms(
    db: Session, template_id: int, period_date: date,
):
    # type: (...) -> tuple
    """
    Farklı dönemler için karşılaştırma formlarını bul.
    Döndürür: (comparisons_dict, period_dates_dict)
    comparisons_dict: { "previous": [...], "previous_day": [...], ... }
    period_dates_dict: { "previous": date, "previous_day": date, ... }
    """
    result = {
        "previous": None,
        "previous_day": None,
        "previous_week": None,
        "previous_month": None,
    }
    period_dates = {
        "previous": None,
        "previous_day": None,
        "previous_week": None,
        "previous_month": None,
    }

    # 1. Önceki form (tarih farkı ne olursa olsun — en yakın geçmiş)
    prev_form = (
        db.query(QualityForm)
        .options(joinedload(QualityForm.values))
        .filter(
            QualityForm.template_id == template_id,
            QualityForm.period_date < period_date,
        )
        .order_by(desc(QualityForm.period_date))
        .first()
    )
    if prev_form:
        result["previous"] = _form_values_to_list(prev_form)
        period_dates["previous"] = prev_form.period_date

    # 2. Önceki gün (±1 gün tolerans)
    target_day = period_date - timedelta(days=1)
    day_form = (
        db.query(QualityForm)
        .options(joinedload(QualityForm.values))
        .filter(
            QualityForm.template_id == template_id,
            QualityForm.period_date >= target_day - timedelta(days=1),
            QualityForm.period_date <= target_day + timedelta(days=1),
            QualityForm.period_date < period_date,
        )
        .order_by(func.abs(QualityForm.period_date - target_day))
        .first()
    )
    if day_form:
        result["previous_day"] = _form_values_to_list(day_form)
        period_dates["previous_day"] = day_form.period_date

    # 3. Önceki hafta (±1 gün tolerans)
    target_week = period_date - timedelta(days=7)
    week_form = (
        db.query(QualityForm)
        .options(joinedload(QualityForm.values))
        .filter(
            QualityForm.template_id == template_id,
            QualityForm.period_date >= target_week - timedelta(days=1),
            QualityForm.period_date <= target_week + timedelta(days=1),
        )
        .order_by(func.abs(QualityForm.period_date - target_week))
        .first()
    )
    if week_form:
        result["previous_week"] = _form_values_to_list(week_form)
        period_dates["previous_week"] = week_form.period_date

    # 4. Önceki ay (±3 gün tolerans)
    target_month = period_date - timedelta(days=30)
    month_form = (
        db.query(QualityForm)
        .options(joinedload(QualityForm.values))
        .filter(
            QualityForm.template_id == template_id,
            QualityForm.period_date >= target_month - timedelta(days=3),
            QualityForm.period_date <= target_month + timedelta(days=3),
        )
        .order_by(func.abs(QualityForm.period_date - target_month))
        .first()
    )
    if month_form:
        result["previous_month"] = _form_values_to_list(month_form)
        period_dates["previous_month"] = month_form.period_date

    return result, period_dates


def _safe_float(val):
    """Değeri güvenli float'a çevir."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _compute_meter_consumptions(
    db, template_id, form, comparisons, period_dates, meter_field_ids,
):
    # type: (Session, int, QualityForm, dict, dict, set) -> dict
    """
    Sayaç alanları için tüketim hesapla.
    Tüketim = mevcut_okuma - önceki_gün_okuması.
    Döndürür: { "current": {fid: val}, "previous_day": {fid: val}, ... }
    """
    result = {}

    # — Mevcut form değerleri —
    current_vals = {v.field_id: v.value for v in form.values}

    # — Önceki gün değerleri (comparisons'dan, zaten yüklü) —
    prev_day_vals = {}
    if comparisons.get("previous_day"):
        for pv in comparisons["previous_day"]:
            prev_day_vals[pv["field_id"]] = pv.get("value")

    # Mevcut form tüketimi
    current_consumption = {}
    for fid in meter_field_ids:
        cur = _safe_float(current_vals.get(fid))
        prev = _safe_float(prev_day_vals.get(fid))
        if cur is not None and prev is not None:
            current_consumption[str(fid)] = cur - prev
        else:
            current_consumption[str(fid)] = None
    result["current"] = current_consumption

    # — Her karşılaştırma dönemi için tüketim hesapla —
    for comp_key in ("previous_day", "previous_week", "previous_month"):
        comp_period_date = period_dates.get(comp_key)
        if not comp_period_date or not comparisons.get(comp_key):
            result[comp_key] = None
            continue

        # Bu karşılaştırma formunun önceki gün formunu bul
        target = comp_period_date - timedelta(days=1)
        prev_of_comp = (
            db.query(QualityForm)
            .options(joinedload(QualityForm.values))
            .filter(
                QualityForm.template_id == template_id,
                QualityForm.period_date >= target - timedelta(days=1),
                QualityForm.period_date <= target + timedelta(days=1),
                QualityForm.period_date < comp_period_date,
            )
            .order_by(func.abs(QualityForm.period_date - target))
            .first()
        )

        if not prev_of_comp:
            result[comp_key] = None
            continue

        # Karşılaştırma formu değerleri
        comp_vals = {}
        for pv in comparisons[comp_key]:
            comp_vals[pv["field_id"]] = pv.get("value")

        # Önceki gün formu değerleri
        prev_of_comp_vals = {v.field_id: v.value for v in prev_of_comp.values}

        comp_consumption = {}
        for fid in meter_field_ids:
            cur = _safe_float(comp_vals.get(fid))
            prev = _safe_float(prev_of_comp_vals.get(fid))
            if cur is not None and prev is not None:
                comp_consumption[str(fid)] = cur - prev
            else:
                comp_consumption[str(fid)] = None
        result[comp_key] = comp_consumption

    return result


def _build_form_detail(
    form: QualityForm, db: Session, include_comparisons: bool = True,
) -> dict:
    """Form detay yanıtı oluştur."""
    # Şablon yapısını yükle
    template = (
        db.query(QualityTemplate)
        .options(
            joinedload(QualityTemplate.sections)
            .joinedload(QualityTemplateSection.fields),
        )
        .filter(QualityTemplate.id == form.template_id)
        .first()
    )

    sections = []
    meter_field_ids = set()
    if template:
        for s in template.sections:
            fields = []
            for f in s.fields:
                fields.append(TemplateFieldResponse(
                    id=f.id,
                    label=f.label,
                    field_type=f.field_type,
                    unit=f.unit,
                    is_required=f.is_required,
                    is_resource=f.is_resource,
                    is_guest_count=f.is_guest_count,
                    is_meter=f.is_meter,
                    is_month_end_only=f.is_month_end_only,
                    options=f.options,
                    sort_order=f.sort_order,
                ))
                if f.is_meter:
                    meter_field_ids.add(f.id)
            sections.append(TemplateSectionResponse(
                id=s.id,
                name=s.name,
                sort_order=s.sort_order,
                fields=fields,
            ))

    # Form değerlerini yükle
    values = [
        FormValueResponse(
            id=v.id,
            field_id=v.field_id,
            value=v.value,
            corrective_action=v.corrective_action,
            correction_note=v.correction_note,
        )
        for v in form.values
    ]

    # Karşılaştırma formlarını yükle
    comparisons = None
    previous_values = None
    period_dates = None
    if include_comparisons:
        comparisons, period_dates = _find_comparison_forms(
            db, form.template_id, form.period_date,
        )
        # Geriye uyumluluk: previous_values hâlâ gönderiliyor
        previous_values_raw = comparisons.get("previous")
        if previous_values_raw:
            previous_values = [
                FormValueResponse(**pv)
                for pv in previous_values_raw
            ]

    # Sayaç tüketim hesaplaması
    meter_consumptions = None
    if meter_field_ids and include_comparisons and comparisons is not None:
        meter_consumptions = _compute_meter_consumptions(
            db, form.template_id, form,
            comparisons, period_dates, meter_field_ids,
        )

    # Eşik değerleri
    inc_threshold = 10.0
    dec_threshold = 10.0
    if template:
        inc_threshold = template.increase_threshold if template.increase_threshold is not None else 10.0
        dec_threshold = template.decrease_threshold if template.decrease_threshold is not None else 10.0

    # Ay sonu kontrolü
    is_month_end = False
    if form.period_date:
        last_day = calendar.monthrange(form.period_date.year, form.period_date.month)[1]
        is_month_end = form.period_date.day == last_day

    return FormDetailResponse(
        id=form.id,
        template_id=form.template_id,
        template_name=template.name if template else "—",
        period_date=form.period_date,
        status=form.status,
        filled_by=form.filled_by,
        filled_by_name=_user_display(form.filler),
        submitted_at=form.submitted_at,
        reviewed_by=form.reviewed_by,
        reviewed_by_name=_user_display(form.reviewer),
        reviewed_at=form.reviewed_at,
        review_comment=form.review_comment,
        notes=form.notes,
        sections=sections,
        values=values,
        previous_values=previous_values,
        comparisons=comparisons,
        meter_consumptions=meter_consumptions,
        increase_threshold=inc_threshold,
        decrease_threshold=dec_threshold,
        is_month_end=is_month_end,
        created_at=form.created_at,
    ).model_dump()


def _check_filler(db: Session, template_id: int, user: User) -> bool:
    """Kullanıcının bu şablonu doldurabileceğini kontrol et."""
    assignee = (
        db.query(QualityTemplateAssignee)
        .filter(
            QualityTemplateAssignee.template_id == template_id,
            QualityTemplateAssignee.assignment_type == "filler",
        )
        .all()
    )
    # Atama yoksa herkes doldurabilir
    if not assignee:
        return True
    for a in assignee:
        if a.user_id and a.user_id == user.id:
            return True
        if a.role_id and a.role_id == user.role_id:
            return True
    return False


def _check_approver(db: Session, template_id: int, user: User) -> bool:
    """Kullanıcının bu şablonu onaylayabileceğini kontrol et."""
    assignee = (
        db.query(QualityTemplateAssignee)
        .filter(
            QualityTemplateAssignee.template_id == template_id,
            QualityTemplateAssignee.assignment_type == "approver",
        )
        .all()
    )
    # Atama yoksa herkes onaylayabilir
    if not assignee:
        return True
    for a in assignee:
        if a.user_id and a.user_id == user.id:
            return True
        if a.role_id and a.role_id == user.role_id:
            return True
    return False
