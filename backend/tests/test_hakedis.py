"""Hak Ediş Takibi (finance.hakedis) testleri.

Kapsam: yaşlandırma hesabı (vade + gecikme kovaları), vade tanımı upsert,
RBAC (view/use 403 yolu), onay akışı uçtan-uca regresyonu.
"""
from datetime import date, timedelta

from app.models.receivable_term import ReceivableTerm
from app.models.sales_invoice import SalesCollection, SalesInvoice

PREFIX = "/api/finance/hakedis"


def _mk_invoice(db, code, name, d, amount, currency="TL", invoice_no=None):
    inv = SalesInvoice(
        customer_code=code, customer_name=name, invoice_date=d,
        amount=amount, currency=currency,
        amount_currency=amount if currency != "TL" else 0,
        invoice_no=invoice_no, tx_hash=f"th-{code}-{d}-{amount}",
    )
    db.add(inv)
    return inv


class TestReceivableComputation:
    def test_aging_and_terms(self, client, auth_headers, db):
        """Vade=fatura+term_days; tanımlı firma kendi vadesi, tanımsız 30 gün varsayılan;
        gecikme kovaları doğru dolar; tahsil edilen fatura listeden düşer."""
        today = date.today()
        code_a, code_b = "120.98.01.A001", "120.98.01.B001"
        # A: vade tanımlı 45 gün — 50 gün önce kesilen fatura → 5 gün gecikmiş (1-7 kovası)
        db.add(ReceivableTerm(customer_code=code_a, term_days=45))
        _mk_invoice(db, code_a, "TEST ACENTE A", today - timedelta(days=50), 10000, invoice_no="FA1")
        # B (tanımsız → 30 gün): 10 gün önce → vadesi gelmemiş; 70 gün önce → 40 gün gecikmiş (30+)
        _mk_invoice(db, code_b, "TEST ACENTE B", today - timedelta(days=10), 5000, invoice_no="FB1")
        _mk_invoice(db, code_b, "TEST ACENTE B", today - timedelta(days=70), 7000, invoice_no="FB2")
        # B'nin tamamen tahsil edilmiş eski faturası — listede GÖRÜNMEMELİ
        _mk_invoice(db, code_b, "TEST ACENTE B", today - timedelta(days=100), 3000, invoice_no="FB0")
        db.add(SalesCollection(customer_code=code_b, customer_name="TEST ACENTE B",
                               collection_date=today - timedelta(days=90), amount=3000,
                               currency="TL", amount_currency=0, tx_hash="col-b0"))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        assert r.status_code == 200, r.text
        j = r.json()
        by_code = {f["code"]: f for f in j["firms"]}

        fa = by_code[code_a]
        assert fa["term_days"] == 45 and fa["is_default_term"] is False
        assert fa["max_overdue_days"] == 5
        assert fa["open_tl"] == 10000 and fa["overdue_tl"] == 10000

        fb = by_code[code_b]
        assert fb["term_days"] == 30 and fb["is_default_term"] is True
        # FIFO: 3000 tahsilat en eski (FB0) faturayı kapatır → açık FB1+FB2
        assert fb["open_tl"] == 12000
        assert fb["max_overdue_days"] == 40
        assert fb["buckets"]["overdue_30_plus"] == 7000
        assert fb["buckets"]["not_due"] == 5000

        assert j["summary"]["open_tl"] >= 22000
        assert j["summary"]["overdue_firm_count"] >= 2

    def test_munferit_excluded(self, client, auth_headers, db):
        """Münferit (walk-in) faturalar hak ediş takibine GİRMEZ — misafir çıkışta öder
        (PMS folio kanıtı) ama muhasebe 120.03.*'e tahsilat işlemez → sinyal güvenilmez."""
        today = date.today()
        inv = _mk_invoice(db, "120.03.99.M001", "MÜNFERİT TEST",
                          today - timedelta(days=90), 99999, invoice_no="FM1")
        inv.is_munferit = True
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        assert r.status_code == 200
        codes = [f["code"] for f in r.json()["firms"]]
        assert "120.03.99.M001" not in codes, "Münferit firma hak ediş listesinde OLMAMALI"

    def test_firm_invoices_detail(self, client, auth_headers, db):
        today = date.today()
        code = "120.98.02.C001"
        _mk_invoice(db, code, "TEST ACENTE C", today - timedelta(days=40), 8000, invoice_no="FC1")
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/firms/{code}/invoices", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        inv = items[0]
        assert inv["invoice_no"] == "FC1"
        assert inv["overdue_days"] == 10  # 40 gün önce + 30 gün vade
        assert inv["bucket"] == "overdue_8_30"
        assert inv["remaining"] == 8000


