"""Acente Mahsup & Nakit Akım (sales.acente_mahsup) — projeksiyon panosu.

Salt-okuma GET endpoint'i rezervasyon cirosunu (EUR) acente konfigü (vade/kickback) +
gerçek avanslar + yıl sonu hedef senaryosuyla birleştirir. RBAC + payload shape +
projeksiyon matematiği (gerçekleşen/ileri ayrımı, pay, kickback, hedef dağıtımı) doğrulanır.
"""
from datetime import date

from app.models.agency_group import AgencyGroup
from app.models.reservation import Reservation
from app.services.agency_settlement_service import compute_agency_status, compute_settlement

API = "/api/sales/acente-mahsup"


def _seed_reservation(db, rec_id, agency, checkout, eur):
    r = Reservation(
        rec_id=rec_id, agency=agency,
        checkin_date=date(checkout.year, checkout.month, 1),
        checkout_date=checkout, record_date=date(checkout.year, 1, 1),
        nights=1, rooms=1, eur_total=eur,
    )
    db.add(r)
    return r


class TestRBAC:
    def test_unauthorized(self, client):
        assert client.get(f"{API}/").status_code == 401

    def test_requires_view(self, client, no_perm_user_headers):
        assert client.get(f"{API}/", headers=no_perm_user_headers).status_code == 403

    def test_viewer_ok(self, client, viewer_user_headers):
        assert client.get(f"{API}/", headers=viewer_user_headers).status_code == 200

    def test_admin_shape(self, client, auth_headers):
        r = client.get(f"{API}/?year=2026&opening_cash=1000", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("kpi", "funnel", "agencies", "monthly", "advances", "invoices", "cashflow"):
            assert key in body, f"eksik blok: {key}"
        assert body["currency"] == "EUR"
        assert len(body["monthly"]) == 12
        for k in ("grand_total", "realized", "forecast", "advance_received", "kickback_total"):
            assert k in body["kpi"]


class TestProjectionMath:
    """compute_settlement doğrudan çağrılır (deterministik today ile)."""

    TODAY = date(2026, 7, 15)  # Tem ortası: Oca–Haz gerçekleşen, Tem–Ara ileri

    def _seed(self, db):
        g = AgencyGroup(name="TESTGRP", members=["TESTAG"], term_days=30,
                        kickback_percent=10)
        db.add(g)
        _seed_reservation(db, 900001, "TESTAG", date(2026, 6, 10), 1000)   # gerçekleşen
        _seed_reservation(db, 900002, "TESTAG", date(2026, 9, 10), 2000)   # ileri
        _seed_reservation(db, 900003, "RANDOMX", date(2026, 5, 10), 500)   # grupsuz → Diğer
        db.flush()

    def test_revenue_split_and_shares(self, db):
        self._seed(db)
        out = compute_settlement(db, 2026, year_target=None,
                                 opening_cash=0, today=self.TODAY)
        assert out["kpi"]["realized"] == 1500        # Haz 1000 + May 500
        assert out["kpi"]["grand_total"] == 3500     # hedef yok → gerçek toplam
        assert out["kpi"]["forecast"] == 2000        # ileri (Eyl 2000)
        by_name = {a["name"]: a for a in out["agencies"]}
        assert by_name["TESTGRP"]["revenue"] == 3000
        assert by_name["Diğer"]["revenue"] == 500
        # pay: TESTGRP 3000/3500
        assert abs(by_name["TESTGRP"]["share_pct"] - (3000 / 3500 * 100)) < 0.2

    def test_kickback_from_config(self, db):
        self._seed(db)
        out = compute_settlement(db, 2026, year_target=None,
                                 opening_cash=0, today=self.TODAY)
        by_name = {a["name"]: a for a in out["agencies"]}
        assert by_name["TESTGRP"]["kickback"] == 300   # 3000 × %10
        assert by_name["Diğer"]["kickback"] == 0
        assert out["kpi"]["kickback_total"] == 300

    def test_monthly_recognition_at_checkout(self, db):
        self._seed(db)
        out = compute_settlement(db, 2026, year_target=None,
                                 opening_cash=0, today=self.TODAY)
        m = {row["month"]: row for row in out["monthly"]}
        assert m[5]["total"] == 500 and m[5]["realized"] is True    # Mayıs
        assert m[6]["total"] == 1000 and m[6]["realized"] is True   # Haziran
        assert m[9]["total"] == 2000 and m[9]["realized"] is False  # Eylül (ileri)

    def test_target_scenario_distributes_forecast(self, db):
        self._seed(db)
        out = compute_settlement(db, 2026, year_target=10000,
                                 opening_cash=0, today=self.TODAY)
        assert out["kpi"]["grand_total"] == 10000
        assert out["monthly_meta"]["additional_forecast"] == 6500  # 10000 − 3500
        # Ek tahmin İLERİ rezervasyon ağırlığıyla dağıtılır → yalnız TESTGRP'nin (Eyl)
        # ileri bookingi var, tümü ona gider. Diğer (yalnız geçmiş) forecast almaz.
        by_name = {a["name"]: a for a in out["agencies"]}
        assert abs(by_name["TESTGRP"]["revenue"] - 9500) < 1.0   # 3000 + 6500
        assert abs(by_name["Diğer"]["revenue"] - 500) < 1.0      # forecast almaz

    def test_funnel_reconciles(self, db):
        self._seed(db)
        out = compute_settlement(db, 2026, year_target=None,
                                 opening_cash=0, today=self.TODAY)
        f = out["funnel"]
        # net tahsilat = fatura − avans mahsubu
        assert abs(f["net_collection"] - (f["invoiced"] - f["advance_offset"])) < 0.01
        # fatura toplamı = net + mahsup
        inv = out["invoices"]
        assert abs(inv["total_amount"] - (inv["total_net"] + inv["total_mahsup"])) < 0.05


class TestAgencyStatus:
    """compute_agency_status: acente × durum (gelen/içeride/çıkış) × dönem kırılımı.

    Durum → doğal tarih eşlemesi: gelen/içeride GİRİŞ (check-in), çıkış ÇIKIŞ (check-out).
    """

    TODAY = date(2026, 7, 15)

    def _seed(self, db):
        db.add(AgencyGroup(name="EXPEDIA", members=["EXPEDIA"], term_days=0))
        rows = [
            # gelen (Reservation) — giriş 20 Tem 2026
            dict(rec_id=910001, agency="EXPEDIA", status="Reservation",
                 checkin_date=date(2026, 7, 20), checkout_date=date(2026, 7, 25), eur_total=500),
            # içeride (InHouse) — giriş 10 Tem 2026
            dict(rec_id=910002, agency="EXPEDIA", status="InHouse",
                 checkin_date=date(2026, 7, 10), checkout_date=date(2026, 7, 18), eur_total=800),
            # çıkış (CheckOut) — çıkış 2 Haz 2026
            dict(rec_id=910003, agency="EXPEDIA", status="CheckOut",
                 checkin_date=date(2026, 5, 28), checkout_date=date(2026, 6, 2), eur_total=300),
            # grupsuz acente → Diğer; çıkış 4 Tem 2026
            dict(rec_id=910004, agency="RANDOMX", status="CheckOut",
                 checkin_date=date(2026, 7, 1), checkout_date=date(2026, 7, 4), eur_total=200),
        ]
        for r in rows:
            db.add(Reservation(record_date=date(2026, 1, 1), nights=1, rooms=1, **r))
        db.flush()

    def test_monthly_status_split(self, db):
        self._seed(db)
        out = compute_agency_status(db, "month", 2026, today=self.TODAY)
        by_m = {p["key"]: p for p in out["periods"]}
        # Temmuz: gelen (giriş 500), içeride (giriş 800), çıkış (RANDOMX 200)
        jul = by_m[7]["statuses"]
        assert jul["gelen"]["amount"] == 500
        assert jul["iceride"]["amount"] == 800
        assert jul["cikis"]["amount"] == 200
        # Haziran: çıkış 300 (EXPEDIA çıkışı Haziran'da)
        assert by_m[6]["statuses"]["cikis"]["amount"] == 300
        assert out["totals"]["gelen"]["amount"] == 500
        assert out["totals"]["cikis"]["amount"] == 500   # 300 + 200
        assert out["grand_count"] == 4
        assert len(out["periods"]) == 12

    def test_agency_grouping(self, db):
        self._seed(db)
        out = compute_agency_status(db, "month", 2026, today=self.TODAY)
        by_name = {a["name"]: a for a in out["agencies"]}
        assert by_name["EXPEDIA"]["gelen"]["amount"] == 500
        assert by_name["EXPEDIA"]["iceride"]["amount"] == 800
        assert by_name["EXPEDIA"]["cikis"]["amount"] == 300
        assert by_name["EXPEDIA"]["total_amount"] == 1600
        assert by_name["EXPEDIA"]["total_count"] == 3
        assert by_name["Diğer"]["cikis"]["amount"] == 200

    def test_daily_granularity(self, db):
        self._seed(db)
        out = compute_agency_status(db, "day", 2026, month=7, today=self.TODAY)
        assert out["granularity"] == "day" and out["month"] == 7
        assert len(out["periods"]) == 31
        by_d = {p["key"]: p for p in out["periods"]}
        assert by_d[20]["statuses"]["gelen"]["amount"] == 500   # giriş 20 Tem
        assert by_d[10]["statuses"]["iceride"]["amount"] == 800  # giriş 10 Tem
        assert by_d[4]["statuses"]["cikis"]["amount"] == 200     # RANDOMX çıkış 4 Tem
        # r3 çıkışı Haziran → Temmuz gününde görünmemeli
        assert out["totals"]["cikis"]["amount"] == 200

    def test_yearly_granularity(self, db):
        self._seed(db)
        out = compute_agency_status(db, "year", today=self.TODAY)
        assert [p["key"] for p in out["periods"]] == [2024, 2025, 2026, 2027]
        by_y = {p["key"]: p for p in out["periods"]}
        assert by_y[2026]["statuses"]["gelen"]["amount"] == 500
        assert by_y[2026]["statuses"]["cikis"]["amount"] == 500

    def test_group_filter_shows_members(self, db):
        self._seed(db)
        gid = db.query(AgencyGroup).filter_by(name="EXPEDIA").first().id
        out = compute_agency_status(db, "month", 2026, group_id=gid, today=self.TODAY)
        # yalnız EXPEDIA üyeleri → RANDOMX (Diğer) hariç
        assert out["grand_count"] == 3
        assert out["totals"]["cikis"]["amount"] == 300   # RANDOMX'in 200'ü dahil değil
        assert {a["name"] for a in out["agencies"]} == {"EXPEDIA"}  # ham üye adı, "Diğer" değil
        assert out["filter"]["group_id"] == gid and out["filter"]["label"] == "EXPEDIA"

    def test_agency_filter_uses_raw_name(self, db):
        self._seed(db)
        out = compute_agency_status(db, "month", 2026, agency="RANDOMX", today=self.TODAY)
        assert out["grand_count"] == 1
        assert [a["name"] for a in out["agencies"]] == ["RANDOMX"]  # "Diğer" DEĞİL
        assert out["totals"]["cikis"]["amount"] == 200
        assert out["filter"]["agency"] == "RANDOMX"

    def test_filter_options_universe(self, db):
        self._seed(db)
        out = compute_agency_status(db, "month", 2026, today=self.TODAY)
        gnames = {g["name"]: g for g in out["filter_options"]["groups"]}
        assert "EXPEDIA" in gnames and gnames["EXPEDIA"]["count"] == 1
        assert set(out["filter_options"]["agencies"]) >= {"EXPEDIA", "RANDOMX"}

    def test_endpoint_rbac_and_shape(self, client, auth_headers, no_perm_user_headers):
        client.cookies.clear()  # fixture login'lerinin bıraktığı cookie'yi temizle (gerçek kimliksiz)
        assert client.get(f"{API}/agency-status").status_code == 401
        assert client.get(f"{API}/agency-status", headers=no_perm_user_headers).status_code == 403
        r = client.get(f"{API}/agency-status?granularity=month&year=2026", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("statuses", "periods", "agencies", "totals", "grand_amount",
                  "grand_count", "filter", "filter_options"):
            assert k in body, f"eksik blok: {k}"
        assert len(body["periods"]) == 12
        assert len(body["statuses"]) == 3
        assert "groups" in body["filter_options"] and "agencies" in body["filter_options"]

    def test_endpoint_agency_filter(self, client, auth_headers):
        r = client.get(f"{API}/agency-status?granularity=month&year=2026&agency=RANDOMX",
                       headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["filter"]["agency"] == "RANDOMX"

    def test_endpoint_invalid_granularity(self, client, auth_headers):
        assert client.get(f"{API}/agency-status?granularity=hafta",
                          headers=auth_headers).status_code == 422
