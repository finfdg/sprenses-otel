"""Personel Devam Takip (PDKS) — kiosk dönen QR, telefon basışı, yönetici paneli.

Akış:
- Girişteki ekran `/devam/ekran?key=KIOSK_KEY` → `GET /attendance/kiosk/qr` ile
  her ~10sn'de dönen QR gösterir. QR, `PUBLIC/devam?k=<token>` URL'ini taşır.
- Personel telefonun YERLEŞİK kamerasıyla QR'ı okutur → URL açılır → kimlik çerezi
  (pdks_token) + k token doğrulanır → giriş/çıkış kaydedilir.
- Personel kimliği: kişisel `access_token` (kurulum linki bir kez açılınca çerez olur).

Güvenlik:
- Dönen token HMAC(SECRET, window) — 15sn'de değişir, ~30sn geçerli. Evden basma:
  kiosk QR endpoint'i KIOSK_KEY ister (admin-only) → token uzaktan çekilemez.
- Tek kullanım yerine personel-bazlı debounce (çift basışı engeller).
- Yönetici işlemleri require_permission(hr.attendance); kiosk/setup/punch public.
- Bu modül onay akışından muaftır (Sunucu/Yedekleme gibi ops modülü).
"""
import hashlib
import hmac
import io
import math
import secrets
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

import pytz
import segno
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import RateLimiter, get_client_ip
from app.models.personnel import (
    SOURCE_MANUAL,
    SOURCE_PHONE,
    TYPE_IN,
    TYPE_OUT,
    AttendanceLog,
    Personnel,
)
from app.models.user import User
from app.utils.audit import log_action

TZ = pytz.timezone("Europe/Istanbul")
SECRET = settings.secret_key.encode()
PUBLIC_BASE = settings.cors_origins.split(",")[0].strip().rstrip("/")
# Kiosk ekranını yetkilendiren stabil, admin-only anahtar (SECRET'ten türetilir)
KIOSK_KEY = hmac.new(SECRET, b"pdks-kiosk-key", hashlib.sha256).hexdigest()[:24]

WINDOW_SEC = 15            # token bu saniyede bir döner
TOKEN_VALID_WINDOWS = 2    # current + previous → ~30sn geçerlilik
PUNCH_DEBOUNCE_SEC = 30    # aynı personel bu sürede tekrar basamaz
COOKIE_NAME = "pdks_token"

punch_limiter = RateLimiter(max_requests=40, window_seconds=60)

router = APIRouter()


# ─── Dönen token yardımcıları ────────────────────────────

def _window(t: Optional[float] = None) -> int:
    return int((t if t is not None else time.time()) // WINDOW_SEC)


def _sign(w: int) -> str:
    return hmac.new(SECRET, f"pdks:{w}".encode(), hashlib.sha256).hexdigest()[:16]


def _make_token() -> str:
    w = _window()
    return f"{w}.{_sign(w)}"


def _valid_token(token: str) -> bool:
    try:
        w_str, sig = token.split(".", 1)
        w = int(w_str)
    except (ValueError, AttributeError):
        return False
    cur = _window()
    if w > cur or w < cur - (TOKEN_VALID_WINDOWS - 1):
        return False
    return hmac.compare_digest(sig, _sign(w))


def _set_cookie(response: Response, token: str) -> None:
    is_secure = "https" in settings.cors_origins
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=60 * 60 * 24 * 365, httponly=True, secure=is_secure, samesite="lax", path="/",
    )


def _personnel_from_cookie(request: Request, db: Session) -> Optional[Personnel]:
    tok = request.cookies.get(COOKIE_NAME)
    if not tok:
        return None
    return db.query(Personnel).filter(
        Personnel.access_token == tok, Personnel.is_active.is_(True)
    ).first()


def _last_log(db: Session, personnel_id: int) -> Optional[AttendanceLog]:
    return (
        db.query(AttendanceLog)
        .filter(AttendanceLog.personnel_id == personnel_id)
        .order_by(desc(AttendanceLog.punched_at))
        .first()
    )


