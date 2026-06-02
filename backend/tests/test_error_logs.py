"""Hata logları modülü testleri (system.error_logs)."""
import pytest

from app.models.error_log import ErrorLog


@pytest.fixture(autouse=True)
def _wipe_error_logs(db):
    """Her test başında error_logs tablosunu temizle — temiz başlangıç sağla."""
    db.query(ErrorLog).delete()
    db.flush()
    yield


def _seed_log(db, **overrides):
    """Test için tek bir ErrorLog kaydı oluşturur ve döner."""
    defaults = dict(
        level="ERROR",
        source="app.routers.test",
        message="Test hata mesajı",
        traceback="Traceback (most recent call last):\n  File ...",
        method="GET",
        path="/api/test",
        user_id=None,
        ip_address="127.0.0.1",
    )
    defaults.update(overrides)
    log = ErrorLog(**defaults)
    db.add(log)
    db.flush()
    return log


# ─── Yetki ──────────────────────────────────────────────


def test_list_requires_auth(client):
    """Kimliksiz erişim 401/403 dönmeli."""
    res = client.get("/api/system/error-logs/")
    assert res.status_code in (401, 403)


def test_summary_requires_auth(client):
    """Özet endpoint'i de auth gerektirir."""
    res = client.get("/api/system/error-logs/summary")
    assert res.status_code in (401, 403)


def test_delete_requires_auth(client):
    """Silme endpoint'i auth gerektirir."""
    res = client.delete("/api/system/error-logs/1")
    assert res.status_code in (401, 403)


# ─── Liste ──────────────────────────────────────────────


def test_list_empty(client, auth_headers):
    """Boş tabloda 200 + boş items + pages=1 döner."""
    res = client.get("/api/system/error-logs/", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["pages"] == 1


def test_list_returns_items(client, auth_headers, db):
    """Var olan kayıtlar listede döner."""
    _seed_log(db, level="ERROR", message="Hata 1")
    _seed_log(db, level="WARNING", message="Uyarı 1")
    _seed_log(db, level="CRITICAL", message="Kritik 1")

    res = client.get("/api/system/error-logs/", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    messages = {item["message"] for item in data["items"]}
    assert messages == {"Hata 1", "Uyarı 1", "Kritik 1"}


def test_list_filter_by_level(client, auth_headers, db):
    """level parametresi ile filtreleme."""
    _seed_log(db, level="ERROR", message="hata kaydi")
    _seed_log(db, level="WARNING", message="uyari kaydi")

    res = client.get("/api/system/error-logs/?level=ERROR", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["level"] == "ERROR"


def test_list_filter_by_source(client, auth_headers, db):
    """source parametresi ile ILIKE filtreleme."""
    _seed_log(db, source="app.auth", message="auth hatası")
    _seed_log(db, source="app.finance", message="finans hatası")

    res = client.get("/api/system/error-logs/?source=auth", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert "auth" in data["items"][0]["source"]


def test_list_search_in_message(client, auth_headers, db):
    """search parametresi message alanında ILIKE arar."""
    _seed_log(db, message="Veritabanı bağlantı hatası")
    _seed_log(db, message="Token süresi doldu")

    res = client.get("/api/system/error-logs/?search=Veritabanı", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert "Veritabanı" in data["items"][0]["message"]


def test_list_pagination(client, auth_headers, db):
    """page + page_size pagination çalışır."""
    for i in range(25):
        _seed_log(db, message=f"Kayıt {i}")

    res = client.get("/api/system/error-logs/?page=1&page_size=10", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 25
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["pages"] == 3
    assert len(data["items"]) == 10

    res2 = client.get("/api/system/error-logs/?page=3&page_size=10", headers=auth_headers)
    assert res2.status_code == 200
    assert len(res2.json()["items"]) == 5  # 25 - 20 = 5


def test_list_order_by_created_at_desc(client, auth_headers, db):
    """Sıralama: en yeni kayıt önce gelmeli.

    İki kayıt aynı transaction'da insert edilirse server_default `now()` aynı
    timestamp'i verebilir. Bu yüzden created_at'i manuel olarak ayrı saatlere
    set ederek deterministik sıralama sağlıyoruz.
    """
    from datetime import datetime, timezone, timedelta

    base = datetime.now(timezone.utc) - timedelta(hours=2)
    older = _seed_log(db, message="Eski")
    older.created_at = base
    newer = _seed_log(db, message="Yeni")
    newer.created_at = base + timedelta(hours=1)
    db.flush()

    res = client.get("/api/system/error-logs/", headers=auth_headers)
    assert res.status_code == 200
    items = res.json()["items"]
    # En yeni created_at önce gelmeli
    assert items[0]["id"] == newer.id
    assert items[1]["id"] == older.id


# ─── Özet ───────────────────────────────────────────────


def test_summary_returns_level_counts(client, auth_headers, db):
    """Özet endpoint'i seviye bazlı sayıları döner."""
    _seed_log(db, level="ERROR")
    _seed_log(db, level="ERROR")
    _seed_log(db, level="WARNING")
    _seed_log(db, level="CRITICAL")

    res = client.get("/api/system/error-logs/summary", headers=auth_headers)
    assert res.status_code == 200
    summary = res.json()
    assert summary.get("ERROR") == 2
    assert summary.get("WARNING") == 1
    assert summary.get("CRITICAL") == 1


def test_summary_empty(client, auth_headers):
    """Boş tabloda summary boş dict döner."""
    res = client.get("/api/system/error-logs/summary", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {}


# ─── Silme ──────────────────────────────────────────────


def test_delete_single_log(client, auth_headers, db):
    """Tek log kaydı silinebilir."""
    log = _seed_log(db, message="Silinecek")
    log_id = log.id

    res = client.delete(f"/api/system/error-logs/{log_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    db.expire_all()
    assert db.query(ErrorLog).filter(ErrorLog.id == log_id).first() is None


def test_delete_nonexistent_returns_404(client, auth_headers):
    """Var olmayan ID için 404."""
    res = client.delete("/api/system/error-logs/99999999", headers=auth_headers)
    assert res.status_code == 404


def test_clear_all_logs(client, auth_headers, db):
    """Filtre olmadan tüm kayıtlar temizlenir."""
    _seed_log(db, level="ERROR")
    _seed_log(db, level="WARNING")
    _seed_log(db, level="CRITICAL")

    res = client.delete("/api/system/error-logs/", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["deleted"] == 3

    db.expire_all()
    assert db.query(ErrorLog).count() == 0


def test_clear_logs_by_level(client, auth_headers, db):
    """Sadece belirli seviyedeki loglar temizlenebilir."""
    _seed_log(db, level="ERROR", message="e1")
    _seed_log(db, level="ERROR", message="e2")
    _seed_log(db, level="WARNING", message="w1")

    res = client.delete("/api/system/error-logs/?level=ERROR", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["deleted"] == 2

    db.expire_all()
    remaining = db.query(ErrorLog).all()
    assert len(remaining) == 1
    assert remaining[0].level == "WARNING"
