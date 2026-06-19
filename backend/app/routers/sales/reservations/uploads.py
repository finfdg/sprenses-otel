"""Otel rezervasyon dosya yükleme, yükleme geçmişi ve toplu silme endpoint'leri."""

import asyncio
import json
import os
import uuid
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip, upload_limiter
from app.models.reservation import Reservation, ReservationUpload
from app.models.user import User
from app.schemas.reservation import (
    BulkDeleteRequest,
    BulkDeleteResult,
    RemovalCandidate,
    ReservationUploadResponse,
    ReservationUploadResult,
)
from app.utils.audit import log_action
from app.utils.file_validation import validate_upload_file
from app.utils.reservation_parser import parse_reservation_excel
from app.constants import BroadcastModule
from app.utils.sales_broadcast import broadcast_sales_update

from ._helpers import UPLOAD_DIR, _ensure_upload_dir, logger

router = APIRouter()


def _compute_removal_candidates(
    db: Session,
    excel_rec_ids: set,
    checkin_start: Optional[date_cls],
    checkin_end: Optional[date_cls],
    record_start: Optional[date_cls],
    record_end: Optional[date_cls],
) -> list:
    """Yüklemenin kapsamı içinde olduğu halde Excel'de bulunmayan rezervasyonları belirle.

    Kapsam = (parsed.checkin_start ↔ checkin_end) ∩ (parsed.record_start ↔ record_end).
    Bu aralığa düşen DB kayıtlarından dosyadaki rec_id'lerde olmayanlar aday gösterilir —
    bunlar büyük olasılıkla kaynak sistemde iptal edilmiş rezervasyonlardır.
    """
    if not (checkin_start and checkin_end and record_start and record_end):
        return []

    rows = (
        db.query(Reservation)
        .filter(
            Reservation.checkin_date >= checkin_start,
            Reservation.checkin_date <= checkin_end,
            Reservation.record_date >= record_start,
            Reservation.record_date <= record_end,
        )
        .all()
    )

    candidates: list = []
    for r in rows:
        if r.rec_id in excel_rec_ids:
            continue
        candidates.append(RemovalCandidate(
            id=r.id,
            rec_id=r.rec_id,
            agency=r.agency,
            room_type=r.room_type,
            voucher=r.voucher,
            guests=r.guests,
            checkin_date=r.checkin_date,
            checkout_date=r.checkout_date,
            nights=r.nights,
            record_date=r.record_date,
            rooms=r.rooms,
            nation=r.nation,
            eur_total=float(r.eur_total or 0),
            rez_status=r.rez_status,
            status=r.status,
        ))

    candidates.sort(key=lambda c: (c.checkin_date, c.agency or "", c.id))
    return candidates


# ─── Dosya Yükleme ──────────────────────────────────────


