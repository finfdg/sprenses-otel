"""Kalite şablon CRUD endpoint'leri."""

import math
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.quality_form import QualityForm
from app.models.quality_template import QualityTemplate
from app.models.quality_template_assignee import QualityTemplateAssignee
from app.models.quality_template_field import QualityTemplateField
from app.models.quality_template_section import QualityTemplateSection
from app.models.user import User
from app.schemas.quality import (
    TemplateAssigneeResponse,
    TemplateCreate,
    TemplateDetailResponse,
    TemplateFieldResponse,
    TemplateListResponse,
    TemplateSectionResponse,
    TemplateUpdate,
)
from app.utils.approval_check import check_approval
from app.utils.audit import log_action

router = APIRouter()

# Logo yükleme dizini
_LOGOS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads" / "logos"
_LOGOS_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
_MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB


# ─── Yardımcı fonksiyonlar ────────────────────────────────────────────


def _build_template_detail(t: QualityTemplate) -> dict:
    """Şablon detay yanıtı oluştur."""
    sections = []
    for s in t.sections:
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
        sections.append(TemplateSectionResponse(
            id=s.id,
            name=s.name,
            sort_order=s.sort_order,
            fields=fields,
        ))

    assignees = []
    for a in t.assignees:
        assignees.append(TemplateAssigneeResponse(
            id=a.id,
            assignment_type=a.assignment_type,
            user_id=a.user_id,
            role_id=a.role_id,
            user_name=a.user.full_name if a.user else None,
            role_name=a.role.name if a.role else None,
        ))

    logo_url = None
    if t.logo_filename:
        logo_url = "/uploads/logos/%s" % t.logo_filename

    return TemplateDetailResponse(
        id=t.id,
        name=t.name,
        description=t.description,
        frequency=t.frequency,
        is_active=t.is_active,
        footer_text=t.footer_text,
        increase_threshold=t.increase_threshold if t.increase_threshold is not None else 10.0,
        decrease_threshold=t.decrease_threshold if t.decrease_threshold is not None else 10.0,
        logo_url=logo_url,
        sections=sections,
        assignees=assignees,
        created_by=t.created_by,
        creator_name=t.creator.full_name if t.creator else None,
        created_at=t.created_at,
        updated_at=t.updated_at,
    ).model_dump()


def _save_sections(db: Session, template_id: int, sections_data: list) -> None:
    """Şablon bölümlerini ve alanlarını kaydet."""
    for i, sec_data in enumerate(sections_data):
        section = QualityTemplateSection(
            template_id=template_id,
            name=sec_data.name,
            sort_order=sec_data.sort_order if sec_data.sort_order else i,
        )
        db.add(section)
        db.flush()

        for j, field_data in enumerate(sec_data.fields):
            field = QualityTemplateField(
                section_id=section.id,
                label=field_data.label,
                field_type=field_data.field_type,
                unit=field_data.unit,
                is_required=field_data.is_required,
                is_resource=field_data.is_resource,
                is_guest_count=field_data.is_guest_count,
                is_meter=field_data.is_meter,
                is_month_end_only=field_data.is_month_end_only,
                options=field_data.options,
                sort_order=field_data.sort_order if field_data.sort_order else j,
            )
            db.add(field)


def _save_assignees(db: Session, template_id: int, assignees_data: list) -> None:
    """Şablon atamalarını kaydet."""
    for a_data in assignees_data:
        assignee = QualityTemplateAssignee(
            template_id=template_id,
            assignment_type=a_data.assignment_type,
            user_id=a_data.user_id,
            role_id=a_data.role_id,
        )
        db.add(assignee)


# ─── Şablon Listesi ───────────────────────────────────────────────────


