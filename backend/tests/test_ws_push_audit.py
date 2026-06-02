"""WebSocket, Push ve Audit modülleri testleri."""

import pytest


# ==================== AUDIT LOG TESTLERİ ====================


class TestAuditLogs:
    """Audit log testleri."""

    def test_list_audit_logs(self, client, auth_headers):
        """Audit logları listelenebilmeli."""
        response = client.get("/api/system/audit-logs/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    def test_audit_logs_pagination(self, client, auth_headers):
        """Sayfalama çalışmalı."""
        response = client.get("/api/system/audit-logs/?page=1&page_size=5", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 5

    def test_audit_logs_action_filter(self, client, auth_headers):
        """Action filtresi çalışmalı."""
        response = client.get("/api/system/audit-logs/?action=login", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["action"] == "login"

    def test_audit_logs_entity_type_filter(self, client, auth_headers):
        """Entity type filtresi çalışmalı."""
        response = client.get("/api/system/audit-logs/?entity_type=user", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["entity_type"] == "user"

    def test_audit_logs_user_id_filter(self, client, auth_headers):
        """User ID filtresi çalışmalı."""
        response = client.get("/api/system/audit-logs/?user_id=1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["user_id"] == 1

    def test_audit_logs_response_structure(self, client, auth_headers):
        """Her log kaydı doğru yapıda olmalı."""
        response = client.get("/api/system/audit-logs/?page_size=5", headers=auth_headers)
        data = response.json()
        if data["items"]:
            item = data["items"][0]
            for field in ["id", "user_id", "action", "entity_type", "created_at"]:
                assert field in item, f"'{field}' alanı eksik"

    def test_audit_logs_has_user_info(self, client, auth_headers):
        """Log kaydında kullanıcı bilgisi olmalı."""
        response = client.get("/api/system/audit-logs/?page_size=5", headers=auth_headers)
        data = response.json()
        if data["items"]:
            item = data["items"][0]
            assert "username" in item
            assert "user_full_name" in item

    def test_audit_logs_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/system/audit-logs/")
        assert response.status_code == 401

    def test_audit_logs_ordered_desc(self, client, auth_headers):
        """Loglar yeniden eskiye sıralı olmalı."""
        response = client.get("/api/system/audit-logs/?page_size=20", headers=auth_headers)
        data = response.json()
        items = data["items"]
        if len(items) >= 2:
            for i in range(len(items) - 1):
                assert items[i]["created_at"] >= items[i + 1]["created_at"]


# ==================== PUSH BİLDİRİM TESTLERİ ====================


class TestPush:
    """Push bildirim testleri."""

    def test_get_vapid_key(self, client, auth_headers):
        """VAPID key döndürmeli."""
        response = client.get("/api/push/vapid-key", headers=auth_headers)
        # 200 (key varsa) veya 503 (yapılandırılmamışsa)
        assert response.status_code in (200, 503)

    def test_unsubscribe_nonexistent(self, client, auth_headers):
        """Olmayan abonelik iptal edilebilmeli (sessiz)."""
        response = client.delete(
            "/api/push/unsubscribe?endpoint=https://test.example.com/push",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_push_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/push/vapid-key")
        assert response.status_code == 401

    def _subscribe(self, client, headers, n):
        return client.post(
            "/api/push/subscribe",
            json={
                "endpoint": f"https://push.example.com/ep/{n}",
                "keys": {"p256dh": "BPk-fakekey-p256dh-value-for-test-000", "auth": "fakeauthvalue00"},
                "user_agent": f"TestAgent/{n}",
            },
            headers=headers,
        )

    def test_subscribe_caps_active_per_user(self, client, auth_headers, db):
        """REGRESYON (yavaş banka yükleme kök nedeni): kullanıcı başına aktif abonelik
        sayısı sınırlanmalı. Her tarayıcı/cihaz yeni endpoint üretir; sınır olmadan
        ölü abonelikler birikir (üretimde tek kullanıcıda 77) ve her bildirimde push
        servisine boş yere senkron HTTP isteği yapılır → gönderim yavaşlar."""
        from sqlalchemy import func

        from app.models.push_subscription import PushSubscription
        from app.routers.push import MAX_ACTIVE_SUBSCRIPTIONS_PER_USER as CAP

        # CAP'ten fazla farklı endpoint ile abone ol
        for i in range(CAP + 5):
            assert self._subscribe(client, auth_headers, i).status_code == 201

        # Hiçbir kullanıcının aktif abonelik sayısı sınırı aşmamalı
        counts = (
            db.query(PushSubscription.user_id, func.count(PushSubscription.id))
            .filter(PushSubscription.is_active == True)  # noqa: E712
            .group_by(PushSubscription.user_id)
            .all()
        )
        for uid, cnt in counts:
            assert cnt <= CAP, f"user {uid}: {cnt} aktif abonelik > sınır {CAP}"


# ==================== WEBSOCKET AUTH TESTLERİ ====================


class TestWebSocketAuth:
    """WebSocket kimlik doğrulama testleri."""

    def test_ws_auth_function(self):
        """authenticate_ws_token fonksiyonu geçersiz token'da None dönmeli."""
        from app.routers.ws import authenticate_ws_token
        result = authenticate_ws_token("invalid_token")
        assert result is None

    def test_ws_auth_valid_token(self, client, auth_headers):
        """Geçerli token'dan user_id alınabilmeli."""
        from app.routers.ws import authenticate_ws_token
        token = auth_headers["Authorization"].replace("Bearer ", "")
        result = authenticate_ws_token(token)
        assert result is not None
        user_id, session_id = result
        assert isinstance(user_id, int)
        assert user_id > 0


# ==================== HEALTH CHECK TESTLERİ ====================


class TestHealth:
    """Sağlık kontrolü testleri."""

    def test_health_check(self, client):
        """Health endpoint çalışmalı."""
        response = client.get("/api/health")
        assert response.status_code == 200