@router.post("/upload")
async def upload_reservations(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.hotel_reservation", "use")),
):
    """Crystal Reports rezervasyon XLS/XLSX dosyasını yükle ve upsert et."""
    upload_limiter.check(f"upload-{get_client_ip(request)}")
    content = await validate_upload_file(file, allowed_types=["excel"])

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("xls", "xlsx"):
        raise HTTPException(status_code=400, detail="Sadece .xls veya .xlsx dosyaları kabul edilir")

    _ensure_upload_dir()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as f:
        f.write(content)

    try:
        # CPU-yoğun Excel parse'ı threadpool'a al → event loop bloke olmaz (eşzamanlı istekler beklemez)
        parsed = await asyncio.to_thread(parse_reservation_excel, file_path)
    except Exception as e:
        logger.error("Rezervasyon dosyası ayrıştırma hatası (%s): %s", file.filename, e, exc_info=True)
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=400,
            detail=f"Dosya ayrıştırılamadı: {str(e)[:200]}",
        )

    if not parsed.reservations:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Dosyada rezervasyon kaydı bulunamadı")

    # ── Upload kaydı ────────────────────────────────────────
    upload = ReservationUpload(
        file_name=file.filename or unique_name,
        file_url=file_path,
        file_type=ext,
        hotel_name=parsed.hotel_name,
        period_checkin_start=parsed.checkin_start,
        period_checkin_end=parsed.checkin_end,
        period_record_start=parsed.record_start,
        period_record_end=parsed.record_end,
        uploaded_by=current_user.id,
    )
    db.add(upload)
    db.flush()

    # ── Upsert ──────────────────────────────────────────────
    rec_ids = [p.rec_id for p in parsed.reservations]
    existing = {
        r.rec_id: r for r in
        db.query(Reservation).filter(Reservation.rec_id.in_(rec_ids)).all()
    }

    new_count = 0
    updated_count = 0

    for p in parsed.reservations:
        cur = existing.get(p.rec_id)
        if cur:
            cur.upload_id = upload.id
            cur.agency = p.agency
            cur.room_type = p.room_type
            cur.voucher = p.voucher
            cur.guests = p.guests
            cur.checkin_date = p.checkin_date
            cur.checkout_date = p.checkout_date
            cur.nights = p.nights
            cur.record_date = p.record_date
            cur.board = p.board
            cur.vip_type = p.vip_type
            cur.rooms = p.rooms
            cur.adult = p.adult
            cur.child_paid = p.child_paid
            cur.child_free = p.child_free
            cur.baby = p.baby
            cur.nation = p.nation
            cur.net_amount = p.net_amount
            cur.currency = p.currency
            cur.eur_total = p.eur_total
            cur.per_room = p.per_room
            cur.per_adult = p.per_adult
            cur.rez_status = p.rez_status
            cur.status = p.status
            updated_count += 1
        else:
            db.add(Reservation(
                rec_id=p.rec_id,
                upload_id=upload.id,
                agency=p.agency,
                room_type=p.room_type,
                voucher=p.voucher,
                guests=p.guests,
                checkin_date=p.checkin_date,
                checkout_date=p.checkout_date,
                nights=p.nights,
                record_date=p.record_date,
                board=p.board,
                vip_type=p.vip_type,
                rooms=p.rooms,
                adult=p.adult,
                child_paid=p.child_paid,
                child_free=p.child_free,
                baby=p.baby,
                nation=p.nation,
                net_amount=p.net_amount,
                currency=p.currency,
                eur_total=p.eur_total,
                per_room=p.per_room,
                per_adult=p.per_adult,
                rez_status=p.rez_status,
                status=p.status,
            ))
            new_count += 1

    upload.total_rows = len(parsed.reservations)
    upload.new_rows = new_count
    upload.updated_rows = updated_count

    # Kapsamda olduğu halde dosyada bulunmayan kayıtlar — olası iptaller
    excel_rec_ids = {p.rec_id for p in parsed.reservations}
    removal_candidates = _compute_removal_candidates(
        db,
        excel_rec_ids,
        parsed.checkin_start,
        parsed.checkin_end,
        parsed.record_start,
        parsed.record_end,
    )

    log_action(
        db, current_user.id, "upload", "reservation_upload",
        entity_id=upload.id,
        details=json.dumps({
            "file": file.filename,
            "hotel": parsed.hotel_name,
            "total": len(parsed.reservations),
            "new": new_count,
            "updated": updated_count,
            "removal_candidates": len(removal_candidates),
        }, ensure_ascii=False),
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.HOTEL_RESERVATION, "upload")

    return ReservationUploadResult(
        upload_id=upload.id,
        file_name=upload.file_name,
        hotel_name=upload.hotel_name,
        period_checkin_start=upload.period_checkin_start,
        period_checkin_end=upload.period_checkin_end,
        total_rows=upload.total_rows,
        new_rows=upload.new_rows,
        updated_rows=upload.updated_rows,
        removal_candidates=removal_candidates,
    ).model_dump(mode="json")


# ─── Yükleme Geçmişi ────────────────────────────────────


