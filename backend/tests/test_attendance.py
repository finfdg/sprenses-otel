"""Devam Takip (hr.attendance) ana akışı — personel CRUD + basış + elle giriş + log + puantaj.

Cihaz-bağlama (anti-buddy-punch) ayrı `test_attendance_device.py`'de test edilir; burada onu
TEKRARLAMADAN ana iş akışı kapsanır:
- Personel oluştur → enrollment (setup) → device_token → punch (giriş + çıkış)
- Çift basış engeli (debounce + alternation)
- Yönetici elle giriş (manual) + zaman seçimli + çift engeli
- Kayıt düzenle (PATCH) + sil (soft delete)
- Aylık puantaj (summary)
- İzin geçitleri (403) personnel CRUD + manual

Punch akışı kiosk token (k) gerektirir: token = HMAC(SECRET, "pdks:<ts>") — test ortamında
`_make_token()` ile üretilebilir, gerçek bir basış uçtan uca doğrulanır (atlanmaz).
"""
import uuid
from datetime import datetime, timedelta

import pytz

from app.models.personnel import TYPE_IN, TYPE_OUT, AttendanceLog, Personnel
from app.routers.attendance.kiosk import _make_token

PREFIX = "/api/attendance"
TZ = pytz.timezone("Europe/Istanbul")


# ─── Yardımcılar ─────────────────────────────────────────

def _mk_personnel(db, dept="Mutfak") -> Personnel:
    p = Personnel(
        full_name="Akış Test",
        employee_code=f"AT-{uuid.uuid4().hex[:6]}",
        department=dept,
        title="Aşçı",
        access_token=f"ENR-{uuid.uuid4().hex}",
        is_active=True,
    )
    db.add(p)
    db.flush()
    return p


def _enroll(client, p: Personnel) -> str:
    """Personeli bir cihaza bağla, device_token döndür."""
    r = client.post(f"{PREFIX}/setup", json={"token": p.access_token})
    assert r.status_code == 200, r.text
    dt = r.json().get("device_token")
    assert dt
    return dt


# ─── Personel CRUD (yönetici) ────────────────────────────

