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
