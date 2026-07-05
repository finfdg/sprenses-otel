"""Acente Mahsup & Nakit Akım (sales.acente_mahsup) — projeksiyon panosu.

Salt-okuma GET endpoint'i rezervasyon cirosunu (EUR) acente konfigü (vade/kickback) +
gerçek avanslar + yıl sonu hedef senaryosuyla birleştirir. RBAC + payload shape +
projeksiyon matematiği (gerçekleşen/ileri ayrımı, pay, kickback, hedef dağıtımı) doğrulanır.
"""
from datetime import date

from app.models.agency_group import AgencyGroup
from app.models.reservation import Reservation
from app.services.agency_settlement_service import compute_settlement

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