class TestGroupingAndAdvances:
    def test_agency_grouping_via_bridge(self, client, auth_headers, db):
        """agency_groups.members (PMS adları) → agency_code_map köprüsü → 120 kodları gruplanır;
        grup satırı toplamları + üye listesi + grup fatura detayı (`group-{id}`) çalışır."""
        from app.models.agency_code_map import AgencyCodeMap
        from app.models.agency_group import AgencyGroup

        today = date.today()
        _mk_invoice(db, "120.96.01.G001", "GRUP TEST BİR A.Ş.", today - timedelta(days=50), 10000, invoice_no="G1")
        _mk_invoice(db, "120.96.01.G002", "GRUP TEST İKİ LTD.", today - timedelta(days=10), 4000, invoice_no="G2")
        db.add(AgencyCodeMap(pms_name="GRUPTEST EU", acc_code="120.96.01.G001"))
        db.add(AgencyCodeMap(pms_name="GRUPTEST RU", acc_code="120.96.01.G002"))
        grp = AgencyGroup(name="GRUPTEST", members=["GRUPTEST EU", "GRUPTEST RU"])
        db.add(grp)
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        assert r.status_code == 200
        rows = {f["name"]: f for f in r.json()["firms"]}
        g = rows.get("GRUPTEST")
        assert g and g["is_group"] is True, "Grup satırı oluşmalı"
        assert len(g["members"]) == 2
        assert g["open_tl"] == 14000  # 10000 + 4000
        assert g["max_overdue_days"] == 20  # 50g - 30g vade
        # Üye kodları ayrı satır olarak GÖRÜNMEMELİ
        codes = [f["code"] for f in r.json()["firms"]]
        assert "120.96.01.G001" not in codes and "120.96.01.G002" not in codes

        # Grup fatura detayı — iki üyenin faturaları birleşik
        d = client.get(f"{PREFIX}/firms/group-{grp.id}/invoices", headers=auth_headers)
        assert d.status_code == 200
        inv_nos = sorted(i["invoice_no"] for i in d.json()["items"])
        assert inv_nos == ["G1", "G2"]

    def test_code_override_wins_over_sedna_map(self, client, auth_headers, db):
        """agency_code_overrides Sedna haritasının ÜZERİNE yazar: haritadaki yanlış kod
        yerine override kodu kullanılır. (Sedna senkronu agency_code_map'i silip yeniden
        yüklediğinden kalıcı düzeltmeler bu tabloda yaşar — 2026-07-17 kontrat analizi.)"""
        from app.models.agency_code_map import AgencyCodeMap
        from app.models.agency_code_override import AgencyCodeOverride
        from app.models.agency_group import AgencyGroup

        today = date.today()
        _mk_invoice(db, "120.95.01.D001", "OVERRIDE DOĞRU A.Ş.",
                    today - timedelta(days=10), 6000, invoice_no="OV1")
        db.add(AgencyCodeMap(pms_name="OVERRIDETEST", acc_code="120.95.01.YANLIS"))
        db.add(AgencyCodeOverride(pms_name="OVERRIDETEST", acc_code="120.95.01.D001",
                                  notes="test: harita yanlış, faturalar D001'de"))
        db.add(AgencyGroup(name="OVERRIDEGRUP", members=["OVERRIDETEST"]))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        assert r.status_code == 200
        rows = {f["name"]: f for f in r.json()["firms"]}
        g = rows.get("OVERRIDEGRUP")
        assert g and g["is_group"] is True, "Override kodu üzerinden grup satırı oluşmalı"
        assert g["open_tl"] == 6000  # fatura, haritadaki yanlış kodda değil override kodunda

    def test_advance_netting(self, client, auth_headers, db):
        """340 avansı (isim-eşli) firmadan düşülür: net_open_tl = max(0, open - advance_tl)."""
        from app.models.sales_invoice import SalesAdvance

        today = date.today()
        _mk_invoice(db, "120.96.02.A001", "AVANS TEST TURİZM A.Ş.", today - timedelta(days=5), 20000, invoice_no="AV1")
        db.add(SalesAdvance(code="340.96.02.A001", name="AVANS TEST TURİZM",
                            currency="TL", received=15000, consumed=0))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        row = next(f for f in r.json()["firms"] if f["code"] == "120.96.02.A001")
        assert row["advance_tl"] == 15000
        assert row["net_open_tl"] == 5000  # 20000 - 15000
        assert "advance_tl" in r.json()["summary"] and "net_open_tl" in r.json()["summary"]


