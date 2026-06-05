"""PDKS cihaz bağlama (anti-buddy-punch) testleri.

access_token yalnızca enrollment; basış kimliği cihaza özel device_token'dır.
Kopyalanan kişisel link başka cihazda basış yapamaz (X-Pdks-Token artık kimlik vermez).
Tek aktif cihaz: zaten bağlıysa 409 → admin reset → yeniden bağlanır.
"""
import uuid

from app.models.personnel import Personnel


def _mk(db) -> Personnel:
    p = Personnel(
        full_name="Cihaz Test",
        employee_code=f"DEV-{uuid.uuid4().hex[:6]}",
        access_token=f"ENR-{uuid.uuid4().hex}",
        is_active=True,
    )
    db.add(p)
    db.flush()
    return p


def test_enroll_binds_device_and_blocks_copy(client, db):
    p = _mk(db)
    # 1) ilk kurulum → device_token döner
    r = client.post("/api/attendance/setup", json={"token": p.access_token})
    assert r.status_code == 200, r.text
    dt = r.json().get("device_token")
    assert dt
    # 2) ikinci cihaz aynı kartla → 409 (tek aktif cihaz)
    assert client.post("/api/attendance/setup", json={"token": p.access_token}).status_code == 409
    # 3) doğru cihaz token'ı ile kimlik → 200
    r3 = client.get("/api/attendance/me", headers={"X-Pdks-Device": dt})
    assert r3.status_code == 200 and r3.json()["full_name"] == "Cihaz Test"
    # 4) yanlış cihaz token'ı → 401
    assert client.get("/api/attendance/me", headers={"X-Pdks-Device": "yanlis"}).status_code == 401
    # 5) KRİTİK: eski access_token (kopyalanan URL) artık kimlik VERMEZ → 401
    assert client.get("/api/attendance/me", headers={"X-Pdks-Token": p.access_token}).status_code == 401


def test_admin_reset_allows_rebind(client, db, auth_headers):
    p = _mk(db)
    assert client.post("/api/attendance/setup", json={"token": p.access_token}).status_code == 200
    # zaten bağlı
    assert client.post("/api/attendance/setup", json={"token": p.access_token}).status_code == 409
    # admin cihaz sıfırla
    assert client.post(f"/api/attendance/personnel/{p.id}/reset-device", headers=auth_headers).status_code == 200
    # sıfırlama sonrası yeniden bağlanır
    r = client.post("/api/attendance/setup", json={"token": p.access_token})
    assert r.status_code == 200 and r.json().get("device_token")


def test_reset_device_requires_use_permission(client, db, viewer_user_headers):
    p = _mk(db)
    r = client.post(f"/api/attendance/personnel/{p.id}/reset-device", headers=viewer_user_headers)
    assert r.status_code == 403


def test_reset_device_404(client, auth_headers):
    assert client.post("/api/attendance/personnel/999999/reset-device", headers=auth_headers).status_code == 404


def test_personnel_list_exposes_device_status(client, db, auth_headers):
    p = _mk(db)
    r = client.get("/api/attendance/personnel", headers=auth_headers)
    assert r.status_code == 200
    row = next((x for x in r.json()["items"] if x["id"] == p.id), None)
    assert row is not None
    assert row["device_bound"] is False  # henüz bağlanmadı
    assert "device_bound_at" in row
