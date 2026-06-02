"""Kalite formu PDF dışa aktarma endpoint'i."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.quality_form import QualityForm
from app.models.quality_template import QualityTemplate
from app.models.user import User
from app.utils.audit import log_action
from app.utils.pdf_quality import generate_quality_form_pdf

from ._helpers import _build_form_detail

router = APIRouter()


@router.get("/forms/{form_id}/pdf")
def export_form_pdf(
    form_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.forms", "view")),
):
    """Onaylanmış formu PDF olarak döndür (tarayıcıda görüntüleme)."""
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

    if form.status != "approved":
        raise HTTPException(
            status_code=400,
            detail="Sadece onaylanmış formlar PDF olarak dışa aktarılabilir",
        )

    # Şablon altbilgi ve logo bilgilerini al
    template = db.query(QualityTemplate).filter(
        QualityTemplate.id == form.template_id
    ).first()
    footer_text = template.footer_text if template else None
    logo_filename = template.logo_filename if template else None

    detail = _build_form_detail(form, db, include_comparisons=True)
    pdf_bytes = generate_quality_form_pdf(
        detail, footer_text=footer_text, logo_filename=logo_filename,
    )

    # Dosya adı: sablon_tarih.pdf
    safe_name = (detail.get("template_name") or "form").replace(" ", "_")[:40]
    period = str(detail.get("period_date", ""))
    filename = f"{safe_name}_{period}.pdf"

    log_action(
        db, current_user.id, "download", "quality_form",
        entity_id=form_id,
        details="PDF raporu indirildi",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )
