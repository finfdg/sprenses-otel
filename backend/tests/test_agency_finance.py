"""Acente Finansal Takip — ay × acente birleşik rapor regresyonları."""
from datetime import date

from app.models.agency_code_map import AgencyCodeMap
from app.models.agency_group import AgencyGroup
from app.models.reservation import Reservation
from app.models.sales_invoice import (
    SalesAdvanceTransaction,
    SalesCollection,
    SalesInvoice,
)
from app.services.agency_finance_service import compute_agency_finance
from app.services.sales_invoice_service import _invalidate_compute_cache

API = "/api/sales/acente-finans"


def _seed(db):
    group = AgencyGroup(
        name="AFİN TEST ACENTE",
        members=["AFIN PMS"],
        term_days=30,
        kickback_percent=0,
    )
    db.add(group)
    db.flush()
    db.add(AgencyCodeMap(pms_name="AFIN PMS", acc_code="120.99.99.9901"))

    db.add_all([
        SalesAdvanceTransaction(
            sedna_rec_id=990001,
            code="340.99.99.9901",
            name="AFİN TEST TURİZM A.Ş.",
            transaction_date=date(2026, 1, 10),
            currency="EUR",
            received=300,
            consumed=0,
            received_tl=15000,
            consumed_tl=0,
        ),
        SalesAdvanceTransaction(
            sedna_rec_id=990002,
            code="340.99.99.9901",
            name="AFİN TEST TURİZM A.Ş.",
            transaction_date=date(2026, 4, 5),
            currency="EUR",
            received=0,
            consumed=100,
            received_tl=0,
            consumed_tl=5000,
        ),
        SalesInvoice(
            customer_code="120.99.99.9901",
            customer_name="AFİN TEST TURİZM A.Ş.",
            is_munferit=False,
            invoice_no="AFIN-1",
            invoice_date=date(2026, 4, 1),
            amount=500,
            currency="EUR",
            amount_currency=500,
            tx_hash="agency-finance-invoice-1",
        ),
        SalesInvoice(
            customer_code="120.99.99.9901",
            customer_name="AFİN TEST TURİZM A.Ş.",
            is_munferit=False,
            invoice_no="AFIN-2",
            invoice_date=date(2026, 6, 30),
            amount=400,
            currency="EUR",
            amount_currency=400,
            tx_hash="agency-finance-invoice-2",
        ),
        SalesCollection(
            customer_code="120.99.99.9901",
            customer_name="AFİN TEST TURİZM A.Ş.",
            collection_date=date(2026, 4, 20),
            amount=200,
            currency="EUR",
            amount_currency=200,
            description="Banka tahsilatı",
            tx_hash="agency-finance-collection-1",
        ),
        Reservation(
            rec_id=9999001,
            agency="AFIN PMS",
            checkin_date=date(2026, 8, 10),
            checkout_date=date(2026, 8, 15),
            record_date=date(2026, 2, 1),
            nights=5,
            rooms=1,
            eur_total=1000,
        ),
    ])
    db.flush()
    _invalidate_compute_cache()
    return group


