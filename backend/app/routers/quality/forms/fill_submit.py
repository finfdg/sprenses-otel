"""Kalite formu doldurma, gönderme, onaylama/reddetme ve yeniden açma endpoint'leri."""

import calendar
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.quality_form import QualityForm
from app.models.quality_form_value import QualityFormValue
from app.models.quality_template import QualityTemplate
from app.models.quality_template_section import QualityTemplateSection
from app.models.user import User
from app.schemas.quality import FormFill, FormReview
from app.utils.audit import log_action

from ._helpers import (
    _build_form_detail,
    _check_approver,
    _check_filler,
    _notify_quality_event,
    _user_display,
    tz_istanbul,
)

router = APIRouter()


def _load_form_detail(form_id: int, db: Session) -> dict:
    """form_id'den ortak form detayı yanıtı oluştur (eager loaded)."""
    form = (
        db.query(QualityForm)
        .options(
            joinedload(QualityForm.filler),
            joinedload(QualityForm.reviewer),
            joinedload(QualityForm.values),
        )
        .filter(QualityForm.id == form_id)
        .first()
    )
    if not form:
        raise HTTPException(status_code=404, detail="Form bulunamadı")
    return _build_form_detail(form, db)


# ─── Form Doldur (Kaydet) ─────────────────────────────────────────────


@router.patch("/forms/{form_id}/fill")
def fill_form(
    form_id: int,
    data: FormFill,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "use")),
):
    """Form değerlerini kaydet (taslak)."""
    form = db.query(QualityForm).filter(QualityForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form bulunamadı")

    if form.status not in ("draft", "rejected"):
        raise HTTPException(
            status_code=400,
            detail="Sadece taslak veya reddedilmiş formlar düzenlenebilir",
        )

    # Dolduran yetkisi kontrol et
    if not _check_filler(db, form.template_id, current_user):
        raise HTTPException(
            status_code=403,
            detail="Bu formu doldurma yetkiniz yok",
        )

    # Değerleri upsert et
    for val_data in data.values:
        existing = (
            db.query(QualityFormValue)
            .filter(
                QualityFormValue.form_id == form_id,
                QualityFormValue.field_id == val_data.field_id,
            )
            .first()
        )
        if existing:
            existing.value = val_data.value
            existing.corrective_action = val_data.corrective_action
            existing.correction_note = val_data.correction_note
        else:
            fv = QualityFormValue(
                form_id=form_id,
                field_id=val_data.field_id,
                value=val_data.value,
                corrective_action=val_data.corrective_action,
                correction_note=val_data.correction_note,
            )
            db.add(fv)

    # Açıklama alanını güncelle
    if data.notes is not None:
        form.notes = data.notes.strip() if data.notes else None

    form.filled_by = current_user.id

    log_action(
        db, current_user.id, "update", "quality_form",
        entity_id=form_id,
        details="Form değerleri kaydedildi",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return _load_form_detail(form_id, db)


# ─── Form Gönder ──────────────────────────────────────────────────────


@router.post("/forms/{form_id}/submit")
def submit_form(
    form_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "use")),
):
    """Formu gönder (draft/rejected → submitted)."""
    form = db.query(QualityForm).filter(QualityForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form bulunamadı")

    if form.status not in ("draft", "rejected"):
        raise HTTPException(
            status_code=400,
            detail="Sadece taslak veya reddedilmiş formlar gönderilebilir",
        )

    if not _check_filler(db, form.template_id, current_user):
        raise HTTPException(status_code=403, detail="Bu formu gönderme yetkiniz yok")

    # Zorunlu alanları kontrol et
    template = (
        db.query(QualityTemplate)
        .options(
            joinedload(QualityTemplate.sections)
            .joinedload(QualityTemplateSection.fields),
        )
        .filter(QualityTemplate.id == form.template_id)
        .first()
    )

    # Ay sonu kontrolü — ay sonu olmayan formda is_month_end_only alanları atlanır
    is_month_end = False
    if form.period_date:
        last_day = calendar.monthrange(form.period_date.year, form.period_date.month)[1]
        is_month_end = form.period_date.day == last_day

    required_field_ids = set()
    if template:
        for sec in template.sections:
            for f in sec.fields:
                if f.is_required:
                    # Ay sonu alanı ve form ay sonu değilse zorunlu değil
                    if f.is_month_end_only and not is_month_end:
                        continue
                    required_field_ids.add(f.id)

    if required_field_ids:
        filled_values = (
            db.query(QualityFormValue)
            .filter(
                QualityFormValue.form_id == form_id,
                QualityFormValue.field_id.in_(required_field_ids),
            )
            .all()
        )
        filled_ids = {v.field_id for v in filled_values if v.value and v.value.strip()}
        missing = required_field_ids - filled_ids
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"{len(missing)} zorunlu alan doldurulmamış",
            )

    form.status = "submitted"
    form.filled_by = current_user.id
    form.submitted_at = datetime.now(tz_istanbul)

    log_action(
        db, current_user.id, "update", "quality_form",
        entity_id=form_id,
        details="Form gönderildi",
        ip_address=get_client_ip(request),
    )
    db.commit()

    # WS bildirimi
    _notify_quality_event(
        "submitted", form_id,
        template.name if template else "—",
        form.period_date,
        _user_display(current_user),
        exclude_user_id=current_user.id,
    )

    return _load_form_detail(form_id, db)


