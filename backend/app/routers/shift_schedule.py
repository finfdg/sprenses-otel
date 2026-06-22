"""Vardiya çizelgesi (hr.shift_schedule) — tarih bazlı rota.

Hangi gün kim hangi vardiyada. `(personnel_id, work_date)` benzersizdir; bir hücre =
bir personelin bir gündeki vardiyası. Kayıt yoksa o gün **izinli/boş** demektir.

Onay akışı:
- Tek hücre atama (POST) ve çıkarma (DELETE) `check_approval`'dan geçer.
- Toplu işlemler (bulk doldur/temizle, hafta kopyalama) onay akışından **muaftır**
  (CLAUDE.md: "Dosya yükleme, toplu işlem, eşleştirme gibi özel endpoint'ler hariç").
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.constants import WSEvent
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.personnel import Personnel
from app.models.shift import ShiftDefinition
from app.models.shift_assignment import ShiftAssignment
from app.models.user import User
from app.services import hr_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

MODULE_CODE = "hr.shift_schedule"
MAX_RANGE_DAYS = 45     # GET aralık üst sınırı (haftalık/aylık görünüm)
MAX_BULK_CELLS = 2000   # toplu işlem hücre üst sınırı
TZ = pytz.timezone("Europe/Istanbul")

router = APIRouter()


# ─── Yardımcılar ─────────────────────────────────────────

def _now_tz() -> datetime:
    return datetime.now(TZ)


def _seg_minutes(s: time, e: time) -> int:
    sm = s.hour * 60 + s.minute
    em = e.hour * 60 + e.minute
    if em <= sm:
        em += 24 * 60  # gece yarısını geçer
    return em - sm


def _shift_brief(s: ShiftDefinition) -> dict:
    mins = _seg_minutes(s.start_time, s.end_time)
    if s.start_time2 and s.end_time2:
        mins += _seg_minutes(s.start_time2, s.end_time2)
    return {
        "id": s.id, "name": s.name, "color": s.color,
        "start_time": s.start_time.strftime("%H:%M") if s.start_time else None,
        "end_time": s.end_time.strftime("%H:%M") if s.end_time else None,
        "start_time2": s.start_time2.strftime("%H:%M") if s.start_time2 else None,
        "end_time2": s.end_time2.strftime("%H:%M") if s.end_time2 else None,
        "is_split": bool(s.start_time2 and s.end_time2),
        "crosses_midnight": s.end_time <= s.start_time,
        "duration_hours": round(mins / 60, 1),
    }


def _assignment_dict(a: ShiftAssignment) -> dict:
    return {
        "id": a.id,
        "personnel_id": a.personnel_id,
        "shift_id": a.shift_id,
        "work_date": a.work_date.isoformat(),
        "note": a.note,
    }


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Geçersiz tarih (YYYY-AA-GG bekleniyor)")


def _broadcast(action: str) -> None:
    """Açık çizelge ekranları anında tazelensin (polling yok)."""
    try:
        manager.send_to_all_sync({"type": WSEvent.SHIFT_SCHEDULE_UPDATED, "action": action})
    except Exception:
        logger.debug("Vardiya çizelgesi WS broadcast gönderilemedi", exc_info=True)


# Tek hücre upsert/sil app/services/hr_service'te (router + onay executor ORTAK kaynak).
# Toplu işlemler (bulk/copy-week) onaydan muaf → kendi inline upsert mantıklarını korur.


# ─── Şemalar ─────────────────────────────────────────────

class AssignCreate(BaseModel):
    personnel_id: int
    shift_id: int
    work_date: date
    note: Optional[str] = None


class BulkAssign(BaseModel):
    personnel_ids: List[int]
    shift_id: Optional[int] = None   # None → hücreleri temizle (sil)
    dates: List[date]
    note: Optional[str] = None


class CopyWeek(BaseModel):
    source_start: date
    target_start: date
    personnel_ids: Optional[List[int]] = None  # None → tüm personel


# ─── Endpoint'ler ────────────────────────────────────────

@router.get("/shift-schedule")
def get_schedule(
    start: str = Query(...),
    end: str = Query(...),
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Tarih aralığındaki rota: aktif vardiyalar + aktif personel + atamalar + departmanlar."""
    d_start = _parse_date(start)
    d_end = _parse_date(end)
    if d_end < d_start:
        raise HTTPException(status_code=400, detail="Bitiş tarihi başlangıçtan önce olamaz")
    if (d_end - d_start).days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Tarih aralığı en fazla {MAX_RANGE_DAYS} gün olabilir")

    shifts = (
        db.query(ShiftDefinition)
        .filter(ShiftDefinition.is_active.is_(True))
        .order_by(ShiftDefinition.sort_order, ShiftDefinition.start_time)
        .all()
    )

    # Departman filtre seçenekleri (filtreden ÖNCE — tüm seçenekler görünsün)
    dept_rows = (
        db.query(Personnel.department)
        .filter(Personnel.is_active.is_(True), Personnel.department.isnot(None))
        .distinct()
        .all()
    )
    departments = sorted({r[0] for r in dept_rows if r[0]}, key=lambda x: x.lower())

    pq = db.query(Personnel).filter(Personnel.is_active.is_(True))
    if department:
        pq = pq.filter(Personnel.department == department)
    personnel = pq.order_by(Personnel.department, Personnel.full_name).all()
    pids = [p.id for p in personnel]

    assignments = []
    if pids:
        assignments = (
            db.query(ShiftAssignment)
            .filter(
                ShiftAssignment.work_date >= d_start,
                ShiftAssignment.work_date <= d_end,
                ShiftAssignment.personnel_id.in_(pids),
            )
            .all()
        )

    return {
        "start": d_start.isoformat(),
        "end": d_end.isoformat(),
        "departments": departments,
        "shifts": [_shift_brief(s) for s in shifts],
        "personnel": [
            {
                "id": p.id, "full_name": p.full_name, "employee_code": p.employee_code,
                "department": p.department, "title": p.title,
            }
            for p in personnel
        ],
        "assignments": [_assignment_dict(a) for a in assignments],
    }