class TestAgencyFinanceMath:
    TODAY = date(2026, 7, 15)

    def test_monthly_sources_and_receivable_plan(self, db):
        _seed(db)
        result = compute_agency_finance(db, 2026, today=self.TODAY)
        row = next(item for item in result["agencies"] if item["agency"] == "AFİN TEST ACENTE")
        months = {item["month"]: item for item in row["months"]}

        assert months[1]["advance_received"] == 300
        assert months[4]["advance_applied"] == 100
        assert months[4]["collections"] == 200
        assert months[4]["invoiced_amount"] == 500
        assert months[6]["invoiced_amount"] == 400
        assert months[8]["reservation_amount"] == 1000
        assert months[8]["reservation_count"] == 1

        # 1 Nisan fatura +30 gün = 1 Mayıs; tahsilat sonrası 300€ açıktan
        # kullanılmamış 200€ avans FIFO mahsup edilir, yalnız 100€ gecikmiş kalır.
        assert months[5]["open_due"] == 100
        assert months[5]["overdue"] == 100
        assert months[5]["month_end_receivable"] == 100

        # 30 Haziran fatura +30 gün = 30 Temmuz; bugün 15 Temmuz → açık ama gecikmemiş.
        assert months[7]["open_due"] == 400
        assert months[7]["overdue"] == 0

        # Avans önce açık faturaya ayrıldığı için ileri rezervasyona mahsup kalmaz.
        assert months[9]["projected_gross"] == 1000
        assert months[9]["projected_advance"] == 0
        assert months[9]["projected_due"] == 1000
        assert months[9]["month_end_receivable"] == 1000

        assert row["totals"]["month_end_receivable"] == 1500
        assert row["totals"]["invoiced_amount"] == 900
        assert result["source_counts"]["invoices"] >= 2
        assert result["totals"]["overdue"] >= 100

    def test_unused_advance_closes_open_invoices_before_overdue(self, db):
        _seed(db)
        db.add(SalesAdvanceTransaction(
            sedna_rec_id=990003,
            code="340.99.99.9901",
            name="AFİN TEST TURİZM A.Ş.",
            transaction_date=date(2026, 2, 10),
            currency="EUR",
            received=600,
            consumed=0,
            received_tl=30000,
            consumed_tl=0,
        ))
        db.flush()

        result = compute_agency_finance(db, 2026, today=self.TODAY)
        row = next(item for item in result["agencies"] if item["agency"] == "AFİN TEST ACENTE")

        # Net 800€ kullanılmamış avans, 700€ açık faturanın tamamını kapatır.
        assert row["totals"]["open_due"] == 0
        assert row["totals"]["overdue"] == 0
        # Açık faturadan artan 100€ ancak bundan sonra ileri rezervasyona ayrılır.
        assert row["totals"]["projected_advance"] == 100
        assert row["totals"]["projected_due"] == 900

    def test_member_breakdown_matches_group_totals(self, db):
        _seed(db)
        result = compute_agency_finance(db, 2026, today=self.TODAY)
        row = next(item for item in result["agencies"] if item["agency"] == "AFİN TEST ACENTE")
        members = {member["name"]: member["totals"] for member in row["members"]}

        # Rezervasyon bacağı PMS acente adıyla, Sedna bacağı 120 cari adıyla listelenir.
        assert "AFIN PMS" in members
        assert "AFİN TEST TURİZM A.Ş." in members
        assert members["AFIN PMS"]["reservation_amount"] == 1000
        assert members["AFIN PMS"]["reservation_count"] == 1
        assert members["AFIN PMS"]["projected_due"] == 1000
        assert members["AFİN TEST TURİZM A.Ş."]["advance_received"] == 300
        assert members["AFİN TEST TURİZM A.Ş."]["collections"] == 200
        assert members["AFİN TEST TURİZM A.Ş."]["invoiced_amount"] == 900
        assert members["AFİN TEST TURİZM A.Ş."]["open_due"] == 500
        assert members["AFİN TEST TURİZM A.Ş."]["overdue"] == 100

        # Üye kırılımının toplamı grup satırıyla birebir tutmalı.
        for key in ("advance_received", "collections", "reservation_amount",
                    "invoiced_amount", "overdue", "open_due", "projected_due",
                    "month_end_receivable"):
            assert round(sum(m[key] for m in members.values()), 2) == row["totals"][key], key

    def test_virman_is_not_external_collection(self, db):
        _seed(db)
        db.add(SalesCollection(
            customer_code="120.99.99.9901",
            customer_name="AFİN TEST TURİZM A.Ş.",
            collection_date=date(2026, 5, 2),
            amount=50,
            currency="EUR",
            amount_currency=50,
            description="120-340 VİRMAN",
            tx_hash="agency-finance-virman",
        ))
        db.flush()
        _invalidate_compute_cache()

        result = compute_agency_finance(db, 2026, today=self.TODAY)
        row = next(item for item in result["agencies"] if item["agency"] == "AFİN TEST ACENTE")
        assert row["months"][4]["collections"] == 0
        assert row["totals"]["collections"] == 200


