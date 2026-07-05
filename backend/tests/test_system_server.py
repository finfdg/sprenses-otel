"""Sunucu izleme modülü testleri (system.server).

Bu modül CPU/RAM/disk metrikleri ve servis durumlarını döner.
Gerçek sudo restart çağrıları yapmıyoruz — sadece izin/whitelist davranışını
ve response yapısını test ediyoruz. Sudo gerektiren restart yolu, subprocess
mock'lanarak doğrulanır.
"""
from unittest.mock import patch, MagicMock

import pytest

from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User


@pytest.fixture(autouse=True)
def _ensure_system_server_module(db):
    """system.server modülü test DB'sinde yoksa oluştur ve admin'e izin ver.

    Bu modül migration'lara seed edilmemiş (manuel olarak production'a eklendi).
    Test izolasyonu için her testte SAVEPOINT içinde oluşturuyoruz —
    test sonunda rollback geri alır.
    """
    mod = db.query(Module).filter(Module.code == "system.server").first()
    if not mod:
        mod = Module(name="Sunucu", code="system.server", is_active=True, sort_order=60)
        db.add(mod)
        db.flush()

    admin = db.query(User).filter(User.username == "admin").first()
    if admin:
        perm = (
            db.query(RoleModulePermission)
            .filter(
                RoleModulePermission.role_id == admin.role_id,
                RoleModulePermission.module_id == mod.id,
            )
            .first()
        )
        if not perm:
            db.add(RoleModulePermission(
                role_id=admin.role_id,
                module_id=mod.id,
                can_view=True,
                can_use=True,
            ))
            db.flush()
        else:
            if not perm.can_view or not perm.can_use:
                perm.can_view = True
                perm.can_use = True
                db.flush()

    # Modül cache invalidation — require_permission DB'den okuyacak
    from app.middleware.auth import invalidate_module_cache
    invalidate_module_cache()

    yield


# ─── Yetki ──────────────────────────────────────────────


def test_server_info_requires_auth(client):
    """Kimliksiz erişim 401/403."""
    res = client.get("/api/system/server/info")
    assert res.status_code in (401, 403)


def test_restart_requires_auth(client):
    """Restart endpoint'i auth gerektirir."""
    res = client.post("/api/system/server/services/sprenses-api/restart")
    assert res.status_code in (401, 403)


def test_logs_requires_auth(client):
    """Log endpoint'i auth gerektirir."""
    res = client.get("/api/system/server/services/sprenses-api/logs")
    assert res.status_code in (401, 403)


# ─── /server/info ───────────────────────────────────────


