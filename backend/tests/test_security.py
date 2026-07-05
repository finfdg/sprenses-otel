"""Güvenlik sertleştirme testleri.

Kapsam (audit'te işaretlenen güvenlik bulguları):
- Global CSP başlığı (main.py SecurityHeadersMiddleware)
- Temel güvenlik başlıkları (X-Content-Type-Options, X-Frame-Options, HSTS)

Not: Logo upload SVG stored-XSS testleri Kalite modülü (quality/templates.py logo
endpoint'i) kaldırıldığında bu dosyadan çıkarıldı — o özellik yalnız Kalite modülüne aitti.
"""


# ─────────────────────── Güvenlik başlıkları ───────────────────────

class TestSecurityHeaders:
    def test_csp_header_present(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        csp = r.headers.get("content-security-policy")
        assert csp is not None, "CSP başlığı eksik"
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "base-uri 'none'" in csp

    def test_baseline_security_headers_present(self, client):
        r = client.get("/api/health")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert "max-age=" in (r.headers.get("strict-transport-security") or "")
