"""Kalite form otomatik oluşturma zamanlayıcısı."""

from datetime import date, timedelta
from typing import Optional

import pytz
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.quality_form import QualityForm
from app.models.quality_template import QualityTemplate
from app.models.user import User
from app.utils.audit import log_action

router = APIRouter()

tz_istanbul = pytz.timezone("Europe/Istanbul")


def _get_period_date(frequency: str, today: date) -> Optional[date]:
    """Şablon sıklığına göre periyod tarihini hesapla."""
    if frequency == "daily":
        return today
    elif frequency == "weekly":
        # Haftanın Pazartesi günü
        return today - timedelta(days=today.weekday())
    elif frequency == "monthly":
        # Ayın 1'i
        return today.replace(day=1)
    return None


@router.post("/scheduler/generate")
def generate_forms(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "use")),
):
    """Aktif şablonlara göre bugünün formlarını oluştur."""
    today = date.today()

    templates = (
        db.query(QualityTemplate)
        .filter(QualityTemplate.is_active == True)
        .all()
    )

    generated = 0
    skipped = 0

    for t in templates:
        period_date = _get_period_date(t.frequency, today)
        if not period_date:
            skipped += 1
            continue

        # Bu tarih-şablon çifti zaten var mı?
        existing = (
            db.query(QualityForm)
            .filter(
                QualityForm.template_id == t.id,
                QualityForm.period_date == period_date,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        form = QualityForm(
            template_id=t.id,
            period_date=period_date,
            status="draft",
        )
        db.add(form)
        generated += 1

    if generated > 0:
        log_action(
            db, current_user.id, "create", "quality_form",
            details=f"Zamanlayıcı: {generated} form oluşturuldu ({today})",
            ip_address=get_client_ip(request),
        )
        db.commit()

    return {
        "generated": generated,
        "skipped": skipped,
        "date": str(today),
    }


@router.get("/scheduler/status")
def scheduler_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("quality.forms", "view")),
):
    """Hangi şablonların bugün formu olduğunu kontrol et."""
    today = date.today()

    templates = (
        db.query(QualityTemplate)
        .filter(QualityTemplate.is_active == True)
        .all()
    )

    result = []
    for t in templates:
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

        result.append({
            "template_id": t.id,
            "template_name": t.name,
            "frequency": t.frequency,
            "period_date": str(period_date),
            "form_exists": existing is not None,
            "form_id": existing.id if existing else None,
            "form_status": existing.status if existing else None,
        })

    return result
