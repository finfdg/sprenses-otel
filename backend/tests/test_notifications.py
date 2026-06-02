"""Bildirim ve dosya servisi testleri.

Endpoint'ler: /api/notifications/, /api/uploads/
"""

import pytest

NOTIF_PREFIX = "/api/notifications"


# ─── Bildirim Listesi ──────────────────────────────────────


class TestNotificationList:

    def test_list_structure(self, client, auth_headers):
        """Bildirim listesi — sayfalama yapısı."""
        resp = client.get(f"{NOTIF_PREFIX}/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_pagination(self, client, auth_headers):
        resp = client.get(f"{NOTIF_PREFIX}/?page=1&page_size=5", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_without_auth(self, client):
        resp = client.get(f"{NOTIF_PREFIX}/")
        assert resp.status_code in (401, 403)


# ─── Okunmamış Sayısı ──────────────────────────────────────


class TestUnreadCount:

    def test_unread_count(self, client, auth_headers):
        resp = client.get(f"{NOTIF_PREFIX}/unread-count", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] >= 0

    def test_unread_without_auth(self, client):
        resp = client.get(f"{NOTIF_PREFIX}/unread-count")
        assert resp.status_code in (401, 403)


# ─── Okundu İşaretleme ─────────────────────────────────────


class TestMarkRead:

    def test_mark_read_empty_ids(self, client, auth_headers):
        """Boş ID listesi — 422 veya hata."""
        resp = client.patch(
            f"{NOTIF_PREFIX}/read",
            json={"ids": []},
            headers=auth_headers,
        )
        # Boş IDs kabul edilebilir veya hata verebilir
        assert resp.status_code in (200, 400, 422)

    def test_mark_read_without_auth(self, client):
        resp = client.patch(f"{NOTIF_PREFIX}/read", json={"ids": [1]})
        assert resp.status_code in (401, 403)


# ─── Bildirim Silme ────────────────────────────────────────


class TestDeleteNotification:

    def test_delete_all(self, client, auth_headers):
        """Tüm bildirimleri sil."""
        resp = client.delete(f"{NOTIF_PREFIX}/all", headers=auth_headers)
        assert resp.status_code == 200

    def test_delete_single_not_found(self, client, auth_headers):
        resp = client.delete(f"{NOTIF_PREFIX}/999999", headers=auth_headers)
        assert resp.status_code in (200, 404)

    def test_delete_without_auth(self, client):
        resp = client.delete(f"{NOTIF_PREFIX}/all")
        assert resp.status_code in (401, 403)


# ─── Dosya Servisi ──────────────────────────────────────────


class TestFileService:

    def test_file_access_without_auth(self, client):
        """Kimliksiz dosya erişimi — 401."""
        resp = client.get("/uploads/test.jpg")
        assert resp.status_code == 401

    def test_file_not_found(self, client, auth_headers):
        """Var olmayan dosya — 404."""
        resp = client.get("/uploads/nonexistent-file-12345.jpg", headers=auth_headers)
        assert resp.status_code in (401, 404)

    def test_nested_path_not_found(self, client, auth_headers):
        """Geçerli alt dizin yolu — 404 (dosya yok)."""
        resp = client.get("/uploads/subdir/nonexistent.jpg", headers=auth_headers)
        assert resp.status_code in (401, 404)
