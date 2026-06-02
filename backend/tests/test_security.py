"""Güvenlik sertleştirme testleri.

Kapsam (audit'te işaretlenen güvenlik bulguları):
- Global CSP başlığı (main.py SecurityHeadersMiddleware)
- Logo upload SVG stored-XSS engeli (quality/templates.py) — eski yetersiz blacklist
  yerine SVG tamamen reddedilir; raster formatlar magic-byte ile doğrulanır.
"""

from uuid import uuid4

from app.models.quality_template import QualityTemplate
from app.routers.quality.templates import _LOGOS_DIR

# Sadece ilk 4 bayt magic kontrol edilir; geçerli bir PNG başlığı yeterli.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_SVG_SCRIPT = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
# Eski blacklist filtresinin YAKALAMADIĞI vektör (onerror) — artık SVG tümden reddedilir.
_SVG_ONERROR = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="x" onerror="alert(1)"/></svg>'


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


# ─────────────────────── Logo upload SVG/XSS sertleştirme ───────────────────────

def _make_template(db) -> int:
    t = QualityTemplate(
        name=f"Logo Test {uuid4().hex[:6]}", description="güvenlik testi",
        frequency="daily", is_active=True, created_by=1,
    )
    db.add(t)
    db.commit()
    return t.id


def _cleanup_logos(tid: int) -> None:
    """Başarılı upload'ın diske yazdığı dosyaları temizle (DB rollback dosyayı silmez)."""
    for p in _LOGOS_DIR.glob(f"{tid}_*"):
        p.unlink(missing_ok=True)


class TestLogoUploadSecurity:
    def test_svg_logo_rejected(self, client, auth_headers, db):
        tid = _make_template(db)
        r = client.post(
            f"/api/quality/templates/{tid}/logo", headers=auth_headers,
            files={"file": ("logo.svg", _SVG_SCRIPT, "image/svg+xml")},
        )
        assert r.status_code == 400, r.text

    def test_svg_with_onerror_rejected(self, client, auth_headers, db):
        """Eski blacklist 'onerror='i yakalamıyordu; artık SVG kategorik olarak reddedilir."""
        tid = _make_template(db)
        r = client.post(
            f"/api/quality/templates/{tid}/logo", headers=auth_headers,
            files={"file": ("x.svg", _SVG_ONERROR, "image/svg+xml")},
        )
        assert r.status_code == 400

    def test_png_ext_with_svg_content_rejected(self, client, auth_headers, db):
        """Magic-byte doğrulaması: .png uzantısı ama içerik PNG değil → reddedilir
        (SVG'yi .png olarak yeniden adlandırıp atlatma denemesi engellenir)."""
        tid = _make_template(db)
        r = client.post(
            f"/api/quality/templates/{tid}/logo", headers=auth_headers,
            files={"file": ("fake.png", _SVG_SCRIPT, "image/png")},
        )
        assert r.status_code == 400

    def test_valid_png_accepted(self, client, auth_headers, db):
        tid = _make_template(db)
        try:
            r = client.post(
                f"/api/quality/templates/{tid}/logo", headers=auth_headers,
                files={"file": ("logo.png", _PNG_BYTES, "image/png")},
            )
            assert r.status_code in (200, 201), r.text
        finally:
            _cleanup_logos(tid)
