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

    def test_import_auto_matches_existing_bank_tx(self, client, auth_headers, db):
        """Boşluk kapandı: ekstre ÖNCE yüklenmişse, import edilen çek otomatik eşleşir (paid)."""
        import uuid
        from app.models.bank_account import BankAccount
        from app.models.bank_transaction import BankTransaction
        acc = BankAccount(bank_name="Halkbank", iban="TR" + uuid.uuid4().hex[:30].upper(), currency="TRY")
        db.add(acc)
        db.flush()
        db.add(BankTransaction(
            account_id=acc.id, date=date(2026, 5, 12), description="ÇEK : CHKAUTO1 odeme",
            amount=-5000, type="expense", tx_hash=uuid.uuid4().hex,
        ))
        db.flush()
        row = [{"vendor_code": "320.99.02.0001", "vendor_name": "AUTO CARİ", "check_no": "CHKAUTO1",
                "bank": "Halkbank", "city": None, "due_date": date(2026, 5, 10),
                "amount_tl": 5000, "currency": "TL", "amount_currency": 5000, "max_pos": 100}]
        with patch(f"{TARGET}.sedna_configured", return_value=True), \
             patch(f"{TARGET}.fetch_issued_checks", return_value=row):
            j = client.post(f"{PREFIX}/sedna-import", headers=auth_headers).json()
            assert j["new_checks"] == 1 and j["matched_to_bank"] >= 1
            r = db.execute(text("SELECT status, bank_transaction_id FROM checks WHERE check_no='CHKAUTO1'")).first()
            assert r[0] == "paid" and r[1] is not None   # Sedna pending dese de banka kanıtı → paid

    def test_reschedule_updates_not_duplicates(self, client, auth_headers, db):
        """Vade değişen çek (aynı no+cari+tutar) → YENİ kayıt değil GÜNCELLEME (mükerrer olmaz)."""
        base = {"vendor_code": "320.77.01.0001", "vendor_name": "RESC CARİ", "check_no": "RESCHK1",
                "bank": "YAPI KREDI", "city": None, "amount_tl": 92000, "currency": "TL",
                "amount_currency": 92000, "max_pos": 100}
        with patch(f"{TARGET}.sedna_configured", return_value=True):
            with patch(f"{TARGET}.fetch_issued_checks", return_value=[dict(base, due_date=date(2026, 6, 2))]):
                j1 = client.post(f"{PREFIX}/sedna-import", headers=auth_headers).json()
            assert j1["new_checks"] == 1
            # Sedna'da vade 02.06 → 31.07 değişti
            with patch(f"{TARGET}.fetch_issued_checks", return_value=[dict(base, due_date=date(2026, 7, 31))]):
                j2 = client.post(f"{PREFIX}/sedna-import", headers=auth_headers).json()
            assert j2["new_checks"] == 0 and j2["updated_checks"] == 1
        rows = db.execute(text("SELECT due_date FROM checks WHERE check_no='RESCHK1'")).fetchall()
        assert len(rows) == 1 and str(rows[0][0]) == "2026-07-31"   # tek kayıt, güncel vade

    def test_same_number_different_amount_kept_separate(self, client, auth_headers, db):
        """Aynı çek no + cari ama FARKLI tutar → iki ayrı gerçek çek (birleştirilmez)."""
        rows = [
            {"vendor_code": "320.77.02.0001", "vendor_name": "X", "check_no": "DUPNO1", "bank": None,
             "city": None, "due_date": date(2026, 4, 30), "amount_tl": 900000, "currency": "TL",
             "amount_currency": 900000, "max_pos": 100},
            {"vendor_code": "320.77.02.0001", "vendor_name": "X", "check_no": "DUPNO1", "bank": None,
             "city": None, "due_date": date(2026, 5, 30), "amount_tl": 969000, "currency": "TL",
             "amount_currency": 969000, "max_pos": 100},
        ]
        with patch(f"{TARGET}.sedna_configured", return_value=True), \
             patch(f"{TARGET}.fetch_issued_checks", return_value=rows):
            j = client.post(f"{PREFIX}/sedna-import", headers=auth_headers).json()
        assert j["new_checks"] == 2
        assert db.execute(text("SELECT count(*) FROM checks WHERE check_no='DUPNO1'")).scalar() == 2

    def test_heals_existing_unmatched_dupe(self, client, auth_headers, db):
        """Önceden (vade değişiminden) oluşmuş eşleşmemiş mükerrer → import temizler, tek kayıt kalır."""
        from app.models.check import Check, CheckUpload
        up = CheckUpload(file_name="seed", file_url="x")
        db.add(up)
        db.flush()
        for dd in (date(2026, 6, 2), date(2026, 7, 31)):
            db.add(Check(upload_id=up.id, check_no="HEALCHK", vendor_code="320.77.03.0001",
                         vendor_name="H", due_date=dd, amount_tl=50000, currency="TL",
                         amount_currency=50000, transaction_type="Verilen Çek", status="pending"))
        db.flush()
        row = [{"vendor_code": "320.77.03.0001", "vendor_name": "H", "check_no": "HEALCHK", "bank": None,
                "city": None, "due_date": date(2026, 7, 31), "amount_tl": 50000, "currency": "TL",
                "amount_currency": 50000, "max_pos": 100}]
        with patch(f"{TARGET}.sedna_configured", return_value=True), \
             patch(f"{TARGET}.fetch_issued_checks", return_value=row):
            j = client.post(f"{PREFIX}/sedna-import", headers=auth_headers).json()
        assert j["removed_dupes"] == 1
        rows = db.execute(text("SELECT due_date FROM checks WHERE check_no='HEALCHK'")).fetchall()
        assert len(rows) == 1 and str(rows[0][0]) == "2026-07-31"

    def test_constraint_collision_skipped_not_crash(self, client, auth_headers, db):
        """Aynı (no,cari,vade) farklı tutar → UNIQUE çakışır; o satır SAVEPOINT'le atlanır, import çökmez."""
        from app.models.check import Check, CheckUpload
        up = CheckUpload(file_name="seed", file_url="x")
        db.add(up)
        db.flush()
        db.add(Check(upload_id=up.id, check_no="COLCHK", vendor_code="320.88.01.0001", vendor_name="C",
                     due_date=date(2026, 7, 31), amount_tl=100000, currency="TL", amount_currency=100000,
                     transaction_type="Verilen Çek", status="pending"))
        db.flush()
        rows = [
            {"vendor_code": "320.88.01.0001", "vendor_name": "C", "check_no": "COLCHK", "bank": None,
             "city": None, "due_date": date(2026, 7, 31), "amount_tl": 200000, "currency": "TL",
             "amount_currency": 200000, "max_pos": 100},   # (COLCHK,vendor,07-31) çakışır → atlanır
            {"vendor_code": "320.88.01.0002", "vendor_name": "D", "check_no": "OKCHK", "bank": None,
             "city": None, "due_date": date(2026, 8, 1), "amount_tl": 5000, "currency": "TL",
             "amount_currency": 5000, "max_pos": 100},     # sorunsuz → eklenir
        ]
        with patch(f"{TARGET}.sedna_configured", return_value=True), \
             patch(f"{TARGET}.fetch_issued_checks", return_value=rows):
            r = client.post(f"{PREFIX}/sedna-import", headers=auth_headers)
            assert r.status_code == 200, r.text          # çökmedi
            j = r.json()
        assert j["new_checks"] == 1                       # yalnız OKCHK
        assert db.execute(text("SELECT count(*) FROM checks WHERE check_no='OKCHK'")).scalar() == 1
        assert db.execute(text("SELECT count(*) FROM checks WHERE check_no='COLCHK'")).scalar() == 1
