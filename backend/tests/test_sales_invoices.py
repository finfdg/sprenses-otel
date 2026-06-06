"""Otel satış faturaları (120) — Sedna içe aktarma + FIFO tahsil durumu testleri.

fetch_sales_invoices mock'lanır. FIFO: müşteri bazında tahsilat faturalara en eskiden düşülür.
"""
from datetime import date
from unittest.mock import patch

import pytest

PREFIX = "/api/finance/sales-invoices"
TARGET = "app.routers.finance.sales_invoices"

FAKE = {
    "invoices": [
        {"customer_code": "120.03.01.0001", "customer_name": "MÜNFERİT GENEL",
         "invoice_date": date(2026, 1, 5), "invoice_no": "INV1", "amount": 1000, "aciklama": "a"},
        {"customer_code": "120.03.01.0001", "customer_name": "MÜNFERİT GENEL",
         "invoice_date": date(2026, 2, 5), "invoice_no": "INV2", "amount": 2000, "aciklama": "b"},
        {"customer_code": "120.24.01.0001", "customer_name": "WEBRES TURİZM",
         "invoice_date": date(2026, 1, 10), "invoice_no": "INV3", "amount": 500, "aciklama": "c"},
    ],
    "collections": [
        {"customer_code": "120.03.01.0001", "collection_date": date(2026, 3, 1),
         "amount": 1500, "aciklama": "tahsil", "fis_no": 99},
    ],
}