@router.post("/shift-schedule", status_code=201)
def assign_cell(
    data: AssignCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Bir personeli bir günde bir vardiyaya ata (upsert). Onay akışına tabi."""
    # Varlık doğrulaması (404) — check_approval'dan ÖNCE
    person = db.query(Personnel).filter(Personnel.id == data.personnel_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    shift = db.query(ShiftDefinition).filter(ShiftDefinition.id == data.shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="Vardiya bulunamadı")

    approval_resp = check_approval(db, MODULE_CODE, 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    a = hr_service.upsert_assignment(db, data.personnel_id, data.shift_id, data.work_date, data.note, current_user.id)
    log_action(
        db, current_user.id, "create", "shift_assignment", a.id,
        f"Rota: {person.full_name} → {shift.name} ({data.work_date.isoformat()})",
        get_client_ip(request),
    )
    db.commit()
    db.refresh(a)
    _broadcast("assign")
    return _assignment_dict(a)


@router.delete("/shift-schedule/{assignment_id}")
def remove_cell(
    assignment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Bir rota hücresini sil (personeli o günkü vardiyadan çıkar). Onay akışına tabi."""
    a = db.query(ShiftAssignment).filter(ShiftAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Atama bulunamadı")

    approval_resp = check_approval(db, MODULE_CODE, a.id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    log_action(
        db, current_user.id, "delete", "shift_assignment", a.id,
        f"Rota silindi (personel #{a.personnel_id}, {a.work_date.isoformat()})",
        get_client_ip(request),
    )
    hr_service.delete_assignment(db, a)
    db.commit()
    _broadcast("remove")
    return {"ok": True}


@router.post("/shift-schedule/bulk")
def bulk_assign(
    data: BulkAssign,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Toplu atama/temizleme (onay akışından muaf — toplu işlem).

    shift_id verilirse seçili personel×tarih hücrelerine atar; None ise temizler (siler).
    """
    if not data.personnel_ids or not data.dates:
        raise HTTPException(status_code=400, detail="En az bir personel ve bir tarih seçilmeli")
    if len(set(data.personnel_ids)) * len(set(data.dates)) > MAX_BULK_CELLS:
        raise HTTPException(status_code=400, detail=f"Toplu işlem en fazla {MAX_BULK_CELLS} hücre olabilir")

    if data.shift_id is not None:
        shift = db.query(ShiftDefinition).filter(ShiftDefinition.id == data.shift_id).first()
        if not shift:
            raise HTTPException(status_code=404, detail="Vardiya bulunamadı")

    valid_ids = {pid for (pid,) in db.query(Personnel.id).filter(Personnel.id.in_(data.personnel_ids)).all()}
    if not valid_ids:
        raise HTTPException(status_code=404, detail="Geçerli personel bulunamadı")
    dates = list({d for d in data.dates})

    count = 0
    if data.shift_id is None:
        count = (
            db.query(ShiftAssignment)
            .filter(
                ShiftAssignment.personnel_id.in_(valid_ids),
                ShiftAssignment.work_date.in_(dates),
            )
            .delete(synchronize_session=False)
        )
        detail = f"Rota temizlendi: {count} hücre"
    else:
        existing = (
            db.query(ShiftAssignment)
            .filter(
                ShiftAssignment.personnel_id.in_(valid_ids),
                ShiftAssignment.work_date.in_(dates),
            )
            .all()
        )
        emap = {(a.personnel_id, a.work_date): a for a in existing}
        now = _now_tz()
        for pid in valid_ids:
            for d in dates:
                a = emap.get((pid, d))
                if a:
                    a.shift_id = data.shift_id
                    if data.note is not None:
                        a.note = data.note or None
                    a.updated_at = now
                else:
                    db.add(ShiftAssignment(
                        personnel_id=pid, shift_id=data.shift_id, work_date=d,
                        note=(data.note or None), created_by=current_user.id,
                    ))
                count += 1
        detail = f"Rota toplu atama (vardiya #{data.shift_id}): {count} hücre"

    log_action(db, current_user.id, "bulk", "shift_assignment", 0, detail, get_client_ip(request))
    db.commit()
    _broadcast("bulk")
    return {"ok": True, "count": count}


@router.post("/shift-schedule/copy-week")
def copy_week(
    data: CopyWeek,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Kaynak haftadaki (7 gün) atamaları hedef haftaya kopyala (onay akışından muaf)."""
    offset = (data.target_start - data.source_start).days
    if offset == 0:
        raise HTTPException(status_code=400, detail="Kaynak ve hedef hafta aynı olamaz")

    src_end = data.source_start + timedelta(days=6)
    q = db.query(ShiftAssignment).filter(
        ShiftAssignment.work_date >= data.source_start,
        ShiftAssignment.work_date <= src_end,
    )
    if data.personnel_ids:
        q = q.filter(ShiftAssignment.personnel_id.in_(data.personnel_ids))
    src = q.all()
    if not src:
        return {"ok": True, "count": 0}

    targets = [(a.personnel_id, a.work_date + timedelta(days=offset), a.shift_id, a.note) for a in src]
    tpids = list({t[0] for t in targets})
    tdates = list({t[1] for t in targets})
    existing = (
        db.query(ShiftAssignment)
        .filter(ShiftAssignment.personnel_id.in_(tpids), ShiftAssignment.work_date.in_(tdates))
        .all()
    )
    emap = {(a.personnel_id, a.work_date): a for a in existing}
    now = _now_tz()
    count = 0
    for pid, wd, sid, note in targets:
        a = emap.get((pid, wd))
        if a:
            a.shift_id = sid
            a.note = note
            a.updated_at = now
        else:
            new = ShiftAssignment(personnel_id=pid, shift_id=sid, work_date=wd, note=note, created_by=current_user.id)
            db.add(new)
            emap[(pid, wd)] = new
        count += 1

    log_action(
        db, current_user.id, "bulk", "shift_assignment", 0,
        f"Hafta kopyalandı ({offset:+d}g): {count} hücre", get_client_ip(request),
    )
    db.commit()
    _broadcast("bulk")
    return {"ok": True, "count": count}
