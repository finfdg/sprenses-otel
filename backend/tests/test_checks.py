"""Çek modülü CRUD testleri.

Endpoint'ler: /api/finance/checks/
Not: Upload testi Excel dosyası gerektirdiğinden burada liste, özet ve durum testleri yapılır.
"""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import text

PREFIX = "/api/finance/checks"
TARGET = "app.routers.finance.checks"


# ─── LIST ────────────────────────────────────────────────────


class TestCheckList:

    def test_list_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data

    def test_list_with_filters(self, client, auth_headers):
        """Filtreler ile listeleme — hata vermemeli."""
        resp = client.get(f"{PREFIX}/?status=pending&currency=TL", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_with_search(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?search=test", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_with_sort(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?sort_by=due_date&sort_order=asc", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_pagination(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?page=1&page_size=5", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) <= 5

    def test_list_without_auth(self, client):
        resp = client.get(f"{PREFIX}/")
        assert resp.status_code in (401, 403)


# ─── SUMMARY ─────────────────────────────────────────────────


class TestCheckSummary:

    def test_summary_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Yapısal alanlar mevcut olmalı
        assert "total_count" in data
        assert "total_amount" in data
        assert "pending_count" in data
        assert "pending_amount" in data

    def test_summary_without_auth(self, client):
        resp = client.get(f"{PREFIX}/summary")
        assert resp.status_code in (401, 403)


# ─── UPLOADS ─────────────────────────────────────────────────


class TestCheckUploads:

    def test_list_uploads(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/uploads", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_delete_upload_not_found(self, client, auth_headers):
        resp = client.delete(f"{PREFIX}/uploads/999999", headers=auth_headers)
        assert resp.status_code == 404


# ─── STATUS UPDATE ───────────────────────────────────────────


class TestCheckStatus:

    def test_status_update_not_found(self, client, auth_headers):
        resp = client.patch(
            f"{PREFIX}/999999/status?new_status=cancelled",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ─── SEDNA İÇE AKTARMA (verilen çek) ─────────────────────────

FAKE_CHECK_ROWS = [
    {"vendor_code": "320.99.01.0001", "vendor_name": "TEST CARİ A", "check_no": "CHK001",
     "bank": "YAPI KREDI", "city": "ANTALYA", "due_date": date(2026, 9, 30),
     "amount_tl": 1000, "currency": "TL", "amount_currency": 1000, "max_pos": 100},   # pending
    {"vendor_code": "320.99.01.0002", "vendor_name": "TEST CARİ B", "check_no": "CHK002",
     "bank": "GARANTI", "city": None, "due_date": date(2026, 10, 14),
     "amount_tl": 2500, "currency": "TL", "amount_currency": 2500, "max_pos": 101},   # paid
    {"vendor_code": "320.99.01.0003", "vendor_name": "TEST C", "check_no": "CHK003",
     "bank": None, "city": None, "due_date": date(2026, 8, 1),
     "amount_tl": 600, "currency": "EUR", "amount_currency": 15, "max_pos": 103},     # cancelled, EUR
]


class TestSednaCheckImport:

    def test_requires_use(self, client, viewer_user_headers):
        assert client.post(f"{PREFIX}/sedna-import", headers=viewer_user_headers).status_code == 403

    def test_not_configured_503(self, client, auth_headers):
        with patch(f"{TARGET}.sedna_configured", return_value=False):
            assert client.post(f"{PREFIX}/sedna-import", headers=auth_headers).status_code == 503

    def test_import_status_mapping_dedup_and_sync(self, client, auth_headers, db):
        with patch(f"{TARGET}.sedna_configured", return_value=True), \
             patch(f"{TARGET}.fetch_issued_checks", return_value=FAKE_CHECK_ROWS):
            r = client.post(f"{PREFIX}/sedna-import", headers=auth_headers)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["new_checks"] == 3 and j["total_fetched"] == 3

            rows = {x[0]: x for x in db.execute(text(
                "SELECT check_no, status, currency, amount_currency, transaction_type, description "
                "FROM checks WHERE check_no IN ('CHK001','CHK002','CHK003')"
            )).fetchall()}
            assert rows["CHK001"][1] == "pending"
            assert rows["CHK002"][1] == "paid"
            assert rows["CHK003"][1] == "cancelled" and rows["CHK003"][2] == "EUR" and float(rows["CHK003"][3]) == 15.0
            assert rows["CHK001"][4] == "Verilen Çek" and rows["CHK001"][5] == "YAPI KREDI"  # banka açıklamada

            # paid çek → finance_event is_realized=True
            assert db.execute(text(
                "SELECT is_realized FROM finance_events WHERE source_type='check' "
                "AND check_no='CHK002'"
            )).scalar() is True
            # cancelled çek → finance_event YOK (hayalet bekleyen gider olmasın)
            assert db.execute(text(
                "SELECT count(*) FROM finance_events WHERE source_type='check' AND check_no='CHK003'"
            )).scalar() == 0

            # RE-RUN aynı veri → hepsi mevcut, değişiklik yok
            j2 = client.post(f"{PREFIX}/sedna-import", headers=auth_headers).json()
            assert j2["new_checks"] == 0 and j2["updated_checks"] == 0

            # CHK001 Sedna'da ödenmiş (max_pos=101) → durum senkronize (pending→paid)
            changed = [dict(FAKE_CHECK_ROWS[0], max_pos=101)]
            with patch(f"{TARGET}.fetch_issued_checks", return_value=changed):
                j3 = client.post(f"{PREFIX}/sedna-import", headers=auth_headers).json()
            assert j3["updated_checks"] == 1
            assert db.execute(text("SELECT status FROM checks WHERE check_no='CHK001'")).scalar() == "paid"
