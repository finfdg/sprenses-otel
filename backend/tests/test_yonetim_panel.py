"""Yönetim Paneli (yonetim.panel) — KPI dashboard + maliyet sınıflama + uyarılar.

Salt-okunur 3 GET endpoint'i mevcut modüllerin verisini birleştirir. Boş/seyrek DB'de
bile çökmeden 0/boş döndürmeli (graceful). Audit'te 'testi olmayan modül' (Yüksek)
olarak işaretlenmişti — bu dosya shape + RBAC + temel tutarlılığı doğrular.
"""

API = "/api/yonetim"


class TestDashboard:
    def test_dashboard_shape(self, client, auth_headers):
        r = client.get(f"{API}/dashboard", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("occupancy", "cost", "revenue", "finance", "gop_approx_try"):
            assert key in body, f"eksik blok: {key}"
        assert "supplier_debt_try" in body["finance"]
        assert "room_invoiced_try" in body["revenue"]
        assert "occupancy_pct" in body["occupancy"]

    def test_dashboard_requires_view(self, client, no_perm_user_headers):
        assert client.get(f"{API}/dashboard", headers=no_perm_user_headers).status_code == 403

    def test_dashboard_viewer_ok(self, client, viewer_user_headers):
        assert client.get(f"{API}/dashboard", headers=viewer_user_headers).status_code == 200

    def test_dashboard_unauthorized(self, client):
        assert client.get(f"{API}/dashboard").status_code == 401


class TestCostClassification:
    def test_shape_and_total(self, client, auth_headers):
        r = client.get(f"{API}/cost-classification", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) == 3
        assert {it["key"] for it in body["items"]} == {"variable", "semi", "fixed"}
        # total = parçaların toplamı (yuvarlama toleransı)
        assert abs(body["total"] - sum(it["total"] for it in body["items"])) < 0.01

    def test_requires_view(self, client, no_perm_user_headers):
        assert client.get(f"{API}/cost-classification", headers=no_perm_user_headers).status_code == 403


class TestAlerts:
    def test_shape(self, client, auth_headers):
        r = client.get(f"{API}/alerts", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("price_variance", "supplier_debt_top", "supplier_debt_total_try",
                    "critical_stock", "critical_stock_count"):
            assert key in body
        assert isinstance(body["price_variance"], list)
        assert isinstance(body["critical_stock"], list)
        assert body["critical_stock_count"] == len(body["critical_stock"])

    def test_requires_view(self, client, no_perm_user_headers):
        assert client.get(f"{API}/alerts", headers=no_perm_user_headers).status_code == 403
