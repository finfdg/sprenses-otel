"""Çek modülü CRUD testleri.

Endpoint'ler: /api/finance/checks/
Not: Upload testi Excel dosyası gerektirdiğinden burada liste, özet ve durum testleri yapılır.
"""

import pytest

PREFIX = "/api/finance/checks"


# ─── LIST ────────────────────────────────────────────────────


class TestCheckList:

    def test_list_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data

    def test_list_with_filters(self, client, auth_headers):
        """Filtreler ile listeleme — hata vermemeli."""
        resp = client.get(f"{PREFIX}/?status=pending&currency=TL", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_with_search(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?search=test", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_with_sort(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?sort_by=due_date&sort_order=asc", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_pagination(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?page=1&page_size=5", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) <= 5

    def test_list_without_auth(self, client):
        resp = client.get(f"{PREFIX}/")
        assert resp.status_code in (401, 403)


# ─── SUMMARY ─────────────────────────────────────────────────


class TestCheckSummary:

    def test_summary_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Yapısal alanlar mevcut olmalı
        assert "total_count" in data
        assert "total_amount" in data
        assert "pending_count" in data
        assert "pending_amount" in data

    def test_summary_without_auth(self, client):
        resp = client.get(f"{PREFIX}/summary")
        assert resp.status_code in (401, 403)


# ─── UPLOADS ─────────────────────────────────────────────────


class TestCheckUploads:

    def test_list_uploads(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/uploads", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_delete_upload_not_found(self, client, auth_headers):
        resp = client.delete(f"{PREFIX}/uploads/999999", headers=auth_headers)
        assert resp.status_code == 404


# ─── STATUS UPDATE ───────────────────────────────────────────


class TestCheckStatus:

    def test_status_update_not_found(self, client, auth_headers):
        resp = client.patch(
            f"{PREFIX}/999999/status?new_status=cancelled",
            headers=auth_headers,
        )
        assert resp.status_code == 404