@router.get("/templates/")
def list_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("quality.templates", "view")),
):
    """Şablon listesi (paginated)."""
    # Bölüm ve alan sayılarını tek sorguda subquery ile hesapla (N+1 yok)
    section_count_sq = (
        db.query(
            QualityTemplateSection.template_id,
            func.count(QualityTemplateSection.id).label("section_count"),
        )
        .group_by(QualityTemplateSection.template_id)
        .subquery()
    )
    field_count_sq = (
        db.query(
            QualityTemplateSection.template_id,
            func.count(QualityTemplateField.id).label("field_count"),
        )
        .join(QualityTemplateField, QualityTemplateField.section_id == QualityTemplateSection.id)
        .group_by(QualityTemplateSection.template_id)
        .subquery()
    )

    q = (
        db.query(
            QualityTemplate,
            func.coalesce(section_count_sq.c.section_count, 0).label("section_count"),
            func.coalesce(field_count_sq.c.field_count, 0).label("field_count"),
        )
        .outerjoin(section_count_sq, QualityTemplate.id == section_count_sq.c.template_id)
        .outerjoin(field_count_sq, QualityTemplate.id == field_count_sq.c.template_id)
    )

    if is_active is not None:
        q = q.filter(QualityTemplate.is_active == is_active)

    total = q.count()
    rows = (
        q.order_by(QualityTemplate.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for t, sec_count, fld_count in rows:
        items.append(TemplateListResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            frequency=t.frequency,
            is_active=t.is_active,
            section_count=sec_count,
            field_count=fld_count,
            created_at=t.created_at,
        ).model_dump())

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


# ─── Şablon Detay ─────────────────────────────────────────────────────


@router.get("/templates/{template_id}")
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("quality.templates", "view")),
):
    """Şablon detay (bölümler, alanlar, atamalar dahil)."""
    t = (
        db.query(QualityTemplate)
        .options(
            joinedload(QualityTemplate.creator),
            joinedload(QualityTemplate.sections)
            .joinedload(QualityTemplateSection.fields),
            joinedload(QualityTemplate.assignees)
            .joinedload(QualityTemplateAssignee.user),
            joinedload(QualityTemplate.assignees)
            .joinedload(QualityTemplateAssignee.role),
        )
        .filter(QualityTemplate.id == template_id)
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı")

    return _build_template_detail(t)


# ─── Şablon Oluştur ───────────────────────────────────────────────────


@router.post("/templates/", status_code=status.HTTP_201_CREATED)
def create_template(
    data: TemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.templates", "use")),
):
    """Yeni şablon oluştur (bölümler, alanlar, atamalar dahil)."""
    approval_resp = check_approval(db, "quality.templates", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Şablon adı boş olamaz")

    if data.frequency not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="Geçersiz sıklık değeri")

    template = QualityTemplate(
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        frequency=data.frequency,
        is_active=data.is_active,
        footer_text=data.footer_text.strip() if data.footer_text else None,
        increase_threshold=data.increase_threshold if data.increase_threshold is not None else 10.0,
        decrease_threshold=data.decrease_threshold if data.decrease_threshold is not None else 10.0,
        created_by=current_user.id,
    )
    db.add(template)
    db.flush()

    # Bölüm ve alanları kaydet
    if data.sections:
        _save_sections(db, template.id, data.sections)

    # Atamaları kaydet
    if data.assignees:
        _save_assignees(db, template.id, data.assignees)

    log_action(
        db, current_user.id, "create", "quality_template",
        entity_id=template.id,
        details=f"Şablon oluşturuldu: {template.name}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    # Detay yanıtını döndür
    return get_template(template.id, db, current_user)


# ─── Şablon Güncelle ──────────────────────────────────────────────────


@router.patch("/templates/{template_id}")
def update_template(
    template_id: int,
    data: TemplateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.templates", "use")),
):
    """Şablonu güncelle."""
    template = db.query(QualityTemplate).filter(QualityTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı")

    approval_resp = check_approval(db, "quality.templates", template_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp

    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(status_code=400, detail="Şablon adı boş olamaz")
        template.name = data.name.strip()

    if data.description is not None:
        template.description = data.description.strip() if data.description else None

    if data.frequency is not None:
        if data.frequency not in ("daily", "weekly", "monthly"):
            raise HTTPException(status_code=400, detail="Geçersiz sıklık değeri")
        template.frequency = data.frequency

    if data.is_active is not None:
        template.is_active = data.is_active

    if data.footer_text is not None:
        template.footer_text = data.footer_text.strip() if data.footer_text else None

    if data.increase_threshold is not None:
        template.increase_threshold = data.increase_threshold

    if data.decrease_threshold is not None:
        template.decrease_threshold = data.decrease_threshold

    # Bölümler değiştiyse mevcut bölümleri sil, yenilerini ekle
    if data.sections is not None:
        # Form varsa bölüm yapısı değiştirilemez (orphan value riski)
        form_count = (
            db.query(func.count(QualityForm.id))
            .filter(QualityForm.template_id == template_id)
            .scalar()
        )
        if form_count and form_count > 0:
            raise HTTPException(
                status_code=400,
                detail="Bu şablona ait %d form bulunduğu için bölüm yapısı değiştirilemez. "
                       "Mevcut formları silmeden şablon alanlarını düzenleyemezsiniz." % form_count,
            )
        # Mevcut bölümleri sil (cascade ile alanlar da silinir)
        db.query(QualityTemplateSection).filter(
            QualityTemplateSection.template_id == template_id
        ).delete()
        db.flush()
        _save_sections(db, template_id, data.sections)

    # Atamalar değiştiyse mevcut atamaları sil, yenilerini ekle
    if data.assignees is not None:
        db.query(QualityTemplateAssignee).filter(
            QualityTemplateAssignee.template_id == template_id
        ).delete()
        db.flush()
        _save_assignees(db, template_id, data.assignees)

    log_action(
        db, current_user.id, "update", "quality_template",
        entity_id=template_id,
        details=f"Şablon güncellendi: {template.name}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return get_template(template_id, db, current_user)


# ─── Şablon Sil ───────────────────────────────────────────────────────


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.templates", "use")),
):
    """Şablonu sil (form yoksa)."""
    template = db.query(QualityTemplate).filter(QualityTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı")

    approval_resp = check_approval(db, "quality.templates", template_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    # Form var mı kontrol et
    form_count = (
        db.query(func.count(QualityForm.id))
        .filter(QualityForm.template_id == template_id)
        .scalar()
    )
    if form_count and form_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Bu şablona ait {form_count} form bulunduğu için silinemez",
        )

    template_name = template.name

    # Logo dosyasını sil
    if template.logo_filename:
        logo_path = _LOGOS_DIR / template.logo_filename
        if logo_path.is_file():
            logo_path.unlink(missing_ok=True)

    db.delete(template)

    log_action(
        db, current_user.id, "delete", "quality_template",
        entity_id=template_id,
        details=f"Şablon silindi: {template_name}",
        ip_address=get_client_ip(request),
    )
    db.commit()


# ─── Logo Yükle ──────────────────────────────────────────────────────


@router.post("/templates/{template_id}/logo")
async def upload_template_logo(
    template_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.templates", "use")),
):
    """Şablon logosu yükle/değiştir."""
    template = db.query(QualityTemplate).filter(QualityTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı")

    # Dosya uzantısı kontrolü
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_LOGO_EXTS:
        raise HTTPException(
            status_code=400,
            detail="Desteklenmeyen dosya formatı. PNG, JPG, SVG veya WEBP yükleyin.",
        )

    # Dosya boyutu kontrolü
    content = await file.read()
    if len(content) > _MAX_LOGO_SIZE:
        raise HTTPException(status_code=400, detail="Logo dosyası 2 MB'dan küçük olmalıdır")

    # Magic bytes ile gerçek dosya tipi doğrulama (SVG XSS engeli)
    _MAGIC = {
        ".png": b"\x89PNG",
        ".jpg": b"\xff\xd8\xff",
        ".jpeg": b"\xff\xd8\xff",
        ".webp": b"RIFF",
    }
    if ext == ".svg":
        # SVG dosyasında <script> tagı varsa reddet
        text = content.decode("utf-8", errors="ignore").lower()
        if "<script" in text or "javascript:" in text or "on" + "load=" in text:
            raise HTTPException(status_code=400, detail="SVG dosyasında zararlı içerik tespit edildi")
    elif ext in _MAGIC:
        if not content[:4].startswith(_MAGIC[ext]):
            raise HTTPException(status_code=400, detail="Dosya içeriği uzantısıyla uyuşmuyor")

    # Eski logoyu sil
    if template.logo_filename:
        old_path = _LOGOS_DIR / template.logo_filename
        if old_path.is_file():
            old_path.unlink(missing_ok=True)

    # Yeni dosyayı kaydet
    new_filename = "%s_%s%s" % (template_id, uuid.uuid4().hex[:8], ext)
    new_path = _LOGOS_DIR / new_filename
    with open(new_path, "wb") as f:
        f.write(content)

    template.logo_filename = new_filename

    log_action(
        db, current_user.id, "update", "quality_template",
        entity_id=template_id,
        details="Logo yüklendi: %s" % file.filename,
        ip_address=get_client_ip(request),
    )
    db.commit()

    return {
        "logo_url": "/uploads/logos/%s" % new_filename,
        "message": "Logo başarıyla yüklendi",
    }


# ─── Logo Sil ────────────────────────────────────────────────────────


@router.delete("/templates/{template_id}/logo")
def delete_template_logo(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("quality.templates", "use")),
):
    """Şablon logosunu sil."""
    template = db.query(QualityTemplate).filter(QualityTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı")

    if not template.logo_filename:
        raise HTTPException(status_code=400, detail="Şablonun logosu yok")

    # Dosyayı sil
    logo_path = _LOGOS_DIR / template.logo_filename
    if logo_path.is_file():
        logo_path.unlink(missing_ok=True)

    template.logo_filename = None

    log_action(
        db, current_user.id, "update", "quality_template",
        entity_id=template_id,
        details="Logo silindi",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return {"message": "Logo silindi"}