class TestTermUpsert:
    def test_patch_creates_and_updates(self, client, auth_headers, db):
        code = "120.98.03.D001"
        r1 = client.patch(f"{PREFIX}/terms/{code}", headers=auth_headers,
                          json={"term_days": 45, "notes": "2026 anlaşması"})
        assert r1.status_code == 200, r1.text
        assert r1.json()["term_days"] == 45

        r2 = client.patch(f"{PREFIX}/terms/{code}", headers=auth_headers,
                          json={"term_days": 30})
        assert r2.status_code == 200
        db.expire_all()
        rows = db.query(ReceivableTerm).filter(ReceivableTerm.customer_code == code).all()
        assert len(rows) == 1 and rows[0].term_days == 30  # upsert — çift kayıt yok

    def test_patch_validation(self, client, auth_headers):
        r = client.patch(f"{PREFIX}/terms/120.98.03.D002", headers=auth_headers,
                         json={"term_days": 999})
        assert r.status_code == 422  # pydantic ge/le


class TestRBAC:
    def test_view_required(self, client, no_perm_user_headers):
        assert client.get(f"{PREFIX}/", headers=no_perm_user_headers).status_code == 403

    def test_use_required_for_terms(self, client, viewer_user_headers):
        r = client.patch(f"{PREFIX}/terms/120.98.04.E001", headers=viewer_user_headers,
                         json={"term_days": 45})
        assert r.status_code == 403

    def test_viewer_can_read(self, client, viewer_user_headers):
        assert client.get(f"{PREFIX}/", headers=viewer_user_headers).status_code == 200


