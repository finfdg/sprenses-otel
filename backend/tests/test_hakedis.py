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
