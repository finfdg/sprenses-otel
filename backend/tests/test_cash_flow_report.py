"""Nakit akım PDF raporu (`GET /finance/cash-flow/report/pdf`) testleri."""


class TestCashFlowReportPdf:
    def test_report_pdf_returns_valid_pdf(self, client, auth_headers):
        resp = client.get("/api/finance/cash-flow/report/pdf", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content[:5] == b"%PDF-"
        assert "nakit-akim-raporu" in resp.headers.get("content-disposition", "")

    def test_report_pdf_with_date_range(self, client, auth_headers):
        resp = client.get(
            "/api/finance/cash-flow/report/pdf?start_date=2026-01-01&end_date=2026-12-31",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_report_pdf_empty_range_still_valid_pdf(self, client, auth_headers):
        """Kayıt olmayan aralıkta bile geçerli PDF döner ('kayıt bulunamadı' mesajı)."""
        resp = client.get(
            "/api/finance/cash-flow/report/pdf?start_date=1999-01-01&end_date=1999-01-02",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_report_pdf_invalid_dates_tolerated(self, client, auth_headers):
        """Geçersiz tarih parametresi sessizce yok sayılır (listing.py toleransı)."""
        resp = client.get(
            "/api/finance/cash-flow/report/pdf?start_date=bozuk&end_date=2026-13-99",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_report_pdf_requires_auth(self, client):
        resp = client.get("/api/finance/cash-flow/report/pdf")
        assert resp.status_code == 401

    def test_report_pdf_requires_view_permission(self, client, no_perm_user_headers):
        resp = client.get("/api/finance/cash-flow/report/pdf", headers=no_perm_user_headers)
        assert resp.status_code == 403

    def test_report_pdf_viewer_can_access(self, client, viewer_user_headers):
        """Salt-görüntüleme (can_view) yetkisi rapor indirmeye yeter — GET/read-only."""
        resp = client.get("/api/finance/cash-flow/report/pdf", headers=viewer_user_headers)
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_eur_balances_endpoint_unchanged_after_refactor(self, client, auth_headers):
        """compute_eur_balances çıkarımı sonrası eur-balances endpoint'i aynı şemayı döner."""
        resp = client.get("/api/finance/cash-flow/eur-balances", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "daily" in body
        assert "monthly" in body
        assert "total_balance_eur" in body
