"""Kalite formu CRUD endpoint'leri — listele, detay, oluştur, sil."""

import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.quality_form import QualityForm
from app.models.quality_template import QualityTemplate
from app.models.user import User
from app.routers.quality.scheduler import _get_period_date
from app.schemas.quality import FormCreate, FormListResponse
from app.services import quality_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action

from ._helpers import _build_form_detail, _check_filler, _user_display

router = APIRouter()


# ─── Form Listesi ─────────────────────────────────────────────────────


@router.get("/forms/")
def list_forms(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    template_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("quality.forms", "view")),
):
    """Form listesi (paginated, filtrelenebilir)."""
    # Otomatik form oluşturma: aktif şablonlar için eksik formları oluştur
    today = date.today()
    active_templates = (
        db.query(QualityTemplate)
        .filter(QualityTemplate.is_active == True)
        .all()
    )
    auto_generated = 0
    for t in active_templates:
        period_date = _get_period_date(t.frequency, today)
        if not period_date:
            continue
        existing = (
            db.query(QualityForm)
            .filter(
                QualityForm.template_id == t.id,
                QualityForm.period_date == period_date,
            )
            .first()
        )
        if not existing:
            db.add(QualityForm(
                template_id=t.id,
                period_date=period_date,
                status="draft",
            ))
            auto_generated += 1
    if auto_generated > 0:
        db.commit()

    q = (
        db.query(QualityForm)
        .options(
            joinedload(QualityForm.template),
            joinedload(QualityForm.filler),
            joinedload(QualityForm.reviewer),
        )
    )

    if status_filter:
        q = q.filter(QualityForm.status == status_filter)
    if template_id:
        q = q.filter(QualityForm.template_id == template_id)
    if date_from:
        q = q.filter(QualityForm.period_date >= date_from)
    if date_to:
        q = q.filter(QualityForm.period_date <= date_to)

    total = q.count()
    forms = (
        q.order_by(desc(QualityForm.period_date), desc(QualityForm.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for f in forms:
        items.append(FormListResponse(
            id=f.id,
            template_id=f.template_id,
            template_name=f.template.name if f.template else "—",
            period_date=f.period_date,
            status=f.status,
            filled_by_name=_user_display(f.filler),
            submitted_at=f.submitted_at,
            reviewed_by_name=_user_display(f.reviewer),
            reviewed_at=f.reviewed_at,
            created_at=f.created_at,
        ).model_dump())

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


# ─── Form Detay ───────────────────────────────────────────────────────


@router.get("/forms/{form_id}")
def get_form(
    form_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("quality.forms", "view")),
):
    """Form detay (şablon yapısı + değerler + önceki değerler)."""
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


# ─── Form Oluştur ─────────────────────────────────────────────────────


@router.post("/forms/", status_code=status.HTTP_201_CREATED)
def create_form(
    data: FormCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "use")),
):
    """Manuel form oluştur."""
    template = db.query(QualityTemplate).filter(QualityTemplate.id == data.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı")
    if not template.is_active:
        raise HTTPException(status_code=400, detail="Şablon aktif değil")

    approval_resp = check_approval(db, "quality.forms", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    # Aynı tarih-şablon çifti var mı kontrol et
    existing = (
        db.query(QualityForm)
        .filter(
            QualityForm.template_id == data.template_id,
            QualityForm.period_date == data.period_date,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Bu şablon için bu tarihe ait form zaten var",
        )

    form = quality_service.create_form(
        db,
        template_id=data.template_id,
        period_date=data.period_date,
    )

    log_action(
        db, current_user.id, "create", "quality_form",
        entity_id=form.id,
        details=f"Form oluşturuldu: {template.name} ({data.period_date})",
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(form)

    # Detay yanıtı için form'u yükle (filler/reviewer/values ile)
    form = (
        db.query(QualityForm)
        .options(
            joinedload(QualityForm.filler),
            joinedload(QualityForm.reviewer),
            joinedload(QualityForm.values),
        )
        .filter(QualityForm.id == form.id)
        .first()
    )
    return _build_form_detail(form, db)


# ─── Form Sil ────────────────────────────────────────────────────────


@router.delete("/forms/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form(
    form_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "use")),
):
    """Taslak formu sil (sadece draft durumundaki formlar silinebilir)."""
    form = db.query(QualityForm).filter(QualityForm.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form bulunamadı")

    approval_resp = check_approval(db, "quality.forms", form_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    if form.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Sadece taslak durumundaki formlar silinebilir",
        )

    # Dolduran yetkisi kontrol et
    if not _check_filler(db, form.template_id, current_user):
        raise HTTPException(
            status_code=403,
            detail="Bu formu silme yetkiniz yok",
        )

    # Şablon adını al (audit log için)
    template = db.query(QualityTemplate).filter(
        QualityTemplate.id == form.template_id
    ).first()
    template_name = template.name if template else "—"

    quality_service.delete_form(db, form)

    log_action(
        db, current_user.id, "delete", "quality_form",
        entity_id=form_id,
        details="Form silindi: %s (%s)" % (template_name, form.period_date),
        ip_address=get_client_ip(request),
    )
    db.commit()