def _today_summary(db: Session, personnel_id: int) -> dict:
    """Bugünkü toplam içeride-süre (dakika) + şu an içeride mi."""
    today = datetime.now(TZ).date()
    start = TZ.localize(datetime.combine(today, datetime.min.time()))
    logs = (
        db.query(AttendanceLog)
        .filter(AttendanceLog.personnel_id == personnel_id, AttendanceLog.punched_at >= start)
        .order_by(AttendanceLog.punched_at)
        .all()
    )
    total = 0.0
    open_in: Optional[datetime] = None
    for lg in logs:
        if lg.type == TYPE_IN:
            open_in = lg.punched_at
        elif lg.type == TYPE_OUT and open_in:
            total += (lg.punched_at - open_in).total_seconds()
            open_in = None
    inside = open_in is not None
    if inside:
        total += (datetime.now(TZ) - open_in).total_seconds()
    return {"minutes_today": round(total / 60), "inside": inside}


def _personnel_dict(p: Personnel) -> dict:
    return {
        "id": p.id, "full_name": p.full_name, "employee_code": p.employee_code,
        "department": p.department, "phone": p.phone, "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _svg_qr(data: str) -> Response:
    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=10, border=2)
    return Response(
        content=buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


# ─── Şemalar ─────────────────────────────────────────────

class PersonnelCreate(BaseModel):
    full_name: str
    employee_code: str
    department: Optional[str] = None
    phone: Optional[str] = None


class PersonnelUpdate(BaseModel):
    full_name: Optional[str] = None
    employee_code: Optional[str] = None
    department: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class SetupRequest(BaseModel):
    token: str


class PunchRequest(BaseModel):
    k: str


class ManualPunch(BaseModel):
    personnel_id: int
    type: str
    punched_at: Optional[datetime] = None
    note: Optional[str] = None


# ═══ PUBLIC — Kiosk ekranı ═══════════════════════════════

@router.get("/attendance/kiosk/qr")
def kiosk_qr(key: str = Query(...)):
    """Girişteki ekranın gösterdiği dönen QR (SVG). KIOSK_KEY gerektirir."""
    if not hmac.compare_digest(key, KIOSK_KEY):
        raise HTTPException(status_code=403, detail="Geçersiz kiosk anahtarı")
    url = f"{PUBLIC_BASE}/devam?k={_make_token()}"
    return _svg_qr(url)


# ═══ PUBLIC — Personel kimlik + basış ════════════════════

@router.post("/attendance/setup")
def setup(data: SetupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Kişisel kurulum linki → kimlik çerezi (pdks_token) set et."""
    punch_limiter.check(f"pdks-setup-{get_client_ip(request)}")
    p = db.query(Personnel).filter(
        Personnel.access_token == data.token.strip(), Personnel.is_active.is_(True)
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Geçersiz veya pasif personel linki")
    _set_cookie(response, p.access_token)
    return {"ok": True, "full_name": p.full_name, "employee_code": p.employee_code}


@router.get("/attendance/me")
def me(request: Request, db: Session = Depends(get_db)):
    """Çerezdeki personelin bilgisi + bugünkü durumu."""
    p = _personnel_from_cookie(request, db)
    if not p:
        raise HTTPException(status_code=401, detail="Personel tanımlı değil — kurulum linkini açın")
    summary = _today_summary(db, p.id)
    last = _last_log(db, p.id)
    return {
        "full_name": p.full_name, "employee_code": p.employee_code, "department": p.department,
        "inside": summary["inside"], "minutes_today": summary["minutes_today"],
        "last_punch": last.punched_at.isoformat() if last else None,
        "last_type": last.type if last else None,
    }


@router.post("/attendance/punch")
def punch(data: PunchRequest, request: Request, db: Session = Depends(get_db)):
    """Kiosk QR'ı okutunca çağrılır — token doğrula, giriş/çıkış kaydet."""
    punch_limiter.check(f"pdks-punch-{get_client_ip(request)}")
    p = _personnel_from_cookie(request, db)
    if not p:
        raise HTTPException(status_code=401, detail="Personel tanımlı değil — kurulum linkini açın")
    if not _valid_token(data.k):
        raise HTTPException(status_code=400, detail="Karekod süresi doldu — ekrandaki güncel kodu tekrar okutun")

    now = datetime.now(TZ)
    last = _last_log(db, p.id)
    if last and (now - last.punched_at).total_seconds() < PUNCH_DEBOUNCE_SEC:
        raise HTTPException(status_code=429, detail="Çok hızlı — birkaç saniye sonra tekrar deneyin")

    new_type = TYPE_OUT if (last and last.type == TYPE_IN) else TYPE_IN
    lg = AttendanceLog(personnel_id=p.id, type=new_type, source=SOURCE_PHONE)
    db.add(lg)
    db.commit()

    summary = _today_summary(db, p.id)
    return {
        "ok": True,
        "type": new_type,
        "full_name": p.full_name,
        "time": now.strftime("%H:%M"),
        "minutes_today": summary["minutes_today"],
        "message": f"{'Giriş' if new_type == TYPE_IN else 'Çıkış'} yapıldı — hoş geldin {p.full_name.split()[0]}!"
        if new_type == TYPE_IN else f"Çıkış yapıldı — iyi günler {p.full_name.split()[0]}!",
    }


# ═══ YÖNETİCİ — Personel yönetimi ════════════════════════

@router.get("/attendance/personnel")
def list_personnel(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(True),
):
    q = db.query(Personnel)
    if not include_inactive:
        q = q.filter(Personnel.is_active.is_(True))
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((Personnel.full_name.ilike(like)) | (Personnel.employee_code.ilike(like)))
    total = q.count()
    items = q.order_by(Personnel.full_name).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [_personnel_dict(p) for p in items],
        "total": total, "page": page, "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 1,
    }


@router.post("/attendance/personnel", status_code=201)
def create_personnel(
    data: PersonnelCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    code = data.employee_code.strip()
    if db.query(Personnel).filter(Personnel.employee_code == code).first():
        raise HTTPException(status_code=400, detail="Bu sicil no zaten kayıtlı")
    p = Personnel(
        full_name=data.full_name.strip(),
        employee_code=code,
        department=(data.department or "").strip() or None,
        phone=(data.phone or "").strip() or None,
        access_token=secrets.token_urlsafe(24),
    )
    db.add(p)
    db.flush()
    log_action(db, current_user.id, "create", "personnel", p.id,
               f"Personel: {p.full_name} ({p.employee_code})", get_client_ip(request))
    db.commit()
    db.refresh(p)
    return _personnel_dict(p)


@router.patch("/attendance/personnel/{pid}")
def update_personnel(
    pid: int,
    data: PersonnelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    p = db.query(Personnel).filter(Personnel.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    payload = data.model_dump(exclude_unset=True)
    if "employee_code" in payload and payload["employee_code"]:
        code = payload["employee_code"].strip()
        clash = db.query(Personnel).filter(Personnel.employee_code == code, Personnel.id != pid).first()
        if clash:
            raise HTTPException(status_code=400, detail="Bu sicil no başka personelde")
        p.employee_code = code
    for f in ("full_name", "department", "phone", "is_active"):
        if f in payload:
            setattr(p, f, payload[f])
    log_action(db, current_user.id, "update", "personnel", p.id,
               f"Personel güncellendi: {p.full_name}", get_client_ip(request))
    db.commit()
    db.refresh(p)
    return _personnel_dict(p)


@router.delete("/attendance/personnel/{pid}")
def delete_personnel(
    pid: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    p = db.query(Personnel).filter(Personnel.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    log_action(db, current_user.id, "delete", "personnel", p.id,
               f"Personel silindi: {p.full_name} ({p.employee_code})", get_client_ip(request))
    db.delete(p)  # CASCADE logları siler
    db.commit()
    return {"detail": "Personel silindi"}


@router.get("/attendance/personnel/{pid}/qr")
def personnel_setup_qr(
    pid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
):
    """Personelin kişisel kurulum linkinin QR'ı (kart basmak için)."""
    p = db.query(Personnel).filter(Personnel.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    return _svg_qr(f"{PUBLIC_BASE}/devam/kur?t={p.access_token}")


# ═══ YÖNETİCİ — İzleme + raporlar ════════════════════════

@router.get("/attendance/kiosk-link")
def kiosk_link(_: User = Depends(require_permission("hr.attendance", "view"))):
    """Giriş ekranı için açılacak link (KIOSK_KEY dahil) — admin cihaza kurar."""
    return {"url": f"{PUBLIC_BASE}/devam/ekran?key={KIOSK_KEY}"}


@router.get("/attendance/status")
def who_is_inside(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
):
    """Şu an içeride olan personeller (son basışı 'in' olanlar)."""
    # Her personelin son log'u
    sub = (
        db.query(AttendanceLog.personnel_id, func.max(AttendanceLog.punched_at).label("mx"))
        .group_by(AttendanceLog.personnel_id)
        .subquery()
    )
    rows = (
        db.query(AttendanceLog, Personnel)
        .join(sub, (AttendanceLog.personnel_id == sub.c.personnel_id) & (AttendanceLog.punched_at == sub.c.mx))
        .join(Personnel, Personnel.id == AttendanceLog.personnel_id)
        .filter(AttendanceLog.type == TYPE_IN)
        .order_by(desc(AttendanceLog.punched_at))
        .all()
    )
    inside = [{
        "personnel_id": p.id, "full_name": p.full_name, "department": p.department,
        "since": lg.punched_at.isoformat(),
    } for lg, p in rows]
    return {"inside_count": len(inside), "inside": inside}


@router.get("/attendance/logs")
def list_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
    personnel_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    q = db.query(AttendanceLog, Personnel).join(Personnel, Personnel.id == AttendanceLog.personnel_id)
    if personnel_id:
        q = q.filter(AttendanceLog.personnel_id == personnel_id)
    if start_date:
        q = q.filter(AttendanceLog.punched_at >= TZ.localize(datetime.combine(start_date, datetime.min.time())))
    if end_date:
        q = q.filter(AttendanceLog.punched_at < TZ.localize(datetime.combine(end_date + timedelta(days=1), datetime.min.time())))
    total = q.count()
    rows = q.order_by(desc(AttendanceLog.punched_at)).offset((page - 1) * page_size).limit(page_size).all()
    items = [{
        "id": lg.id, "personnel_id": p.id, "full_name": p.full_name, "department": p.department,
        "type": lg.type, "punched_at": lg.punched_at.isoformat(), "source": lg.source,
        "note": lg.note,
    } for lg, p in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 1}


@router.get("/attendance/summary")
def monthly_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
    month: Optional[str] = Query(None),  # YYYY-MM
):
    """Aylık puantaj — personel başına toplam içeride-süre (dakika) + gün sayısı."""
    now = datetime.now(TZ)
    if month:
        try:
            y, m = map(int, month.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="month formatı YYYY-MM olmalı")
    else:
        y, m = now.year, now.month
    start = TZ.localize(datetime(y, m, 1))
    end = TZ.localize(datetime(y + (m // 12), (m % 12) + 1, 1))

    logs = (
        db.query(AttendanceLog, Personnel)
        .join(Personnel, Personnel.id == AttendanceLog.personnel_id)
        .filter(AttendanceLog.punched_at >= start, AttendanceLog.punched_at < end)
        .order_by(AttendanceLog.personnel_id, AttendanceLog.punched_at)
        .all()
    )
    # Personel başına in→out eşle
    by_p: dict = {}
    for lg, p in logs:
        d = by_p.setdefault(p.id, {"full_name": p.full_name, "department": p.department,
                                    "minutes": 0.0, "days": set(), "open_in": None})
        if lg.type == TYPE_IN:
            d["open_in"] = lg.punched_at
        elif lg.type == TYPE_OUT and d["open_in"]:
            d["minutes"] += (lg.punched_at - d["open_in"]).total_seconds() / 60
            d["days"].add(lg.punched_at.date())
            d["open_in"] = None
    result = [{
        "personnel_id": pid, "full_name": v["full_name"], "department": v["department"],
        "total_minutes": round(v["minutes"]), "total_hours": round(v["minutes"] / 60, 1),
        "days_worked": len(v["days"]),
    } for pid, v in by_p.items()]
    result.sort(key=lambda r: r["full_name"])
    return {"month": f"{y:04d}-{m:02d}", "personnel": result}


@router.post("/attendance/manual", status_code=201)
def manual_punch(
    data: ManualPunch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """Yönetici elle giriş/çıkış kaydı (telefonu olmayan / unutulan için)."""
    if data.type not in (TYPE_IN, TYPE_OUT):
        raise HTTPException(status_code=400, detail="type 'in' veya 'out' olmalı")
    p = db.query(Personnel).filter(Personnel.id == data.personnel_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    when = data.punched_at or datetime.now(TZ)
    lg = AttendanceLog(
        personnel_id=p.id, type=data.type, source=SOURCE_MANUAL,
        recorded_by=current_user.id, note=(data.note or "").strip() or None,
        punched_at=when,
    )
    db.add(lg)
    log_action(db, current_user.id, "manual_punch", "attendance", p.id,
               f"Elle {data.type}: {p.full_name}", get_client_ip(request))
    db.commit()
    return {"ok": True, "type": data.type, "personnel": p.full_name}
