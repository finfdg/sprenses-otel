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


# ── RBAC: view var, use YOK → mutasyon 403 ─────────────────
# Denetim bulgusu (2026-07-01): çoğu modülde "giriş yapmış ama use izni olmayan"
# kullanıcının POST/PATCH/DELETE'te 403 aldığını doğrulayan test yoktu — izin
# decorator'ı yanlışlıkla kaldırılsa regresyon kırmızı vermezdi. Aşağıdaki merkezi
# parametrik test bu boşluğu tüm modüller için tek yerde kapatır.
#
# require_permission(module, "use") bir FastAPI dependency'sidir → endpoint gövdesinden
# (404/503 vb.) ÖNCE çalışır; bu yüzden var olmayan ID'li DELETE bile 403 döner.
# (method, path, module_code) — module_code yalnız okunabilirlik için yorum.
VIEWER_FORBIDDEN_MUTATIONS = [
    ("DELETE", "/api/finance/krediler/999999"),            # finance.krediler
    ("DELETE", "/api/finance/butce/999999"),               # finance.butce
    ("DELETE", "/api/finance/banks/accounts/999999"),      # finance.banks
    ("DELETE", "/api/finance/checks/uploads/999999"),      # finance.checks
    ("DELETE", "/api/finance/avanslar/999999"),            # finance.avanslar
    ("DELETE", "/api/finance/cariler/uploads/999999"),     # finance.cariler
    ("DELETE", "/api/accounting/taxes/999999"),            # accounting.taxes
    ("DELETE", "/api/accounting/recurring/999999"),        # accounting.recurring
    ("DELETE", "/api/accounting/rent-income/999999"),      # accounting.rent_income
    ("DELETE", "/api/accounting/rent-expense/999999"),     # accounting.rent_expense
    ("DELETE", "/api/accounting/dividend/999999"),         # accounting.dividend
    ("DELETE", "/api/hr/salary/999999"),                   # hr.salary
    ("DELETE", "/api/hr/withholding/999999"),              # hr.withholding
    ("DELETE", "/api/hr/sgk/999999"),                      # hr.sgk
    ("DELETE", "/api/hr/shifts/999999"),                   # hr.shifts
    ("DELETE", "/api/hr/shift-schedule/999999"),           # hr.shift_schedule
    ("DELETE", "/api/sales/room-types/999999"),            # sales.acente_mahsup (oda tipleri)
    ("DELETE", "/api/sales/reservations/uploads/999999"),  # sales.acente_mahsup (rezervasyonlar)
    ("DELETE", "/api/system/users/999999"),                # system.users
    ("DELETE", "/api/system/roles/999999"),                # system.roles
    ("DELETE", "/api/system/modules/999999"),              # system.modules
    ("DELETE", "/api/system/error-logs/999999"),           # system.error_logs
    ("POST", "/api/system/server/services/nginx/restart"), # system.server
    ("POST", "/api/stok/sedna-import"),                    # stok.maliyet
    ("POST", "/api/finance/sales-invoices/sedna-import"),  # finance.sales_invoices
    ("POST", "/api/system/backup/run"),                    # system.backup
]


class TestViewerCannotMutate:
    """View izni olan ama use izni OLMAYAN kullanıcı mutasyon endpoint'lerinde 403 almalı.

    Her modülün `require_permission(module, "use")` geçidinin gerçekten çalıştığını
    doğrular (izin decorator'ı kaldırılırsa/GET'e düşürülürse test kırmızı verir).
    """

    @pytest.mark.parametrize("method,path", VIEWER_FORBIDDEN_MUTATIONS,
                             ids=[f"{m} {p}" for m, p in VIEWER_FORBIDDEN_MUTATIONS])
    def test_viewer_forbidden(self, client, viewer_user_headers, method, path):
        resp = getattr(client, method.lower())(path, headers=viewer_user_headers)
        assert resp.status_code == 403, (
            f"Viewer (use izni yok) {method} {path} → {resp.status_code} "
            f"(403 beklenirdi; use geçidi çalışmıyor olabilir)"
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