# ─── Form Onayla/Reddet ───────────────────────────────────────────────


@router.post("/forms/{form_id}/review")
def review_form(
    form_id: int,
    data: FormReview,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "use")),
):
    """Formu onayla veya reddet."""
    form = db.query(QualityForm).filter(QualityForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form bulunamadı")

    if form.status != "submitted":
        raise HTTPException(
            status_code=400,
            detail="Sadece gönderilmiş formlar onaylanabilir veya reddedilebilir",
        )

    if data.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Geçersiz işlem: approve veya reject")

    if not _check_approver(db, form.template_id, current_user):
        raise HTTPException(status_code=403, detail="Bu formu onaylama/reddetme yetkiniz yok")

    now = datetime.now(tz_istanbul)

    if data.action == "approve":
        form.status = "approved"
    else:
        form.status = "rejected"

    form.reviewed_by = current_user.id
    form.reviewed_at = now
    form.review_comment = data.comment.strip() if data.comment else None

    action_text = "onaylandı" if data.action == "approve" else "reddedildi"
    log_action(
        db, current_user.id, "update", "quality_form",
        entity_id=form_id,
        details=f"Form {action_text}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    # WS bildirimi
    template = db.query(QualityTemplate).filter(
        QualityTemplate.id == form.template_id
    ).first()
    ws_event = "approved" if data.action == "approve" else "rejected"
    _notify_quality_event(
        ws_event, form_id,
        template.name if template else "—",
        form.period_date,
        _user_display(current_user),
        exclude_user_id=current_user.id,
    )

    return _load_form_detail(form_id, db)


# ─── Form Yeniden Aç ──────────────────────────────────────────────────


@router.post("/forms/{form_id}/reopen")
def reopen_form(
    form_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "use")),
):
    """Reddedilmiş formu yeniden aç (rejected → draft)."""
    form = db.query(QualityForm).filter(QualityForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form bulunamadı")

    if form.status != "rejected":
        raise HTTPException(
            status_code=400,
            detail="Sadece reddedilmiş formlar yeniden açılabilir",
        )

    # Yetki: yalnızca formun doldurucusu veya onaylayanı yeniden açabilir.
    # (Kardeş fill/submit → _check_filler, review → _check_approver; reopen ikisine de açık.)
    # Aksi halde herhangi bir quality.forms:use kullanıcısı review alanlarını silebilirdi.
    if not (_check_filler(db, form.template_id, current_user)
            or _check_approver(db, form.template_id, current_user)):
        raise HTTPException(status_code=403, detail="Bu formu yeniden açma yetkiniz yok")

    form.status = "draft"
    form.reviewed_by = None
    form.reviewed_at = None
    form.review_comment = None

    log_action(
        db, current_user.id, "update", "quality_form",
        entity_id=form_id,
        details="Form yeniden açıldı",
        ip_address=get_client_ip(request),
    )
    db.commit()

    # WS bildirimi
    template = db.query(QualityTemplate).filter(
        QualityTemplate.id == form.template_id
    ).first()
    _notify_quality_event(
        "reopened", form_id,
        template.name if template else "—",
        form.period_date,
        _user_display(current_user),
        exclude_user_id=current_user.id,
    )

    return _load_form_detail(form_id, db)
