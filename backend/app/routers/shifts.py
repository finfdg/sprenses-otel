"""Vardiya tanımları (hr.shifts) — CRUD + süre hesabı + onay akışı.

Normal vardiya start→end; gece vardiyası gece yarısını geçebilir (end<=start → ertesi gün).
Split vardiya için ikinci segment (start_time2/end_time2). Süre dk olarak hesaplanır.
"""
from datetime import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.shift import ShiftDefinition
from app.models.user import User
from app.services import hr_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action

router = APIRouter()


# ─── Yardımcılar ─────────────────────────────────────────

def _seg_minutes(s: time, e: time) -> int:
    sm = s.hour * 60 + s.minute
    em = e.hour * 60 + e.minute
    if em <= sm:
        em += 24 * 60  # gece yarısını geçer
    return em - sm


def _total_minutes(s: ShiftDefinition) -> int:
    total = _seg_minutes(s.start_time, s.end_time)
    if s.start_time2 and s.end_time2:
        total += _seg_minutes(s.start_time2, s.end_time2)
    return total


def _hm(t: Optional[time]) -> Optional[str]:
    return t.strftime("%H:%M") if t else None


def _shift_dict(s: ShiftDefinition) -> dict:
    mins = _total_minutes(s)
    return {
        "id": s.id, "name": s.name, "color": s.color,
        "start_time": _hm(s.start_time), "end_time": _hm(s.end_time),
        "start_time2": _hm(s.start_time2), "end_time2": _hm(s.end_time2),
        "is_split": bool(s.start_time2 and s.end_time2),
        "crosses_midnight": s.end_time <= s.start_time,
        "duration_minutes": mins,
        "duration_hours": round(mins / 60, 1),
        "description": s.description, "is_active": s.is_active, "sort_order": s.sort_order,
    }


# ─── Şemalar ─────────────────────────────────────────────

class ShiftCreate(BaseModel):
    name: str
    color: Optional[str] = None
    start_time: time
    end_time: time
    start_time2: Optional[time] = None
    end_time2: Optional[time] = None
    description: Optional[str] = None
    is_active: Optional[bool] = True
    sort_order: Optional[int] = 0


class ShiftUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    start_time2: Optional[time] = None
    end_time2: Optional[time] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


# ─── Endpoint'ler ────────────────────────────────────────

@router.get("/shifts")
def list_shifts(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.shifts", "view")),
):
    rows = (
        db.query(ShiftDefinition)
        .order_by(ShiftDefinition.sort_order, ShiftDefinition.start_time)
        .all()
    )
    return {"items": [_shift_dict(s) for s in rows]}


@router.post("/shifts", status_code=201)
def create_shift(
    data: ShiftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.shifts", "use")),
):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Vardiya adı zorunlu")
    approval_resp = check_approval(db, "hr.shifts", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp
    s = hr_service.create_shift(db, data.model_dump(), current_user.id)
    log_action(db, current_user.id, "create", "shift", s.id, f"Vardiya: {s.name}", get_client_ip(request))
    db.commit()
    db.refresh(s)
    return _shift_dict(s)


@router.patch("/shifts/{sid}")
def update_shift(
    sid: int,
    data: ShiftUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.shifts", "use")),
):
    s = db.query(ShiftDefinition).filter(ShiftDefinition.id == sid).first()
    if not s:
        raise HTTPException(status_code=404, detail="Vardiya bulunamadı")
    payload = data.model_dump(exclude_unset=True)
    approval_resp = check_approval(db, "hr.shifts", s.id, current_user.id, "update", payload)
    if approval_resp:
        return approval_resp
    hr_service.apply_shift_update(db, s, payload)
    log_action(db, current_user.id, "update", "shift", s.id, f"Vardiya güncellendi: {s.name}", get_client_ip(request))
    db.commit()
    db.refresh(s)
    return _shift_dict(s)


@router.delete("/shifts/{sid}")
def delete_shift(
    sid: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.shifts", "use")),
):
    s = db.query(ShiftDefinition).filter(ShiftDefinition.id == sid).first()
    if not s:
        raise HTTPException(status_code=404, detail="Vardiya bulunamadı")
    approval_resp = check_approval(db, "hr.shifts", s.id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp
    log_action(db, current_user.id, "delete", "shift", s.id, f"Vardiya silindi: {s.name}", get_client_ip(request))
    hr_service.delete_shift(db, s)
    db.commit()
    return {"ok": True}
