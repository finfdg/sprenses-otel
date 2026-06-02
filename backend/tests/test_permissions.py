"""İzin kontrol testleri — can_view vs can_use ayrımı.

Tüm korumalı endpoint'lerin kimlik doğrulama ve yetkilendirme
kontrollerini doğrular.
"""

import pytest


# ── Kimlik doğrulama gerektiren endpoint'ler ────────────────
# (method, path) — kimliksiz erişimde 401/403 dönmeli

PROTECTED_ENDPOINTS = [
    # Finans
    ("GET", "/api/finance/cash-flow/"),
    ("GET", "/api/finance/cash-flow/summary"),
    ("GET", "/api/finance/banks/accounts/"),
    ("GET", "/api/finance/checks/"),
    ("GET", "/api/finance/checks/summary"),
    ("GET", "/api/finance/krediler/"),
    ("GET", "/api/finance/krediler/summary/by-type"),
    ("GET", "/api/finance/butce/kategoriler"),
    ("GET", "/api/finance/butce/?year=2099"),
    ("GET", "/api/finance/butce/summary?year=2099"),
    ("GET", "/api/finance/onay/my-approvals"),
    ("GET", "/api/finance/onay/pending-count"),
    ("GET", "/api/finance/cariler/vendors"),
    ("GET", "/api/finance/avanslar/"),
    ("GET", "/api/finance/exchange-rates/latest"),
    # Muhasebe
    ("GET", "/api/accounting/taxes/"),
    ("GET", "/api/accounting/recurring/"),
    ("GET", "/api/accounting/rent-income/"),
    ("GET", "/api/accounting/rent-expense/"),
    ("GET", "/api/accounting/dividend/"),
    ("GET", "/api/accounting/taxes/summary/totals"),
    # İK
    ("GET", "/api/hr/salary/"),
    ("GET", "/api/hr/withholding/"),
    ("GET", "/api/hr/sgk/"),
    # Sistem
    ("GET", "/api/system/users/"),
    ("GET", "/api/system/roles/"),
    ("GET", "/api/system/modules/"),
    ("GET", "/api/system/audit-logs/"),
    # Mesajlaşma
    ("GET", "/api/messages/conversations"),
    ("GET", "/api/messages/unread-count"),
    ("GET", "/api/messages/users"),
]


class TestUnauthenticatedAccess:
    """Kimlik doğrulama olmadan korumalı endpoint'lere erişim — hepsi 401/403 dönmeli."""

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS,
                             ids=[f"{m} {p.split('?')[0]}" for m, p in PROTECTED_ENDPOINTS])
    def test_unauthenticated_blocked(self, client, method, path):
        resp = getattr(client, method.lower())(path)
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code} instead of 401/403"
        )


# ── Write endpoint'leri (use izni gerektirenler) ──────────
# Kimliksiz erişimde POST/PATCH/DELETE endpoint'leri 401/403 dönmeli

WRITE_ENDPOINTS = [
    ("POST", "/api/finance/krediler/", {"type": "spot_kredi", "name": "X", "total_amount": 100}),
    ("POST", "/api/finance/butce/kategoriler", {"name": "X", "type": "expense"}),
    ("POST", "/api/accounting/taxes/", {"name": "X", "amount": 100}),
    ("POST", "/api/hr/salary/", {"name": "X", "amount": 100}),
    ("POST", "/api/system/users/", {"username": "x", "email": "x@x.com", "password": "x", "role_id": 1}),
    ("POST", "/api/system/roles/", {"name": "x"}),
    ("DELETE", "/api/finance/krediler/999999", None),
    ("DELETE", "/api/finance/butce/kategoriler/999999", None),
    ("DELETE", "/api/accounting/taxes/999999", None),
]


class TestWriteEndpointsBlocked:
    """Kimlik doğrulama olmadan yazma endpoint'leri — hepsi 401/403 dönmeli."""

    @pytest.mark.parametrize("method,path,body", WRITE_ENDPOINTS,
                             ids=[f"{m} {p.split('?')[0]}" for m, p, _ in WRITE_ENDPOINTS])
    def test_write_unauthenticated(self, client, method, path, body):
        kwargs = {}
        if body:
            kwargs["json"] = body
        resp = getattr(client, method.lower())(path, **kwargs)
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code} instead of 401/403"
        )


# ── Admin yetkili endpoint testleri ────────────────────────
# Admin tüm view endpoint'lerine erişebilmeli

class TestAdminCanAccessAll:
    """Admin kullanıcı tüm korumalı endpoint'lere erişebilir."""

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS,
                             ids=[f"{m} {p.split('?')[0]}" for m, p in PROTECTED_ENDPOINTS])
    def test_admin_can_access(self, client, auth_headers, method, path):
        resp = getattr(client, method.lower())(path, headers=auth_headers)
        # Admin erişebilmeli — 401/403 dönmemeli
        assert resp.status_code not in (401, 403), (
            f"Admin {method} {path} erişemedi: {resp.status_code}"
        )
