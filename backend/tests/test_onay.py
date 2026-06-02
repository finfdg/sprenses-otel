"""Departman onay iş akışı testleri.

Endpoint'ler: /api/finance/onay/
"""

import pytest

PREFIX = "/api/finance/onay"


# ─── MY APPROVALS ────────────────────────────────────────────


class TestMyApprovals:

    def test_my_approvals_structure(self, client, auth_headers):
        """Onay bekleyen listesi — başarılı yanıt."""
        resp = client.get(f"{PREFIX}/my-approvals", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_my_approvals_without_auth(self, client):
        resp = client.get(f"{PREFIX}/my-approvals")
        assert resp.status_code in (401, 403)


# ─── PENDING COUNT ───────────────────────────────────────────


class TestPendingCount:

    def test_pending_count_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/pending-count", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] >= 0

    def test_pending_count_without_auth(self, client):
        resp = client.get(f"{PREFIX}/pending-count")
        assert resp.status_code in (401, 403)


# ─── ASSIGN ──────────────────────────────────────────────────


class TestAssign:

    def test_assign_not_found(self, client, auth_headers):
        """Var olmayan VTX — 404."""
        resp = client.post(
            f"{PREFIX}/assign/999999",
            json={"department_id": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_assign_without_auth(self, client):
        resp = client.post(f"{PREFIX}/assign/1", json={"department_id": 1})
        assert resp.status_code in (401, 403)


# ─── APPROVE / REJECT ───────────────────────────────────────


class TestApproveReject:

    def test_approve_not_found(self, client, auth_headers):
        resp = client.post(f"{PREFIX}/approve/999999", json={}, headers=auth_headers)
        assert resp.status_code == 404

    def test_reject_not_found(self, client, auth_headers):
        resp = client.post(
            f"{PREFIX}/reject/999999",
            json={"note": "Test ret nedeni"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_approve_without_auth(self, client):
        resp = client.post(f"{PREFIX}/approve/1", json={})
        assert resp.status_code in (401, 403)


# ─── REMOVE ──────────────────────────────────────────────────


class TestRemove:

    def test_remove_not_found(self, client, auth_headers):
        resp = client.post(f"{PREFIX}/remove/999999", headers=auth_headers)
        assert resp.status_code == 404

    def test_remove_without_auth(self, client):
        resp = client.post(f"{PREFIX}/remove/1")
        assert resp.status_code in (401, 403)
