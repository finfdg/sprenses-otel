"""Vardiya tanımları (hr.shifts) — CRUD + izin geçitleri + doğrulama + onay regresyonu.

Bu modül daha önce hiç test edilmemişti. Buradaki testler:
- Admin ile mutlu yol CRUD (create/list/update/delete + süre/split/gece hesabı)
- İzin (403): view-only kullanıcı yazma yapamaz, izinsiz kullanıcı görüntüleyemez
- Onay regresyonu: hr.shifts için workflow varsa POST 202 → approver onaylar →
  `_handle_shifts` vardiyayı GERÇEKTEN oluşturur (alanlar doğru set edilmiş)
"""
from uuid import uuid4

from app.models.shift import ShiftDefinition

PREFIX = "/api/hr/shifts"
API = "/api/system/approval"

# Onay regresyonu için onay testlerinin yardımcılarını yeniden kullan.
from tests.test_approval_system import _make_actor, _make_workflow  # noqa: E402


# ─── İzin geçitleri ──────────────────────────────────────

def test_list_requires_view(client, no_perm_user_headers):
    """İzni olmayan kullanıcı vardiya listesini görememeli (403)."""
    r = client.get(PREFIX, headers=no_perm_user_headers)
    assert r.status_code == 403


def test_create_requires_use(client, viewer_user_headers):
    """Yalnız görme izni olan kullanıcı vardiya oluşturamamalı (403)."""
    r = client.post(PREFIX, json={
        "name": "Sabah", "start_time": "07:00", "end_time": "15:00",
    }, headers=viewer_user_headers)
    assert r.status_code == 403


def test_update_delete_require_use(client, viewer_user_headers, auth_headers):
    """Görme-yalnız kullanıcı güncelleme/silme yapamamalı (403)."""
    # Admin bir vardiya oluşturur
    r = client.post(PREFIX, json={
        "name": f"Vardiya {uuid4().hex[:4]}", "start_time": "09:00", "end_time": "17:00",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    assert client.patch(f"{PREFIX}/{sid}", json={"name": "Yeni"}, headers=viewer_user_headers).status_code == 403
    assert client.delete(f"{PREFIX}/{sid}", headers=viewer_user_headers).status_code == 403


def test_view_user_can_list(client, viewer_user_headers, auth_headers):
    """Görme izni olan kullanıcı listeyi çekebilmeli (200)."""
    client.post(PREFIX, json={
        "name": f"Akşam {uuid4().hex[:4]}", "start_time": "15:00", "end_time": "23:00",
    }, headers=auth_headers)
    r = client.get(PREFIX, headers=viewer_user_headers)
    assert r.status_code == 200
    assert "items" in r.json()


# ─── CRUD mutlu yol ──────────────────────────────────────

def test_create_list_update_delete(client, auth_headers, db):
    """Admin ile tam CRUD döngüsü + DB doğrulaması."""
    name = f"Gündüz {uuid4().hex[:5]}"
    r = client.post(PREFIX, json={
        "name": name, "color": "#ff0000", "start_time": "08:00", "end_time": "16:00",
        "description": "Standart gündüz", "sort_order": 3,
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    sid = body["id"]
    assert body["name"] == name
    assert body["color"] == "#ff0000"
    assert body["start_time"] == "08:00" and body["end_time"] == "16:00"
    assert body["duration_hours"] == 8.0
    assert body["is_split"] is False
    assert body["crosses_midnight"] is False

    # list — yeni vardiya görünür
    r = client.get(PREFIX, headers=auth_headers)
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json()["items"])

    # update — ad + saat değiştir
    r = client.patch(f"{PREFIX}/{sid}", json={"name": "Güncellendi", "end_time": "17:00"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Güncellendi"
    assert r.json()["end_time"] == "17:00"
    assert r.json()["duration_hours"] == 9.0

    # delete
    r = client.delete(f"{PREFIX}/{sid}", headers=auth_headers)
    assert r.status_code == 200
    assert db.query(ShiftDefinition).filter(ShiftDefinition.id == sid).first() is None


def test_create_validation_empty_name(client, auth_headers):
    """Boş ad ile vardiya oluşturma 400 vermeli."""
    r = client.post(PREFIX, json={"name": "   ", "start_time": "07:00", "end_time": "15:00"}, headers=auth_headers)
    assert r.status_code == 400


def test_night_shift_crosses_midnight(client, auth_headers):
    """Gece vardiyası (end <= start) gece yarısını geçmeli + süre doğru hesaplanmalı."""
    r = client.post(PREFIX, json={
        "name": f"Gece {uuid4().hex[:4]}", "start_time": "23:00", "end_time": "07:00",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["crosses_midnight"] is True
    assert body["duration_hours"] == 8.0  # 23:00 → 07:00 = 8 saat


def test_split_shift_two_segments(client, auth_headers):
    """Split vardiya (ikinci segment) toplam süreyi iki segmentin toplamı yapmalı."""
    r = client.post(PREFIX, json={
        "name": f"Split {uuid4().hex[:4]}",
        "start_time": "07:00", "end_time": "11:00",
        "start_time2": "18:00", "end_time2": "22:00",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_split"] is True
    assert body["duration_hours"] == 8.0  # 4 + 4 segment


def test_update_404(client, auth_headers):
    assert client.patch(f"{PREFIX}/999999", json={"name": "X"}, headers=auth_headers).status_code == 404


def test_delete_404(client, auth_headers):
    assert client.delete(f"{PREFIX}/999999", headers=auth_headers).status_code == 404


# ─── Onay regresyonu ─────────────────────────────────────

def test_create_shift_via_approval_regression(db):
    """REGRESYON: hr.shifts için onay akışı varsa POST 202 döner, approver onaylayınca
    `_handle_shifts` handler'ı vardiyayı GERÇEKTEN oluşturur.

    Onaydan önce kayıt OLUŞMAMALI; onaydan sonra alanlar (ad/saat/süre) doğru set edilmeli.
    Zaman alanları payload'da "HH:MM:SS" string olarak gelir; handler time'a parse eder.
    """
    _, req_role, req_client = _make_actor(db, {
        "hr.shifts": {"view": True, "use": True},
        "system.approval": {"view": True, "use": False},
    })
    _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
    _make_workflow(db, "hr.shifts", req_role, app_role)

    name = f"Onaylı {uuid4().hex[:6]}"
    resp = req_client.post(PREFIX, json={
        "name": name, "color": "#123456", "start_time": "06:00", "end_time": "14:00",
    })
    assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
    req_id = resp.json()["request_id"]

    # Onaydan önce: vardiya henüz oluşmamalı
    db.expire_all()
    assert db.query(ShiftDefinition).filter(ShiftDefinition.name == name).first() is None

    # Onayla → executor uygular (handler eksik/bozuk olsaydı 500 verirdi)
    ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
    assert ap.status_code == 200, f"_handle_shifts hatası → 500: {ap.text}"

    db.expire_all()
    s = db.query(ShiftDefinition).filter(ShiftDefinition.name == name).first()
    assert s is not None, "Onay sonrası vardiya oluşturulmalıydı"
    assert s.color == "#123456"
    assert s.start_time.strftime("%H:%M") == "06:00"
    assert s.end_time.strftime("%H:%M") == "14:00"
    assert s.is_active is True
