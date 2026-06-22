"""İK domain servis katmanı — PDKS giriş/çıkış + vardiya tanımı + vardiya çizelgesi mutasyonları (HTTP'siz).

D1-2 (2026-06-22): İK mutasyon mantığı TEK kaynakta. Hem router endpoint'leri
(`attendance/logs.py`, `shifts.py`, `shift_schedule.py`) hem onay executor handler'ları
(`_handle_attendance`, `_handle_shifts`, `_handle_shift_schedule`) AYNI fonksiyonları
çağırır → router↔executor sapması (sessiz bug) yapısal olarak engellenir.

Tasarım sınırı (CLAUDE.md): HTTP doğrulama (404/400/komşu-tip), response, approval,
audit (`log_action`), broadcast/WS → ROUTER'da (ve executor handler'ında) kalır. Service
yalnız mutasyon: kayıt oluştur/güncelle/sil + alan uygulama + edited_at + soft-delete + upsert.

Onay payload'ı JSON'dur (json.dumps default=str) → tarih/saat alanları STRING gelir;
router yolu TYPED (datetime/time/date) verir → service İKİSİNİ de coerce eder.
"""
from datetime import date, datetime, time
from typing import Optional, Tuple

import pytz
from sqlalchemy.orm import Session

from app.models.personnel import SOURCE_MANUAL, AttendanceLog
from app.models.shift import DEFAULT_COLOR, ShiftDefinition
from app.models.shift_assignment import ShiftAssignment

TZ = pytz.timezone("Europe/Istanbul")

# Vardiya tanımı güncellemesinde set edilebilen alanlar (router ile aynı)
SHIFT_UPDATE_FIELDS = (
    "name", "color", "start_time", "end_time", "start_time2", "end_time2",
    "description", "is_active", "sort_order",
)


# ─── Coercion yardımcıları (onay payload string ↔ router typed) ───

def _coerce_datetime(v) -> Optional[datetime]:
    """Onay yolu ISO string ('2026-06-22T08:00:00+03:00'); router yolu datetime objesi.
    İkisini de tz-aware Europe/Istanbul datetime'a normalize et."""
    if v is None:
        return None
    if isinstance(v, str):
        if not v:
            return None
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            return None
    else:
        dt = v
    return TZ.localize(dt) if dt.tzinfo is None else dt


def _coerce_time(v) -> Optional[time]:
    """Onay yolu 'HH:MM[:SS]' string; router yolu time objesi. time'a normalize et."""
    if v is None:
        return None
    if isinstance(v, time):
        return v
    try:
        parts = str(v).split(":")
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def _coerce_date(v) -> Optional[date]:
    """Onay yolu 'YYYY-MM-DD' string; router yolu date objesi. date'e normalize et."""
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


# ─── PDKS giriş/çıkış (hr.attendance) ────────────────────

def create_attendance(db: Session, data: dict, actor_id) -> AttendanceLog:
    """Elle giriş/çıkış kaydı oluştur (yönetici). punched_at typed datetime veya ISO string.

    Not strip + None'a normalize. punched_at verilmezse kolon server_default (şimdi) atar —
    ama router/executor zaten somut zaman geçirir (router localize, executor talep anı)."""
    log = AttendanceLog(
        personnel_id=data.get("personnel_id"),
        type=data.get("type"),
        source=SOURCE_MANUAL,
        recorded_by=actor_id,
        note=(data.get("note") or "").strip() or None,
    )
    when = _coerce_datetime(data.get("punched_at"))
    if when is not None:
        log.punched_at = when
    db.add(log)
    db.flush()
    return log


def apply_attendance_update(
    db: Session, log: AttendanceLog, update_data: dict
) -> Tuple[str, datetime, Optional[str]]:
    """Giriş/çıkış kaydı alanlarını uygula (tip / zaman / not) + edited_at damgala.

    Döner: (old_type, old_when, old_note) → çağıran eski→yeni diff üretebilir
    (router rich audit, executor generic). punched_at typed/ISO ikisini de kabul eder."""
    old_type, old_when, old_note = log.type, log.punched_at, log.note
    if update_data.get("type"):
        log.type = update_data["type"]
    if "note" in update_data:
        log.note = (update_data.get("note") or "").strip() or None
    when = _coerce_datetime(update_data.get("punched_at"))
    if when is not None:
        log.punched_at = when
    log.edited_at = datetime.now(TZ)
    return old_type, old_when, old_note


def delete_attendance(db: Session, log: AttendanceLog) -> None:
    """Giriş/çıkış kaydını soft-delete et (kayıt kalır, deleted_at set edilir)."""
    log.deleted_at = datetime.now(TZ)


# ─── Vardiya tanımları (hr.shifts) ───────────────────────

def create_shift(db: Session, data: dict, actor_id) -> ShiftDefinition:
    """Vardiya tanımı oluştur. start/end_time typed time veya 'HH:MM' string."""
    is_active = data.get("is_active")
    s = ShiftDefinition(
        name=(data.get("name") or "").strip(),
        color=data.get("color") or DEFAULT_COLOR,
        start_time=_coerce_time(data.get("start_time")),
        end_time=_coerce_time(data.get("end_time")),
        start_time2=_coerce_time(data.get("start_time2")),
        end_time2=_coerce_time(data.get("end_time2")),
        description=(data.get("description") or "").strip() or None,
        is_active=True if is_active is None else is_active,
        sort_order=data.get("sort_order") or 0,
    )
    db.add(s)
    db.flush()
    return s


def apply_shift_update(db: Session, s: ShiftDefinition, update_data: dict) -> None:
    """Vardiya tanımı alanlarını uygula. time alanları typed/'HH:MM' ikisini de kabul eder."""
    for f in SHIFT_UPDATE_FIELDS:
        if f not in update_data:
            continue
        v = update_data[f]
        if f in ("start_time", "end_time", "start_time2", "end_time2"):
            setattr(s, f, _coerce_time(v))
        elif f == "description":
            s.description = v or None
        else:
            setattr(s, f, v)


def delete_shift(db: Session, s: ShiftDefinition) -> None:
    """Vardiya tanımını sil (hard delete — CASCADE atamaları da siler)."""
    db.delete(s)


# ─── Vardiya çizelgesi / rota (hr.shift_schedule) ────────

def upsert_assignment(
    db: Session, personnel_id, shift_id, work_date, note, actor_id
) -> ShiftAssignment:
    """Bir rota hücresini oluştur veya güncelle (personnel_id + work_date benzersiz).

    work_date typed date veya 'YYYY-MM-DD' string olabilir → date'e coerce edilir."""
    wd = _coerce_date(work_date)
    a = (
        db.query(ShiftAssignment)
        .filter(
            ShiftAssignment.personnel_id == personnel_id,
            ShiftAssignment.work_date == wd,
        )
        .first()
    )
    if a:
        a.shift_id = shift_id
        if note is not None:
            a.note = note or None
        a.updated_at = datetime.now(TZ)
    else:
        a = ShiftAssignment(
            personnel_id=personnel_id,
            shift_id=shift_id,
            work_date=wd,
            note=(note or None),
            created_by=actor_id,
        )
        db.add(a)
    db.flush()
    return a


def delete_assignment(db: Session, a: ShiftAssignment) -> None:
    """Bir rota hücresini sil."""
    db.delete(a)