def test_server_info_returns_metrics_shape(client, auth_headers):
    """Sunucu bilgisi response şeması doğru olmalı.

    Gerçek psutil + systemctl çağrılarını mocklamak yerine response şemasını
    doğruluyoruz — endpoint'in build edilmesi yeterli garanti.
    """
    res = client.get("/api/system/server/info", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()

    # Üst seviye anahtarlar
    for key in ("cpu", "memory", "disk", "uptime_seconds", "services", "storage", "fetched_at"):
        assert key in data, f"info response'ta '{key}' yok"

    # CPU
    assert "percent" in data["cpu"]
    assert "cores" in data["cpu"]

    # Memory
    for k in ("total_mb", "used_mb", "free_mb", "percent"):
        assert k in data["memory"]

    # Disk
    for k in ("total_gb", "used_gb", "free_gb", "percent"):
        assert k in data["disk"]

    # Services — whitelist'teki tüm servisleri içermeli
    service_names = {s["name"] for s in data["services"]}
    expected_services = {
        "sprenses-api",
        "sprenses-frontend",
        "sprenses-exchange-rates",
        "postgresql",
        "nginx",
    }
    assert expected_services.issubset(service_names)


def test_server_info_service_fields(client, auth_headers):
    """Her servis için active/memory_mb/main_pid alanları döner."""
    res = client.get("/api/system/server/info", headers=auth_headers)
    assert res.status_code == 200
    services = res.json()["services"]
    for svc in services:
        assert "name" in svc
        assert "active" in svc
        assert isinstance(svc["active"], bool)
        assert "memory_mb" in svc
        assert "main_pid" in svc


def test_server_info_storage_fields(client, auth_headers):
    """Storage bölümünde db_size_mb / uploads_mb / logs_mb alanları döner."""
    res = client.get("/api/system/server/info", headers=auth_headers)
    assert res.status_code == 200
    storage = res.json()["storage"]
    assert "db_size_mb" in storage
    assert "uploads_mb" in storage
    assert "logs_mb" in storage


# ─── /server/services/{name}/restart — Whitelist ──────────


def test_restart_rejects_unknown_service(client, auth_headers):
    """Whitelist dışı servis için 400 dönmeli — gerçek restart yapılmaz."""
    res = client.post(
        "/api/system/server/services/malicious-service/restart",
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "restart edilemez" in res.json()["detail"].lower()


def test_restart_rejects_command_injection_attempt(client, auth_headers):
    """Path traversal / komut injeksiyon denemesi engellenmeli."""
    res = client.post(
        "/api/system/server/services/sprenses-api;rm -rf//restart",
        headers=auth_headers,
    )
    # FastAPI path parametresinde ';' karakteri rotaya uymadığı için 400 veya 404
    assert res.status_code in (400, 404)


def test_restart_whitelisted_service_calls_subprocess(client, auth_headers):
    """Whitelist'teki servis restart edilirken subprocess.run çağrılır.

    Gerçek sudo çağrısı yapmak yerine subprocess'i mocklarız.
    """
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stderr = ""
    with patch("app.routers.system_server.subprocess.run", return_value=fake_result) as mock_run:
        res = client.post(
            "/api/system/server/services/sprenses-api/restart",
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        assert body["service"] == "sprenses-api"
        mock_run.assert_called_once()
        # İlk argümanın sudo + systemctl restart sprenses-api olduğunu doğrula
        called_args = mock_run.call_args[0][0]
        assert called_args[:3] == ["sudo", "-n", "systemctl"]
        assert "sprenses-api" in called_args


def test_restart_propagates_subprocess_failure(client, auth_headers):
    """subprocess returncode != 0 ise 500 dönmeli."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stderr = "sudo: a password is required"
    with patch("app.routers.system_server.subprocess.run", return_value=fake_result):
        res = client.post(
            "/api/system/server/services/sprenses-api/restart",
            headers=auth_headers,
        )
        assert res.status_code == 500
        assert "password" in res.json()["detail"].lower()


# ─── /server/services/{name}/logs ────────────────────────


def test_logs_rejects_unknown_service(client, auth_headers):
    """Whitelist dışı servisin logu istenirse 400."""
    res = client.get(
        "/api/system/server/services/unknown-svc/logs",
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_logs_rejects_invalid_lines_param(client, auth_headers):
    """lines parametresi 1-500 arasında olmalı."""
    # 0 (alt sınır altı)
    res = client.get(
        "/api/system/server/services/sprenses-api/logs?lines=0",
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "1-500" in res.json()["detail"]

    # 600 (üst sınır üstü)
    res2 = client.get(
        "/api/system/server/services/sprenses-api/logs?lines=600",
        headers=auth_headers,
    )
    assert res2.status_code == 400


def test_logs_whitelisted_service_returns_log_field(client, auth_headers):
    """Whitelist'teki servis için subprocess mocklayarak başarı yolu test edilir."""
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "Apr 12 12:00:01 sprenses-api[123]: started"
    fake_result.stderr = ""
    with patch("app.routers.system_server.subprocess.run", return_value=fake_result):
        res = client.get(
            "/api/system/server/services/postgresql/logs?lines=10",
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["service"] == "postgresql"
        assert body["lines"] == 10
        assert "started" in body["log"]


def test_logs_propagates_subprocess_failure(client, auth_headers):
    """journalctl returncode != 0 ise 500."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stderr = "Permission denied"
    fake_result.stdout = ""
    with patch("app.routers.system_server.subprocess.run", return_value=fake_result):
        res = client.get(
            "/api/system/server/services/nginx/logs",
            headers=auth_headers,
        )
        assert res.status_code == 500
        assert "permission" in res.json()["detail"].lower()