class TestCollectionsVisibility:
    """Tahsilat görünürlüğü (2026-07-03): firma satırında toplam/son tahsilat +
    eşlenmemiş (çapraz-kur) havuz + tahsilat dökümü endpoint'i."""

    def test_firm_row_includes_collection_stats(self, client, auth_headers, db):
        today = date.today()
        code = "120.94.01.T001"
        _mk_invoice(db, code, "TAHSİLAT TEST A.Ş.", today - timedelta(days=10), 10000, invoice_no="T1")
        db.add(SalesCollection(customer_code=code, customer_name="TAHSİLAT TEST A.Ş.",
                               collection_date=today - timedelta(days=3), amount=4000,
                               currency="TL", amount_currency=0, tx_hash="col-t1"))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        row = next(f for f in r.json()["firms"] if f["code"] == code)
        assert row["collected_tl"] == 4000
        assert row["collection_count"] == 1
        assert row["last_collection_date"] == (today - timedelta(days=3)).isoformat()
        assert row["open_tl"] == 6000  # FIFO kısmi mahsup
        assert row["unapplied_tl"] == 0.0  # aynı birim, faturayı aşmıyor → havuz boş
        assert "collected_tl" in r.json()["summary"]
        assert "unapplied_tl" in r.json()["summary"]

    def test_cross_currency_collection_shows_unapplied(self, client, auth_headers, db):
        """EUR faturalı firmaya TL tahsilat: FIFO mahsup ETMEZ (para birimi kovası farklı) →
        açık native değişmez ama tahsilat satırda görünür ve havuz 'eşlenmemiş' olarak döner.
        (Canlı örnek: FUN AND SUN ₺213.959 TL EFT, faturaların tamamı EUR.)"""
        today = date.today()
        code = "120.94.02.X001"
        inv = _mk_invoice(db, code, "ÇAPRAZ KUR TEST GMBH",
                          today - timedelta(days=10), 53000, currency="EUR", invoice_no="X1")
        inv.amount_currency = 1000  # €1.000
        db.add(SalesCollection(customer_code=code, customer_name="ÇAPRAZ KUR TEST GMBH",
                               collection_date=today - timedelta(days=2), amount=5000,
                               currency="TL", amount_currency=0, tx_hash="col-x1"))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        row = next(f for f in r.json()["firms"] if f["code"] == code)
        assert row["open_native"] == 1000  # TL tahsilat EUR faturayı KAPATMADI
        assert row["collected_tl"] == 5000  # ama satırda görünür
        assert row["collected_native"] == 0.0  # EUR cinsinden tahsilat yok
        assert row["unapplied_tl"] == 5000  # havuzda askıda (TL kuru 1.0)
        assert row["unapplied_by_currency"] == {"TL": 5000}

    def test_firm_collections_endpoint(self, client, auth_headers, db):
        today = date.today()
        code = "120.94.03.C001"
        _mk_invoice(db, code, "DÖKÜM TEST LTD.", today - timedelta(days=5), 9000, invoice_no="D1")
        db.add(SalesCollection(customer_code=code, customer_name="DÖKÜM TEST LTD.",
                               collection_date=today - timedelta(days=4), amount=2000,
                               currency="TL", amount_currency=0, tx_hash="col-d1",
                               description="GELEN EFT"))
        db.add(SalesCollection(customer_code=code, customer_name="DÖKÜM TEST LTD.",
                               collection_date=today - timedelta(days=1), amount=1500,
                               currency="TL", amount_currency=0, tx_hash="col-d2"))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/firms/{code}/collections", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 2
        # Yeniden eskiye sıralı
        assert items[0]["collection_date"] == (today - timedelta(days=1)).isoformat()
        assert items[1]["description"] == "GELEN EFT"
        assert items[1]["amount_tl"] == 2000

    def test_collections_endpoint_requires_view(self, client, no_perm_user_headers):
        r = client.get(f"{PREFIX}/firms/120.94.03.C001/collections", headers=no_perm_user_headers)
        assert r.status_code == 403


