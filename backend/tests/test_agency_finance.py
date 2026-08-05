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
