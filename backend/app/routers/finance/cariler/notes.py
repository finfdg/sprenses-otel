"""Cari notları — cari hakkında görüşme/takip notları (ekle/düzenle/sil/yapıldı).

Tasarım (2026-07-04, "Sprenses Tasarımlar" · Cariler yeniden tasarımı): cari detayında
"Notlar" sekmesi. Notlar FİNANSAL ETKİSİ OLMAYAN metadatadır (finance_events'e yazılmaz)
→ **onaydan muaftır** (payment_deferral / manuel-banka-hareketi gibi operasyonel-özel
endpoint istisnası). Yine de `require_permission(finance.cariler, use)` + audit + WS
broadcast zorunludur (CLAUDE.md kuralları). `author_name` yazma anında snapshot alınır.
"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_note import VendorNote
from app.schemas.vendor import VendorNoteCreate, VendorNoteResponse, VendorNoteUpdate
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update

from ._helpers import logger

router = APIRouter()


def _require_vendor(db: Session, vendor_id: int) -> Vendor:
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")
    return vendor


# ─── Not Listesi ─────────────────────────────────────────

@router.get("/vendors/{vendor_id}/notes", response_model=List[VendorNoteResponse])
def list_vendor_notes(
    vendor_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Carinin notlarını getir (en yeni en üstte)."""
    _require_vendor(db, vendor_id)
    notes = (
        db.query(VendorNote)
        .filter(VendorNote.vendor_id == vendor_id)
        .order_by(VendorNote.created_at.desc(), VendorNote.id.desc())
        .all()
    )
    return notes


# ─── Not Ekle ────────────────────────────────────────────

@router.post("/vendors/{vendor_id}/notes", response_model=VendorNoteResponse)
def create_vendor_note(
    vendor_id: int,
    body: VendorNoteCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cariye yeni not ekle. Onaydan muaf (finansal etkisi yok) — use + audit + broadcast."""
    _require_vendor(db, vendor_id)

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Not metni boş olamaz")

    note = VendorNote(
        vendor_id=vendor_id,
        text=text,
        author_id=current_user.id,
        author_name=current_user.full_name,
        done=False,
    )
    db.add(note)

    try:
        db.flush()
        log_action(
            db, current_user.id, "create", "vendor_note",
            entity_id=note.id,
            details=f"Cari notu eklendi (cari #{vendor_id})",
            ip_address=get_client_ip(request),
        )
        db.commit()
        db.refresh(note)
    except Exception as e:
        db.rollback()
        logger.error("Cari notu ekleme hatası (vendor_id=%s): %s", vendor_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Not eklenirken bir hata oluştu.")

    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "update")
    return note


# ─── Not Güncelle (metin / yapıldı) ──────────────────────

@router.patch("/vendors/{vendor_id}/notes/{note_id}", response_model=VendorNoteResponse)
def update_vendor_note(
    vendor_id: int,
    note_id: int,
    body: VendorNoteUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari notunu güncelle (metin ve/veya 'yapıldı' işareti). Onaydan muaf."""
    note = (
        db.query(VendorNote)
        .filter(VendorNote.id == note_id, VendorNote.vendor_id == vendor_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Not bulunamadı")

    fields = body.model_dump(exclude_unset=True)
    if "text" in fields:
        new_text = (fields["text"] or "").strip()
        if not new_text:
            raise HTTPException(status_code=400, detail="Not metni boş olamaz")
        note.text = new_text
    if "done" in fields:
        note.done = bool(fields["done"])

    try:
        log_action(
            db, current_user.id, "update", "vendor_note",
            entity_id=note.id,
            details=f"Cari notu güncellendi (cari #{vendor_id})",
            ip_address=get_client_ip(request),
        )
        db.commit()
        db.refresh(note)
    except Exception as e:
        db.rollback()
        logger.error("Cari notu güncelleme hatası (note_id=%s): %s", note_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Not güncellenirken bir hata oluştu.")

    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "update")
    return note


# ─── Not Sil ─────────────────────────────────────────────

@router.delete("/vendors/{vendor_id}/notes/{note_id}")
def delete_vendor_note(
    vendor_id: int,
    note_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Cari notunu sil. Onaydan muaf."""
    note = (
        db.query(VendorNote)
        .filter(VendorNote.id == note_id, VendorNote.vendor_id == vendor_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Not bulunamadı")

    try:
        db.delete(note)
        log_action(
            db, current_user.id, "delete", "vendor_note",
            entity_id=note_id,
            details=f"Cari notu silindi (cari #{vendor_id})",
            ip_address=get_client_ip(request),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Cari notu silme hatası (note_id=%s): %s", note_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Not silinirken bir hata oluştu.")

    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "update")
    return {"ok": True}