def test_create_personnel(client, auth_headers):
    code = f"P-{uuid.uuid4().hex[:6]}"
    r = client.post(f"{PREFIX}/personnel", json={
        "full_name": "Yeni Personel", "employee_code": code, "department": "Resepsiyon", "title": "Görevli",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["full_name"] == "Yeni Personel"
    assert body["employee_code"] == code
    assert body["department"] == "Resepsiyon"
    assert body["device_bound"] is False


def test_create_personnel_duplicate_code(client, auth_headers, db):
    p = _mk_personnel(db)
    db.commit()
    r = client.post(f"{PREFIX}/personnel", json={
        "full_name": "Kopya", "employee_code": p.employee_code,
    }, headers=auth_headers)
    assert r.status_code == 400


def test_update_and_delete_personnel(client, auth_headers, db):
    p = _mk_personnel(db)
    db.commit()
    pid = p.id
    r = client.patch(f"{PREFIX}/personnel/{pid}", json={"full_name": "Düzenlendi", "title": "Şef"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Düzenlendi"
    assert r.json()["title"] == "Şef"

    r = client.delete(f"{PREFIX}/personnel/{pid}", headers=auth_headers)
    assert r.status_code == 200
    assert db.query(Personnel).filter(Personnel.id == pid).first() is None


def test_personnel_crud_requires_use(client, viewer_user_headers, no_perm_user_headers, db):
    """Görme-yalnız kullanıcı personel oluşturamaz; izinsiz kullanıcı listeyi göremez."""
    r = client.post(f"{PREFIX}/personnel", json={
        "full_name": "X", "employee_code": f"P-{uuid.uuid4().hex[:6]}",
    }, headers=viewer_user_headers)
    assert r.status_code == 403
    assert client.get(f"{PREFIX}/personnel", headers=no_perm_user_headers).status_code == 403


# ─── Telefon basışı (punch) — uçtan uca ──────────────────

def test_punch_in_then_out(client, db):
    """Kurulum → giriş basışı → (debounce'u atlamak için) çıkış basışı.

    İlk basış 'in', ikinci basış 'out' olmalı (son log tipine göre değişir).
    Debounce 30sn olduğundan ikinci basışı doğrudan DB'ye eski tarihli yazıp simüle ederiz.
    """
    p = _mk_personnel(db)
    db.commit()
    dt = _enroll(client, p)
    hdr = {"X-Pdks-Device": dt}

    # 1) ilk basış → giriş
    r = client.post(f"{PREFIX}/punch", json={"k": _make_token()}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == TYPE_IN

    # 2) debounce penceresini geç (son log'u geriye al) → ikinci basış çıkış olmalı
    last = db.query(AttendanceLog).filter(AttendanceLog.personnel_id == p.id).order_by(AttendanceLog.punched_at.desc()).first()
    last.punched_at = datetime.now(TZ) - timedelta(minutes=5)
    db.commit()

    r = client.post(f"{PREFIX}/punch", json={"k": _make_token()}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == TYPE_OUT


def test_punch_requires_device(client, db):
    """Cihaz token'ı olmadan basış → 401."""
    r = client.post(f"{PREFIX}/punch", json={"k": _make_token()})
    assert r.status_code == 401


def test_punch_invalid_token(client, db):
    """Geçersiz/süresi dolmuş kiosk token'ı ile basış → 400."""
    p = _mk_personnel(db)
    db.commit()
    dt = _enroll(client, p)
    r = client.post(f"{PREFIX}/punch", json={"k": "0.deadbeef"}, headers={"X-Pdks-Device": dt})
    assert r.status_code == 400


def test_punch_debounce(client, db):
    """Aynı personel debounce penceresinde ikinci kez basamaz → 429."""
    p = _mk_personnel(db)
    db.commit()
    dt = _enroll(client, p)
    hdr = {"X-Pdks-Device": dt}
    assert client.post(f"{PREFIX}/punch", json={"k": _make_token()}, headers=hdr).status_code == 200
    # Hemen tekrar → çok hızlı
    assert client.post(f"{PREFIX}/punch", json={"k": _make_token()}, headers=hdr).status_code == 429


# ─── Yönetici elle giriş (manual) ────────────────────────

def test_manual_punch(client, auth_headers, db):
    p = _mk_personnel(db)
    db.commit()
    when = (datetime.now(TZ) - timedelta(hours=2)).isoformat()
    r = client.post(f"{PREFIX}/manual", json={
        "personnel_id": p.id, "type": TYPE_IN, "punched_at": when, "note": "Elle giriş",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["type"] == TYPE_IN
    logs = db.query(AttendanceLog).filter(AttendanceLog.personnel_id == p.id).all()
    assert len(logs) == 1
    assert logs[0].source == "manual"
    assert logs[0].note == "Elle giriş"


def test_manual_punch_alternation_block(client, auth_headers, db):
    """Art arda aynı tip (giriş→giriş) elle kayıt engellenmeli → 400."""
    p = _mk_personnel(db)
    db.commit()
    base = datetime.now(TZ) - timedelta(hours=3)
    r1 = client.post(f"{PREFIX}/manual", json={
        "personnel_id": p.id, "type": TYPE_IN, "punched_at": base.isoformat(),
    }, headers=auth_headers)
    assert r1.status_code == 201, r1.text
    # ikinci kez giriş (komşu aynı tip) → 400
    r2 = client.post(f"{PREFIX}/manual", json={
        "personnel_id": p.id, "type": TYPE_IN, "punched_at": (base + timedelta(hours=1)).isoformat(),
    }, headers=auth_headers)
    assert r2.status_code == 400


def test_manual_punch_invalid_type(client, auth_headers, db):
    p = _mk_personnel(db)
    db.commit()
    r = client.post(f"{PREFIX}/manual", json={"personnel_id": p.id, "type": "xyz"}, headers=auth_headers)
    assert r.status_code == 400


def test_manual_punch_404(client, auth_headers):
    r = client.post(f"{PREFIX}/manual", json={"personnel_id": 999999, "type": TYPE_IN}, headers=auth_headers)
    assert r.status_code == 404


def test_manual_punch_requires_use(client, viewer_user_headers, db):
    p = _mk_personnel(db)
    db.commit()
    r = client.post(f"{PREFIX}/manual", json={"personnel_id": p.id, "type": TYPE_IN}, headers=viewer_user_headers)
    assert r.status_code == 403


# ─── Kayıt düzenle / sil ─────────────────────────────────

def test_update_log(client, auth_headers, db):
    p = _mk_personnel(db)
    when = datetime.now(TZ) - timedelta(hours=4)
    lg = AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual", punched_at=when)
    db.add(lg)
    db.commit()
    lg_id = lg.id

    new_when = (when + timedelta(minutes=30)).isoformat()
    r = client.patch(f"{PREFIX}/logs/{lg_id}", json={"note": "Düzeltildi", "punched_at": new_when}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "Düzeltildi"
    db.expire_all()
    assert db.get(AttendanceLog, lg_id).edited_at is not None


def test_update_log_404(client, auth_headers):
    assert client.patch(f"{PREFIX}/logs/999999", json={"note": "x"}, headers=auth_headers).status_code == 404


def test_delete_log_soft_delete(client, auth_headers, db):
    """Silme soft delete olmalı — kayıt DB'de kalır, deleted_at set edilir."""
    p = _mk_personnel(db)
    lg = AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual",
                       punched_at=datetime.now(TZ) - timedelta(hours=1))
    db.add(lg)
    db.commit()
    lg_id = lg.id

    r = client.delete(f"{PREFIX}/logs/{lg_id}", headers=auth_headers)
    assert r.status_code == 200
    db.expire_all()
    row = db.get(AttendanceLog, lg_id)
    assert row is not None, "soft delete — kayıt silinmemeli"
    assert row.deleted_at is not None

    # zaten silinmiş kaydı tekrar silmek → 400
    assert client.delete(f"{PREFIX}/logs/{lg_id}", headers=auth_headers).status_code == 400


def test_delete_log_requires_use(client, viewer_user_headers, db):
    p = _mk_personnel(db)
    lg = AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual",
                       punched_at=datetime.now(TZ) - timedelta(hours=1))
    db.add(lg)
    db.commit()
    assert client.delete(f"{PREFIX}/logs/{lg.id}", headers=viewer_user_headers).status_code == 403


# ─── Aylık puantaj (summary) ─────────────────────────────

def test_monthly_summary(client, auth_headers, db):
    """Aynı gün giriş→çıkış (2 saat) puantajda doğru toplam dakika vermeli."""
    p = _mk_personnel(db)
    # Bu ayın 15'inde 2 saatlik bir vardiya
    now = datetime.now(TZ)
    in_t = TZ.localize(datetime(now.year, now.month, 15, 9, 0))
    out_t = in_t + timedelta(hours=2)
    db.add_all([
        AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual", punched_at=in_t),
        AttendanceLog(personnel_id=p.id, type=TYPE_OUT, source="manual", punched_at=out_t),
    ])
    db.commit()

    r = client.get(f"{PREFIX}/summary?month={now.year:04d}-{now.month:02d}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["month"] == f"{now.year:04d}-{now.month:02d}"
    row = next((x for x in body["personnel"] if x["personnel_id"] == p.id), None)
    assert row is not None
    assert row["total_minutes"] == 120
    assert row["days_worked"] == 1


def test_summary_bad_month(client, auth_headers):
    assert client.get(f"{PREFIX}/summary?month=bozuk", headers=auth_headers).status_code == 400


def test_summary_requires_view(client, no_perm_user_headers):
    assert client.get(f"{PREFIX}/summary", headers=no_perm_user_headers).status_code == 403


# ─── Loglar listesi + içerideki personel ─────────────────

def test_list_logs(client, auth_headers, db):
    p = _mk_personnel(db)
    db.add(AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual",
                         punched_at=datetime.now(TZ) - timedelta(hours=1)))
    db.commit()
    r = client.get(f"{PREFIX}/logs?personnel_id={p.id}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert {"items", "total", "page", "page_size", "pages"} <= set(body.keys())
    assert body["total"] >= 1


def test_status_who_is_inside(client, auth_headers, db):
    """Son basışı 'in' olan personel 'içeride' listesinde görünmeli."""
    p = _mk_personnel(db)
    db.add(AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual",
                         punched_at=datetime.now(TZ) - timedelta(minutes=10)))
    db.commit()
    r = client.get(f"{PREFIX}/status", headers=auth_headers)
    assert r.status_code == 200
    assert any(x["personnel_id"] == p.id for x in r.json()["inside"])