class TestAgencyFinanceAPI:
    def test_requires_authentication(self, client):
        assert client.get(f"{API}/?year=2026").status_code == 401

    def test_payload_shape(self, client, auth_headers, db):
        _seed(db)
        response = client.get(f"{API}/?year=2026", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["currency"] == "EUR"
        assert len(body["months"]) == 12
        assert body["agencies"]
        assert set((
            "advance_received", "collections", "reservation_amount", "overdue",
            "invoiced_amount", "month_end_receivable",
        )).issubset(body["totals"])


class TestAgencyFinanceFxDates:
    """Kur tarihi kuralı (2026-09-01, denetim O1): akışlar hareketin KENDİ tarihindeki kurla,
    avans havuzu / açık alacak BUGÜNKÜ kurla; kur bulunamayan hareket 0 + `skipped_no_rate`."""
    TODAY = date(2026, 7, 15)

    def _rates(self, db, eur, usd=()):
        from app.models.exchange_rate import ExchangeRate
        db.query(ExchangeRate).filter(
            ExchangeRate.currency_code.in_(("EUR", "USD"))
        ).delete(synchronize_session=False)
        for dt, value in eur:
            db.add(ExchangeRate(date=dt, currency_code="EUR", unit=1,
                                forex_buying=value, forex_selling=value))
        for dt, value in usd:
            db.add(ExchangeRate(date=dt, currency_code="USD", unit=1,
                                forex_buying=value, forex_selling=value))
        db.flush()

    def _seed_fx(self, db):
        group = AgencyGroup(name="AFX TEST ACENTE", members=["AFX PMS"], term_days=30,
                            kickback_percent=0)
        db.add(group)
        db.flush()
        db.add(AgencyCodeMap(pms_name="AFX PMS", acc_code="120.99.99.9902"))
        db.add_all([
            # TL tahsilat Ocak: 4.000 TL → Ocak kuru 40 → 100 € (bugünkü 50 ile 80 DEĞİL)
            SalesCollection(
                customer_code="120.99.99.9902", customer_name="AFX TEST TURİZM A.Ş.",
                collection_date=date(2026, 1, 20), amount=4000, currency="TL",
                amount_currency=4000, description="Havale", tx_hash="afx-col-1",
            ),
            # TL avans Ocak: 8.000 TL → akış 200 € (kur 40); havuza bugünkü kurla 160 €
            SalesAdvanceTransaction(
                sedna_rec_id=990101, code="340.99.99.9902", name="AFX TEST TURİZM A.Ş.",
                transaction_date=date(2026, 1, 10), currency="TL",
                received=8000, consumed=0, received_tl=8000, consumed_tl=0,
            ),
            # USD avans Şubat: 100 $ → akış 100 × 30 / 40 = 75 € (çapraz, Şubat kuru);
            # havuza bugünkü kurla 100 × 35 / 50 = 70 €
            SalesAdvanceTransaction(
                sedna_rec_id=990102, code="340.99.99.9903", name="AFX TEST TURİZM A.Ş.",
                transaction_date=date(2026, 2, 10), currency="USD",
                received=100, consumed=0, received_tl=3000, consumed_tl=0,
            ),
            # İleri rezervasyon (çıkış 15 Ağu + 30 gün vade = 14 Eyl): havuz buna mahsup edilir
            Reservation(
                rec_id=9999002, agency="AFX PMS", checkin_date=date(2026, 8, 10),
                checkout_date=date(2026, 8, 15), record_date=date(2026, 2, 1),
                nights=5, rooms=1, eur_total=1000,
            ),
        ])
        db.flush()
        _invalidate_compute_cache()

    def test_flows_use_transaction_date_rate_and_pool_uses_today(self, db):
        self._rates(db, eur=[(date(2026, 1, 1), 40), (date(2026, 4, 1), 50)],
                    usd=[(date(2026, 1, 1), 30), (date(2026, 4, 1), 35)])
        self._seed_fx(db)
        result = compute_agency_finance(db, 2026, today=self.TODAY)
        row = next(r for r in result["agencies"] if r["agency"] == "AFX TEST ACENTE")
        months = {m["month"]: m for m in row["months"]}

        assert months[1]["collections"] == 100          # 4.000 / 40 — bugünkü 50 ile 80 olurdu
        assert months[1]["advance_received"] == 200     # 8.000 / 40
        assert months[2]["advance_received"] == 75      # 100 × 30 / 40 (çapraz, Şubat)
        # Havuz (stok) bugünkü kurla: 8.000/50 = 160 + 100×35/50 = 70 → 230 €
        assert months[9]["projected_gross"] == 1000
        assert months[9]["projected_advance"] == 230
        assert months[9]["projected_due"] == 770
        assert result["source_counts"]["skipped_no_rate"] == 0
        assert result["eur_rate"] == 50

    def test_missing_rate_skips_and_counts(self, db):
        """Kur geçmişi 1 Mart'ta başlıyor → Ocak/Şubat hareketleri çevrilemez: 0 + sayaç
        (1 TL = 1 EUR varsayımı YOK); havuz yine bugünkü kurla hesaplanır."""
        self._rates(db, eur=[(date(2026, 3, 1), 50)], usd=[(date(2026, 3, 1), 35)])
        self._seed_fx(db)
        result = compute_agency_finance(db, 2026, today=self.TODAY)
        row = next(r for r in result["agencies"] if r["agency"] == "AFX TEST ACENTE")
        months = {m["month"]: m for m in row["months"]}

        assert months[1]["collections"] == 0
        assert months[1]["advance_received"] == 0
        assert months[2]["advance_received"] == 0   # ne çapraz ne EUR kuru var
        assert result["source_counts"]["skipped_no_rate"] == 3
        assert months[9]["projected_advance"] == 230
