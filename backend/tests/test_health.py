"""Sağlık kontrolü testleri — gerçek bağımlılık doğrulaması (denetim OBS-002).

Uç eskiden sabit `{"status":"ok"}` döndürüyordu; DB çökmüş olsa bile 200 verirdi, yani
deploy sonrası "health 200 ✔" doğrulamaları hiçbir şey kanıtlamıyordu. Bu testler yeni
davranışı sabitler: DB SERT bağımlılık (düşerse 503), Sedna tüneli YUMUŞAK (kapalıysa
yalnız raporlanır, 503 üretmez).
"""

from unittest.mock import patch

from app.config import settings


def test_health_ok_when_db_up(client):
    """Sağlıklı durumda 200 + DB kontrolü GERÇEKTEN yapılmış olmalı."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "sprenses-api"

    db = data["checks"]["database"]
    assert db["status"] == "ok"
    # Gerçek sorgu yapıldığının kanıtı: ölçülmüş bir gecikme değeri var
    assert isinstance(db["latency_ms"], (int, float))


def test_health_returns_503_when_db_down(client):
    """DB erişilemezse 503 — sahte 200 REGRESYONUNU yakalar.

    Bu testin varlık sebebi: eski uç DB'ye hiç bakmadığından her koşulda 200 dönerdi.
    """
    from app.routers.core import health as health_mod

    with patch.object(health_mod, "text", side_effect=RuntimeError("DB kapalı")):
        response = client.get("/api/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["database"]["status"] == "error"


def test_sedna_tunnel_down_does_not_fail_health(client):
    """Sedna tüneli KAPALI olması API'yi hasta SAYMAZ (bilinçli yumuşak bağımlılık).

    Tünel akşamları/LAN makinesi kapalıyken normalde kapalıdır; sert saymak her gece
    sahte alarm üretirdi. Yalnız içe-aktarma adımları 503 döner.
    """
    from app.routers.core import health as health_mod

    with patch.object(settings, "sedna_password", "testpw"), \
         patch.object(health_mod, "_check_sedna_tunnel",
                      return_value={"status": "down", "note": "test"}):
        response = client.get("/api/health")

    assert response.status_code == 200          # ← kritik: 503 DEĞİL
    assert response.json()["checks"]["sedna_tunnel"]["status"] == "down"


def test_sedna_disabled_when_not_configured(client):
    """SEDNA_PASSWORD boşsa tünel hiç yoklanmaz (gereksiz soket denemesi yok)."""
    with patch.object(settings, "sedna_password", ""):
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["checks"]["sedna_tunnel"]["status"] == "disabled"


def test_liveness_never_checks_dependencies(client):
    """/health/live yalnız süreç canlılığı — DB kontrolü YAPMAZ, daima 200."""
    from app.routers.core import health as health_mod

    with patch.object(health_mod, "text", side_effect=RuntimeError("DB kapalı")):
        response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"