@router.get("/uploads")
def list_uploads(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.hotel_reservation", "view")),
):
    """Yükleme geçmişi."""
    uploads = (
        db.query(ReservationUpload, User.first_name, User.last_name)
        .outerjoin(User, ReservationUpload.uploaded_by == User.id)
        .order_by(desc(ReservationUpload.uploaded_at))
        .all()
    )
    return [
        ReservationUploadResponse(
            id=u.id,
            file_name=u.file_name,
            hotel_name=u.hotel_name,
            period_checkin_start=u.period_checkin_start,
            period_checkin_end=u.period_checkin_end,
            period_record_start=u.period_record_start,
            period_record_end=u.period_record_end,
            total_rows=u.total_rows,
            new_rows=u.new_rows,
            updated_rows=u.updated_rows,
            uploaded_by=u.uploaded_by,
            uploader_name=f"{fn or ''} {ln or ''}".strip() if fn or ln else None,
            uploaded_at=u.uploaded_at,
        ).model_dump(mode="json")
        for u, fn, ln in uploads
    ]


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(
    upload_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.hotel_reservation", "use")),
):
    """Yüklemeyi sil — rezervasyon satırları korunur (upload_id NULL'a düşer)."""
    upload = db.query(ReservationUpload).filter(ReservationUpload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Yükleme bulunamadı")

    if upload.file_url and os.path.exists(upload.file_url):
        try:
            os.remove(upload.file_url)
        except OSError as e:
            logger.warning("Yükleme dosyası silinemedi (%s): %s", upload.file_url, e)

    log_action(
        db, current_user.id, "delete", "reservation_upload",
        entity_id=upload_id,
        details=f"Rezervasyon yüklemesi silindi: {upload.file_name}",
        ip_address=get_client_ip(request),
    )
    db.delete(upload)
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.HOTEL_RESERVATION, "delete")


# ─── Toplu Silme (kaynakta olmayan kayıtlar) ────────────


@router.post("/bulk-delete")
def bulk_delete_reservations(
    body: BulkDeleteRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.hotel_reservation", "use")),
):
    """Excel'de bulunmayan rezervasyonları toplu sil — upload sonrası onay akışı için.

    `removal_candidates` listesinden seçilen ID'ler bu endpoint'e gönderilir. Audit log'a
    silinen kayıtların kısa özeti yazılır. Tek seferde maksimum 5000 ID (DoS koruma).
    """
    if not body.ids:
        return BulkDeleteResult(deleted=0, skipped=0).model_dump()

    if len(body.ids) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Tek seferde en fazla 5000 kayıt silinebilir.",
        )

    deleted = 0
    skipped = 0
    skipped_reasons: list = []

    try:
        rows = db.query(Reservation).filter(Reservation.id.in_(body.ids)).all()
        found_ids = {r.id for r in rows}
        missing = len(body.ids) - len(found_ids)
        if missing:
            skipped += missing
            skipped_reasons.append(f"{missing} kayıt bulunamadı")

        total_eur = 0.0
        for r in rows:
            total_eur += float(r.eur_total or 0)
            db.delete(r)
            deleted += 1

        if deleted:
            log_action(
                db, current_user.id, "bulk_delete", "reservation",
                entity_id=None,
                details=json.dumps({
                    "deleted": deleted,
                    "skipped": skipped,
                    "total_eur": round(total_eur, 2),
                    "context": "Kaynakta olmayan rezervasyonlar (toplu silme)",
                }, ensure_ascii=False),
                ip_address=get_client_ip(request),
            )

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("Toplu rezervasyon silme hatası: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Rezervasyonlar silinirken bir veritabanı hatası oluştu.",
        )

    if deleted:
        broadcast_sales_update(background_tasks, BroadcastModule.HOTEL_RESERVATION, "delete")

    return BulkDeleteResult(
        deleted=deleted,
        skipped=skipped,
        skipped_reasons=skipped_reasons,
    ).model_dump()
