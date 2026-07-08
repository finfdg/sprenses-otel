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

    Tutar GECE BAZLI dağıtılır: her konaklama gecesi kendi dönemine, eur_total gece
    sayısına bölünerek (Aylık Doluluk Dağılımı ile aynı yöntem). Durum yalnız kategori/renk.
    Seed'te nights = (checkout - checkin) gün sayısına EŞİT tutulur → gece başına pay ×
    gece sayısı = eur_total (aylara doğru bölünür).
    """

    TODAY = date(2026, 7, 15)

    def _seed(self, db):
        db.add(AgencyGroup(name="EXPEDIA", members=["EXPEDIA"], term_days=0))
        rows = [
            # gelen (Reservation) — 20→25 Tem, 5 gece × 100€ (hepsi Tem)
            dict(rec_id=910001, agency="EXPEDIA", status="Reservation",
                 checkin_date=date(2026, 7, 20), checkout_date=date(2026, 7, 25), eur_total=500),
            # içeride (InHouse) — 10→18 Tem, 8 gece × 100€ (hepsi Tem)
            dict(rec_id=910002, agency="EXPEDIA", status="InHouse",
                 checkin_date=date(2026, 7, 10), checkout_date=date(2026, 7, 18), eur_total=800),
            # çıkış (CheckOut) — 28 May→2 Haz, 5 gece × 100€ → May 4 gece (400) + Haz 1 gece (100)
            dict(rec_id=910003, agency="EXPEDIA", status="CheckOut",
                 checkin_date=date(2026, 5, 28), checkout_date=date(2026, 6, 2), eur_total=500),
            # grupsuz acente → Diğer; çıkış 1→4 Tem, 3 gece × 100€ (hepsi Tem)
            dict(rec_id=910004, agency="RANDOMX", status="CheckOut",
                 checkin_date=date(2026, 7, 1), checkout_date=date(2026, 7, 4), eur_total=300),
        ]
        for r in rows:
            n = (r["checkout_date"] - r["checkin_date"]).days  # gece = konaklama süresi
            db.add(Reservation(record_date=date(2026, 1, 1), nights=n, rooms=1, **r))
        db.flush()

    def test_monthly_status_split(self, db):
        self._seed(db)
        out = compute_agency_status(db, "month", 2026, today=self.TODAY)
        by_m = {p["key"]: p for p in out["periods"]}
        # Temmuz: gelen (5 gece 500), içeride (8 gece 800), çıkış (RANDOMX 3 gece 300)
        jul = by_m[7]["statuses"]
        assert jul["gelen"]["amount"] == 500
        assert jul["iceride"]["amount"] == 800
        assert jul["cikis"]["amount"] == 300     # yalnız RANDOMX; r3'ün Tem gecesi yok
        # r3 (EXPEDIA çıkış) 28 May→2 Haz gece bazlı → May 400, Haz 100
        assert by_m[5]["statuses"]["cikis"]["amount"] == 400
        assert by_m[6]["statuses"]["cikis"]["amount"] == 100
        assert out["totals"]["gelen"]["amount"] == 500
        assert out["totals"]["cikis"]["amount"] == 800   # 400 + 100 + 300
        assert out["grand_count"] == 5   # r3 iki aya (May+Haz) değdiğinden 2 sayılır
        assert len(out["periods"]) == 12

    def test_agency_grouping(self, db):
        self._seed(db)
        out = compute_agency_status(db, "month", 2026, today=self.TODAY)
        by_name = {a["name"]: a for a in out["agencies"]}
        # EXPEDIA grubu: üyelerinin tüm durumları tek satırda toplanır
        assert by_name["EXPEDIA"]["gelen"]["amount"] == 500
        assert by_name["EXPEDIA"]["iceride"]["amount"] == 800
        assert by_name["EXPEDIA"]["cikis"]["amount"] == 500   # r3 tüm geceleri (May 400 + Haz 100)
        assert by_name["EXPEDIA"]["total_amount"] == 1800
        assert by_name["EXPEDIA"]["total_count"] == 4         # r3 May+Haz'da ayrı sayılır
        # RANDOMX gruplanmamış ama adetçe top-N içinde → müstakil satır (Diğer'e gömülmez)
        assert by_name["RANDOMX"]["id"] is None
        assert by_name["RANDOMX"]["cikis"]["amount"] == 300
        assert "Diğer" not in by_name   # geriye toplanacak (top-N dışı) birim kalmadı

    def test_daily_granularity(self, db):
        self._seed(db)
        out = compute_agency_status(db, "day", 2026, month=7, today=self.TODAY)
        assert out["granularity"] == "day" and out["month"] == 7
        assert len(out["periods"]) == 31
        by_d = {p["key"]: p for p in out["periods"]}
        # gece bazlı → giriş günü değil, her gece kendi gününe 100€
        assert by_d[20]["statuses"]["gelen"]["amount"] == 100   # r1 ilk gecesi (20 Tem)
        assert by_d[10]["statuses"]["iceride"]["amount"] == 100  # r2 ilk gecesi (10 Tem)
        assert by_d[1]["statuses"]["cikis"]["amount"] == 100     # RANDOMX ilk gecesi (1 Tem)
        assert out["totals"]["gelen"]["amount"] == 500           # r1 5 gece × 100
        # r3'ün Temmuz gecesi yok (28 May→2 Haz) → Temmuz çıkış yalnız RANDOMX (3 gece 300)
        assert out["totals"]["cikis"]["amount"] == 300

    def test_yearly_granularity(self, db):
        self._seed(db)
        out = compute_agency_status(db, "year", today=self.TODAY)
        assert [p["key"] for p in out["periods"]] == [2024, 2025, 2026, 2027]
        by_y = {p["key"]: p for p in out["periods"]}
        assert by_y[2026]["statuses"]["gelen"]["amount"] == 500
        assert by_y[2026]["statuses"]["cikis"]["amount"] == 800   # r3 (500) + RANDOMX (300)

    def test_group_filter_shows_members(self, db):
        self._seed(db)
        gid = db.query(AgencyGroup).filter_by(name="EXPEDIA").first().id
        out = compute_agency_status(db, "month", 2026, group_id=gid, today=self.TODAY)
        # yalnız EXPEDIA üyeleri → RANDOMX (Diğer) hariç
        assert out["grand_count"] == 4   # r3 May+Haz'da ayrı sayılır (2) + r1 + r2
        assert out["totals"]["cikis"]["amount"] == 500   # RANDOMX'in 300'ü dahil değil (r3: 400+100)
        assert {a["name"] for a in out["agencies"]} == {"EXPEDIA"}  # ham üye adı, "Diğer" değil
        assert out["filter"]["group_id"] == gid and out["filter"]["label"] == "EXPEDIA"

    def test_agency_filter_uses_raw_name(self, db):
        self._seed(db)
        out = compute_agency_status(db, "month", 2026, agency="RANDOMX", today=self.TODAY)
        assert out["grand_count"] == 1   # RANDOMX tek ay (Tem) → 1
        assert [a["name"] for a in out["agencies"]] == ["RANDOMX"]  # "Diğer" DEĞİL
        assert out["totals"]["cikis"]["amount"] == 300
        assert out["filter"]["agency"] == "RANDOMX"

    def test_other_group_filter_shows_ungrouped(self, db):
        self._seed(db)  # RANDOMX grup dışı, EXPEDIA gruplu
        # top_n=1 → yalnız EXPEDIA (adetçe en büyük) müstakil; RANDOMX "Diğer"e düşer.
        out = compute_agency_status(db, "month", 2026, group_id=0, top_n=1, today=self.TODAY)
        assert out["filter"]["label"] == "Diğer"
        assert [a["name"] for a in out["agencies"]] == ["RANDOMX"]  # yalnız grup dışı, bireysel
        assert out["totals"]["cikis"]["amount"] == 300
        assert out["grand_count"] == 1

    def test_top_n_rollup_and_diger_drill(self, db):
        # 8 grup (her biri tek üye, hepsi 1 rez → adet eşit) + 1 grup dışı acente.
        # Sıralama ADETe göre; adet eşit olduğundan tutar tiebreak'i devreye girer (AG0>…>AG7).
        for i in range(8):
            db.add(AgencyGroup(name=f"GRP{i}", members=[f"AG{i}"]))
        db.flush()
        rows = [
            dict(rec_id=920000 + i, agency=f"AG{i}", status="CheckOut",
                 checkin_date=date(2026, 6, 1), checkout_date=date(2026, 6, 10),
                 eur_total=1000 - i * 10)                       # AG0=1000 … AG7=930
            for i in range(8)
        ]
        rows.append(dict(rec_id=920099, agency="LONEWOLF", status="CheckOut",
                         checkin_date=date(2026, 6, 1), checkout_date=date(2026, 6, 10),
                         eur_total=5))                          # grup dışı
        for r in rows:
            n = (r["checkout_date"] - r["checkin_date"]).days  # tümü Haz içinde (tek ay) → tutar korunur
            db.add(Reservation(record_date=date(2026, 1, 1), nights=n, rooms=1, **r))
        db.flush()

        out = compute_agency_status(db, "month", 2026, top_n=7, today=self.TODAY)
        names = [a["name"] for a in out["agencies"]]
        assert len(names) == 8 and names[-1] == "Diğer"        # 7 grup + Diğer, en altta
        assert "GRP0" in names and "GRP7" not in names          # en düşük grup Diğer'e düştü
        diger = next(a for a in out["agencies"] if a["name"] == "Diğer")
        assert diger["cikis"]["amount"] == 935                  # GRP7 (930) + LONEWOLF (5)
        assert diger["id"] == 0
        # grand toplam top-N'den etkilenmez (tümü dahil)
        assert out["totals"]["cikis"]["amount"] == sum(1000 - i * 10 for i in range(8)) + 5

        # "Diğer"e drill → GRP7 üyesi (AG7) + LONEWOLF bireysel
        drill = compute_agency_status(db, "month", 2026, group_id=0, top_n=7, today=self.TODAY)
        assert {a["name"] for a in drill["agencies"]} == {"AG7", "LONEWOLF"}

    def test_count_ranking_promotes_ungrouped_agency(self, db):
        # Sıralama TUTARA değil ADETe göre → grupsuz BÜYÜK acente (çok rez, düşük tutar)
        # top-N'e girer; küçük grup (az rez, yüksek tutar) "Diğer"e düşer.
        db.add(AgencyGroup(name="SMALLGRP", members=["SMALLA"]))
        db.flush()
        rows = [
            # BIGSOLO — gruplanmamış, 3 rez, düşük tutar (10€ × 3)
            dict(rec_id=930100 + i, agency="BIGSOLO", status="CheckOut",
                 checkin_date=date(2026, 6, 1), checkout_date=date(2026, 6, 2), eur_total=10)
            for i in range(3)
        ]
        # SMALLGRP üyesi SMALLA — 1 rez, yüksek tutar
        rows.append(dict(rec_id=930200, agency="SMALLA", status="CheckOut",
                         checkin_date=date(2026, 6, 1), checkout_date=date(2026, 6, 2), eur_total=9999))
        for r in rows:
            n = (r["checkout_date"] - r["checkin_date"]).days
            db.add(Reservation(record_date=date(2026, 1, 1), nights=n, rooms=1, **r))
        db.flush()

        out = compute_agency_status(db, "month", 2026, top_n=1, today=self.TODAY)
        names = [a["name"] for a in out["agencies"]]
        assert names[0] == "BIGSOLO"          # adet 3 > SMALLGRP adet 1 (tutarı düşük olsa da)
        big = out["agencies"][0]
        assert big["id"] is None              # gruplanmamış → bireysel satır (drill: tek acente)
        assert big["total_count"] == 3
        assert names[-1] == "Diğer"
        diger = next(a for a in out["agencies"] if a["name"] == "Diğer")
        assert diger["total_count"] == 1 and diger["cikis"]["amount"] == 9999  # SMALLGRP Diğer'de
        # BIGSOLO kökte müstakil → "Diğer" drill'inde GÖRÜNMEZ
        drill = compute_agency_status(db, "month", 2026, group_id=0, top_n=1, today=self.TODAY)
        assert {a["name"] for a in drill["agencies"]} == {"SMALLA"}

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