def _import(client, headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_sales_invoices", return_value=FAKE):
        return client.post(f"{PREFIX}/sedna-import", headers=headers)


def test_sedna_import_requires_use(client, viewer_user_headers):
    assert client.post(f"{PREFIX}/sedna-import", headers=viewer_user_headers).status_code == 403


def test_import_creates_and_dedups(client, auth_headers):
    r = _import(client, auth_headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["invoices_new"] == 3 and j["collections_new"] == 1
    # re-run → dedup
    j2 = _import(client, auth_headers).json()
    assert j2["invoices_new"] == 0 and j2["collections_new"] == 0 and j2["invoices_skipped"] == 3


def test_fifo_status_and_summary(client, auth_headers):
    _import(client, auth_headers)
    # özet: müşteri bazında FIFO
    s = client.get(f"{PREFIX}/summary", headers=auth_headers).json()
    assert s["total"]["invoiced"] == 3500.0 and s["total"]["collected"] == 1500.0
    assert s["total"]["outstanding"] == 2000.0
    assert s["munferit"]["invoiced"] == 3000.0 and s["munferit"]["collected"] == 1500.0
    assert s["agency"]["invoiced"] == 500.0 and s["agency"]["collected"] == 0.0
    assert s["status_counts"] == {"paid": 1, "partial": 1, "open": 1}

    # liste: INV1 paid (1000/1000), INV2 partial (500/2000), INV3 open
    items = {it["invoice_no"]: it for it in client.get(f"{PREFIX}/", headers=auth_headers).json()["items"]}
    assert items["INV1"]["status"] == "paid" and items["INV1"]["collected"] == 1000.0
    assert items["INV2"]["status"] == "partial" and items["INV2"]["collected"] == 500.0 and items["INV2"]["remaining"] == 1500.0
    assert items["INV3"]["status"] == "open" and items["INV3"]["collected"] == 0.0


def test_filters_type_and_status(client, auth_headers):
    _import(client, auth_headers)
    # münferit/acente ayrımı
    assert client.get(f"{PREFIX}/?customer_type=munferit", headers=auth_headers).json()["total"] == 2
    ag = client.get(f"{PREFIX}/?customer_type=agency", headers=auth_headers).json()
    assert ag["total"] == 1 and ag["items"][0]["invoice_no"] == "INV3"
    assert ag["items"][0]["is_munferit"] is False
    # durum filtresi
    assert client.get(f"{PREFIX}/?status=open", headers=auth_headers).json()["total"] == 1
    assert client.get(f"{PREFIX}/?status=paid", headers=auth_headers).json()["total"] == 1


FAKE_ADV = {
    "invoices": [
        {"customer_code": "120.02.01.0099", "customer_name": "AVANS ACENTE",
         "invoice_date": date(2026, 2, 1), "invoice_no": "AINV1", "amount": 1000, "aciklama": "a"},
        {"customer_code": "120.02.01.0099", "customer_name": "AVANS ACENTE",
         "invoice_date": date(2026, 3, 1), "invoice_no": "AINV2", "amount": 200, "aciklama": "b"},
    ],
    "collections": [  # AVANS önce yatırıldı (faturalardan ÖNCE) → faturalar avansla kapanır
        {"customer_code": "120.02.01.0099", "customer_name": "AVANS ACENTE",
         "collection_date": date(2026, 1, 1), "amount": 1500, "aciklama": "avans", "fis_no": 1},
    ],
}


def test_advance_balance_and_by_advance(client, auth_headers):
    """Avans faturadan ÖNCE yatınca: faturalar 'avansla kapandı' + kalan avans bakiyesi."""
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_sales_invoices", return_value=FAKE_ADV):
        assert client.post(f"{PREFIX}/sedna-import", headers=auth_headers).status_code == 200

    # faturalar avansla kapandı (FIFO tarih-sıralı: önce avans havuzu)
    items = {it["invoice_no"]: it for it in client.get(f"{PREFIX}/", headers=auth_headers).json()["items"]}
    assert items["AINV1"]["status"] == "paid" and items["AINV1"]["by_advance"] is True
    assert items["AINV2"]["status"] == "paid" and items["AINV2"]["by_advance"] is True

    # avans bakiyesi: 1500 yatırılan - 1200 fatura = 300 kalan (TL)
    adv = client.get(f"{PREFIX}/advances", headers=auth_headers).json()
    assert adv["count"] == 1 and adv["total_by_currency"]["TL"] == 300.0
    row = adv["items"][0]
    assert row["customer_code"] == "120.02.01.0099" and row["customer_name"] == "AVANS ACENTE"
    assert row["currency"] == "TL"
    assert row["total_collected"] == 1500.0 and row["consumed"] == 1200.0 and row["net_advance"] == 300.0

    # özette de avans bakiyesi (para birimi bazlı)
    s = client.get(f"{PREFIX}/summary", headers=auth_headers).json()
    assert s["advance"]["by_currency"]["TL"] == 300.0 and s["advance"]["agency_count"] == 1


FAKE_EUR = {
    "invoices": [
        {"customer_code": "120.01.02.A001", "customer_name": "ALLTOURS", "invoice_date": date(2026, 2, 1),
         "invoice_no": "EUR1", "amount": 35000, "currency": "EUR", "amount_currency": 1000, "aciklama": "x"},
    ],
    "collections": [  # EUR avans önce
        {"customer_code": "120.01.02.A001", "customer_name": "ALLTOURS", "collection_date": date(2026, 1, 1),
         "amount": 54000, "currency": "EUR", "amount_currency": 1500, "fis_no": 1, "aciklama": "avans"},
    ],
}


def test_eur_currency_per_currency_fifo(client, auth_headers):
    """EUR avans EUR faturayı kapatır; bakiye EUR olarak raporlanır (TL'ye karışmaz)."""
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_sales_invoices", return_value=FAKE_EUR):
        client.post(f"{PREFIX}/sedna-import", headers=auth_headers)
    it = client.get(f"{PREFIX}/?search=EUR1", headers=auth_headers).json()["items"][0]
    assert it["currency"] == "EUR" and it["amount"] == 1000.0 and it["amount_tl"] == 35000.0
    assert it["status"] == "paid" and it["by_advance"] is True   # EUR avansla kapandı
    # avans EUR olarak: 1500 - 1000 = 500 EUR
    adv = client.get(f"{PREFIX}/advances", headers=auth_headers).json()
    eur = [x for x in adv["items"] if x["currency"] == "EUR"]
    assert eur and eur[0]["net_advance"] == 500.0 and eur[0]["customer_name"] == "ALLTOURS"
    assert adv["total_by_currency"]["EUR"] == 500.0


def test_same_day_payment_not_advance(client, auth_headers):
    """Aynı gün ödeme (münferit walk-in) avans sayılmaz — by_advance False."""
    same = {
        "invoices": [{"customer_code": "120.03.01.0001", "customer_name": "MÜNFERİT GENEL",
                      "invoice_date": date(2026, 4, 1), "invoice_no": "SD1", "amount": 500, "aciklama": "x"}],
        "collections": [{"customer_code": "120.03.01.0001", "customer_name": "MÜNFERİT GENEL",
                         "collection_date": date(2026, 4, 1), "amount": 500, "aciklama": "nakit", "fis_no": 7}],
    }
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_sales_invoices", return_value=same):
        client.post(f"{PREFIX}/sedna-import", headers=auth_headers)
    it = client.get(f"{PREFIX}/?search=SD1", headers=auth_headers).json()["items"][0]
    assert it["status"] == "paid" and it["by_advance"] is False  # aynı gün = normal tahsilat


def test_central_sync_includes_sales(client, auth_headers, db):
    """Merkezi Sedna sync satış faturası adımını da çalıştırır."""
    from app.config import settings
    with patch.object(settings, "sedna_password", "x"), \
         patch("app.routers.finance.cariler.sedna_import.fetch_cari_transactions", return_value=[]), \
         patch("app.routers.finance.cariler.sedna_import.fetch_vendor_ibans", return_value=[]), \
         patch("app.routers.finance.checks.fetch_issued_checks", return_value=[]), \
         patch(f"{TARGET}.fetch_sales_invoices", return_value=FAKE):
        j = client.post("/api/finance/sedna/sync-all", headers=auth_headers).json()
        keys = {s["key"] for s in j["steps"]}
        assert "sales_invoices" in keys
        sales = next(s for s in j["steps"] if s["key"] == "sales_invoices")
        assert sales["ok"] and "fatura" in sales["summary"]