class TestOrganizedRowFields:
    """Düzenli satır alanları (2026-07-03): faturalanan toplam (ödenmişler dahil),
    avans alınan/mahsup durumu, ay sonu tahsilat planı (kümülatif)."""

    def test_invoiced_totals_include_paid(self, client, auth_headers, db):
        today = date.today()
        code = "120.93.01.F001"
        _mk_invoice(db, code, "FATURALANAN TEST", today - timedelta(days=60), 3000, invoice_no="P1")
        _mk_invoice(db, code, "FATURALANAN TEST", today - timedelta(days=5), 5000, invoice_no="P2")
        db.add(SalesCollection(customer_code=code, customer_name="FATURALANAN TEST",
                               collection_date=today - timedelta(days=50), amount=3000,
                               currency="TL", amount_currency=0, tx_hash="col-f1"))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        row = next(f for f in r.json()["firms"] if f["code"] == code)
        assert row["invoiced_tl"] == 8000       # ödenmiş P1 DAHİL
        assert row["total_invoice_count"] == 2
        assert row["invoice_count"] == 1        # yalnız açık
        assert row["open_tl"] == 5000

    def test_monthly_due_schedule_cumulative(self, db):
        """Ay sonu planı: ay içi vadesi dolan + kümülatif (sonraki ay öncekini kapsar)."""
        from app.services.receivable_service import compute_receivables
        from app.services.sales_invoice_service import _invalidate_compute_cache

        code = "120.93.02.M001"
        # Varsayılan vade 30 gün: 10.06 → vade 10.07 (Temmuz); 20.07 → vade 19.08 (Ağustos)
        _mk_invoice(db, code, "PLAN TEST", date(2026, 6, 10), 4000, invoice_no="PL1")
        _mk_invoice(db, code, "PLAN TEST", date(2026, 7, 20), 6000, invoice_no="PL2")
        db.commit()
        _invalidate_compute_cache()

        res = compute_receivables(db, today=date(2026, 7, 15))
        row = next(f for f in res["firms"] if f["code"] == code)
        sched = {e["month"]: e for e in row["monthly_due"]}
        assert sched["2026-07"]["due_tl"] == 4000
        assert sched["2026-07"]["cum_tl"] == 4000
        assert sched["2026-08"]["due_tl"] == 6000
        assert sched["2026-08"]["cum_tl"] == 10000  # kümülatif — Temmuz'u kapsar

    def test_advance_consumed_stats(self, client, auth_headers, db):
        """Tamamı mahsup edilmiş avans: netleme değişmez (advance_tl=0) ama
        alınan/mahsup istatistikleri satırda görünür ('avans mahsup edilmiş mi?')."""
        from app.models.sales_invoice import SalesAdvance

        today = date.today()
        code = "120.93.03.A001"
        _mk_invoice(db, code, "MAHSUP TEST TURİZM A.Ş.", today - timedelta(days=5), 20000, invoice_no="MA1")
        db.add(SalesAdvance(code="340.93.03.A001", name="MAHSUP TEST TURİZM",
                            currency="TL", received=15000, consumed=15000))
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        row = next(f for f in r.json()["firms"] if f["code"] == code)
        assert row["advance_tl"] == 0.0          # kalan avans yok → net açık değişmez
        assert row["advance_received_tl"] == 15000
        assert row["advance_consumed_tl"] == 15000
        assert row["net_open_tl"] == 20000


class TestNativeCurrencyDisplay:
    def test_single_currency_firm_gets_native_fields(self, client, auth_headers, db):
        """Tek para birimli (EUR) firmada open/overdue/net native (€) alanları döner —
        fatura detayıyla aynı birim (2026-07-02 geri bildirimi: 'faturalar EUR, başlık neden TL')."""
        from datetime import date, timedelta
        today = date.today()
        inv = _mk_invoice(db, "120.95.01.E001", "EURO TEST GMBH",
                          today - timedelta(days=40), 53000, currency="EUR", invoice_no="E1")
        inv.amount_currency = 1000  # €1.000 (TL karşılığı 53.000)
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        row = next(f for f in r.json()["firms"] if f["code"] == "120.95.01.E001")
        assert row["display_currency"] == "EUR"
        assert row["open_native"] == 1000
        assert row["overdue_native"] == 1000  # 40g > 30g vade
        assert row["net_open_native"] == 1000  # avans yok
        assert row["open_tl"] == 53000  # TL karşılığı korunur (tooltip/toplamlar)
        assert "open_by_currency" in r.json()["summary"]

    def test_mixed_currency_firm_has_no_native(self, client, auth_headers, db):
        from datetime import date, timedelta
        today = date.today()
        _mk_invoice(db, "120.95.02.M001", "KARMA TEST", today - timedelta(days=5), 1000, currency="TRY", invoice_no="M1")
        inv2 = _mk_invoice(db, "120.95.02.M001", "KARMA TEST", today - timedelta(days=6), 5300, currency="EUR", invoice_no="M2")
        inv2.amount_currency = 100
        db.commit()
        from app.services.sales_invoice_service import _invalidate_compute_cache
        _invalidate_compute_cache()

        r = client.get(f"{PREFIX}/", headers=auth_headers)
        row = next(f for f in r.json()["firms"] if f["code"] == "120.95.02.M001")
        assert row["display_currency"] is None
        assert row["open_native"] is None  # karışık → TL gösterilir
        assert row["open_tl"] == 6300
