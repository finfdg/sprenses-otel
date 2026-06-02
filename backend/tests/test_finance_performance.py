"""Finans modülü performans, güvenlik ve eş zamanlılık testleri.

Test kategorileri:
  1. Eş zamanlılık (25 kullanıcı simülasyonu)
  2. Güvenlik (dosya yükleme doğrulama, rate limiting)
  3. Performans (N+1, büyük veri seti)
  4. Veri bütünlüğü (match_number, race condition)
  5. Connection pool
"""

import concurrent.futures
import io
import os
import threading
import time
from typing import List

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TestSessionLocal, extract_token
from app.main import app
from app.middleware.rate_limit import heavy_limiter, login_limiter
from app.models.finance_event import FinanceEvent
from app.models.bank_account import BankAccount
from app.utils.finance_event_service import finance_event_svc


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def _get_token() -> str:
    """Test için admin token üret (rate limiter sıfırlanarak)."""
    login_limiter._requests.clear()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, f"Login başarısız: {r.text}"
    return extract_token(r)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ─── 1. Eş Zamanlılık Testleri ───────────────────────────────────────────────

class TestConcurrency:
    """25 eş zamanlı kullanıcı simülasyonu.

    Concurrent thread'ler tek session paylaşamaz → rollback fixture devre dışı.
    """

    @pytest.fixture(autouse=True)
    def _disable_rollback_for_concurrency(self):
        """Concurrency testleri için rollback fixture'ını devre dışı bırak."""
        from app.database import get_db as _get_db
        original = app.dependency_overrides.get(_get_db)
        app.dependency_overrides.pop(_get_db, None)
        yield
        if original:
            app.dependency_overrides[_get_db] = original

    def test_25_concurrent_cash_flow_requests(self):
        """25 eş zamanlı nakit akım listesi isteği — hepsi 200 veya 429 dönmeli."""
        heavy_limiter._requests.clear()
        token = _get_token()
        errors = []

        def make_request(_):
            c = _make_client()
            r = c.get("/api/finance/cash-flow/?page=1&page_size=50", headers=_auth(token))
            if r.status_code not in (200, 429):
                errors.append(f"Beklenmeyen status: {r.status_code} — {r.text[:100]}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as pool:
            list(pool.map(make_request, range(25)))

        assert len(errors) == 0, f"Hatalar: {errors}"

    def test_10_concurrent_summary_requests(self):
        """10 eş zamanlı özet isteği — veri tutarlılığı."""
        token = _get_token()
        results = []

        def fetch_summary(_):
            c = _make_client()
            r = c.get("/api/finance/cash-flow/summary", headers=_auth(token))
            if r.status_code == 200:
                results.append(r.json())

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(fetch_summary, range(10)))

        assert len(results) >= 8, f"Yalnızca {len(results)}/10 istek başarılı"

        # Tüm sonuçlar aynı balance değerini döndürmeli (tutarsız okuma yok)
        if len(results) > 1:
            first_balance = results[0].get("balance")
            for r in results[1:]:
                assert r.get("balance") == first_balance, \
                    f"Tutarsız bakiye: {first_balance} vs {r.get('balance')}"

    def test_concurrent_bank_account_creation_iban_uniqueness(self):
        """5 eş zamanlı aynı IBAN ile hesap oluşturma — yalnızca 1 başarılı olmalı."""
        test_iban = "TR000000000000000000000001"
        token = _get_token()

        # Varsa temizle
        db = TestSessionLocal()
        try:
            db.query(BankAccount).filter(BankAccount.iban == test_iban).delete()
            db.commit()
        finally:
            db.close()

        successes = []
        errors_400 = []

        def create_account(_):
            c = _make_client()
            r = c.post("/api/finance/banks/accounts/", headers=_auth(token), json={
                "bank_name": "Test Bankası",
                "iban": test_iban,
                "currency": "TRY",
                "holder_name": "Test",
                "branch_name": None,
                "account_no": None,
                "blocked_amount": None,
            })
            if r.status_code == 201:
                successes.append(r.json())
            elif r.status_code == 400:
                errors_400.append(r.json())

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(create_account, range(5)))

        # Temizle (gerçek DB'ye yazıldı — rollback fixture devre dışı)
        db = TestSessionLocal()
        try:
            db.query(BankAccount).filter(BankAccount.iban == test_iban).delete()
            db.commit()
        finally:
            db.close()

        assert len(successes) == 1, f"Yalnızca 1 hesap oluşturulmalı, {len(successes)} oluşturuldu"
        assert len(errors_400) == 4, f"Geri kalan 4 istek 400 dönmeli, {len(errors_400)} döndü"


# ─── 2. Güvenlik Testleri ────────────────────────────────────────────────────

class TestFileSecurity:
    """Dosya yükleme güvenlik doğrulamaları."""

    def _fake_excel_as_pdf(self) -> bytes:
        """İçeriği Excel olan ama uzantısı .pdf olan sahte dosya."""
        return b"\x50\x4B\x03\x04" + b"\x00" * 100  # Excel magic bytes

    def _fake_pdf_as_excel(self) -> bytes:
        """İçeriği metin olan ama uzantısı .xlsx olan sahte dosya."""
        return b"This is not an Excel file"

    def _real_pdf_header(self) -> bytes:
        """%PDF başlıklı minimal içerik."""
        return b"%PDF-1.4\n%some content"

    def test_fake_excel_extension_rejected(self, client, auth_headers):
        """PDF içerikli .xlsx dosyası reddedilmeli."""
        r = client.post(
            "/api/finance/checks/upload",
            headers=auth_headers,
            files={"file": ("test.xlsx", io.BytesIO(self._fake_pdf_as_excel()), "application/octet-stream")},
        )
        assert r.status_code == 400, f"Sahte Excel kabul edildi: {r.text}"
        assert "uzantısıyla uyuşmuyor" in r.json().get("detail", "") or \
               "uyuşmuyor" in r.json().get("detail", "")

    def test_empty_file_rejected(self, client, auth_headers):
        """Boş dosya reddedilmeli."""
        r = client.post(
            "/api/finance/checks/upload",
            headers=auth_headers,
            files={"file": ("test.xlsx", io.BytesIO(b""), "application/octet-stream")},
        )
        assert r.status_code == 400
        assert "boş" in r.json().get("detail", "").lower()

    def test_wrong_extension_rejected(self, client, auth_headers):
        """İzin verilmeyen uzantı reddedilmeli."""
        r = client.post(
            "/api/finance/checks/upload",
            headers=auth_headers,
            files={"file": ("test.exe", io.BytesIO(b"MZ\x90\x00" * 10), "application/octet-stream")},
        )
        assert r.status_code == 400
        assert "İzin verilmeyen" in r.json().get("detail", "") or \
               "uzantı" in r.json().get("detail", "").lower()

    def test_pdf_endpoint_rejects_excel(self, client, auth_headers):
        """PDF endpoint'i Excel dosyasını reddedilmeli."""
        # CC statement auto-upload için PDF beklenir
        r = client.post(
            "/api/finance/krediler/kart/auto-upload",
            headers=auth_headers,
            files={"file": ("test.xlsx", io.BytesIO(b"\x50\x4B\x03\x04" + b"\x00" * 50), "application/octet-stream")},
        )
        assert r.status_code == 400

    def test_excel_endpoint_rejects_pdf(self, client, auth_headers):
        """Excel endpoint'i PDF dosyasını reddedilmeli."""
        r = client.post(
            "/api/finance/checks/upload",
            headers=auth_headers,
            files={"file": ("test.pdf", io.BytesIO(self._real_pdf_header()), "application/pdf")},
        )
        assert r.status_code == 400

    def test_unauthorized_access_rejected(self, client):
        """Token olmadan istek 401 dönmeli."""
        r = client.get("/api/finance/cash-flow/")
        assert r.status_code == 401

    def test_internal_endpoint_blocked_from_outside(self, client, auth_headers):
        """Internal broadcast endpoint dışarıdan erişilememeli."""
        r = client.post(
            "/api/internal/broadcast-finance-update",
            headers={**auth_headers, "X-Internal-Secret": "herhangi-bir-deger"},
        )
        # TestClient localhost'tan bağlanır, bu yüzden IP kontrolü geçer
        # Ama secret yanlış olduğunda 403 dönmeli
        assert r.status_code in (403, 422)


# ─── 3. Performans Testleri ──────────────────────────────────────────────────

class TestPerformance:
    """Sorgu performansı ve N+1 tespiti."""

    def test_cash_flow_query_time(self, client, auth_headers):
        """Nakit akım listesi 2 saniyeden hızlı yanıt vermeli."""
        heavy_limiter._requests.clear()
        start = time.time()
        r = client.get(
            "/api/finance/cash-flow/?page=1&page_size=100",
            headers=auth_headers,
        )
        elapsed = time.time() - start

        assert r.status_code == 200
        assert elapsed < 2.0, f"Yavaş sorgu: {elapsed:.2f}s (limit: 2.0s)"

    def test_cash_flow_summary_query_time(self, client, auth_headers):
        """Özet sorgusu 1 saniyeden hızlı olmalı."""
        start = time.time()
        r = client.get("/api/finance/cash-flow/summary", headers=auth_headers)
        elapsed = time.time() - start

        assert r.status_code == 200
        assert elapsed < 1.0, f"Yavaş özet: {elapsed:.2f}s (limit: 1.0s)"

    def test_bank_accounts_list_query_time(self, client, auth_headers):
        """Banka hesap listesi 1 saniyeden hızlı olmalı."""
        start = time.time()
        r = client.get("/api/finance/banks/accounts/", headers=auth_headers)
        elapsed = time.time() - start

        assert r.status_code == 200
        assert elapsed < 1.0, f"Yavaş banka listesi: {elapsed:.2f}s"

    def test_krediler_list_query_time(self, client, auth_headers):
        """Kredi listesi 1 saniyeden hızlı olmalı (joinedload N+1 engeli ile)."""
        start = time.time()
        r = client.get("/api/finance/krediler/?page_size=50", headers=auth_headers)
        elapsed = time.time() - start

        assert r.status_code == 200
        assert elapsed < 1.0, f"Yavaş kredi listesi: {elapsed:.2f}s"

    def test_mobile_dashboard_query_time(self, client, auth_headers):
        """Mobil dashboard özet 1.5 saniyeden hızlı olmalı."""
        heavy_limiter._requests.clear()
        start = time.time()
        r = client.get("/api/finance/cash-flow/mobile-dashboard", headers=auth_headers)
        elapsed = time.time() - start

        assert r.status_code == 200
        assert elapsed < 1.5, f"Yavaş mobil dashboard: {elapsed:.2f}s"

    def test_pagination_response_format(self, client, auth_headers):
        """Sayfalama formatı doğru olmalı."""
        heavy_limiter._requests.clear()
        r = client.get("/api/finance/cash-flow/?page=1&page_size=10", headers=auth_headers)
        assert r.status_code == 200

        data = r.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert len(data["items"]) <= 10

    def test_page_size_limit_enforced(self, client, auth_headers):
        """page_size 500'den büyük olamaz."""
        heavy_limiter._requests.clear()
        r = client.get("/api/finance/cash-flow/?page_size=5001", headers=auth_headers)
        assert r.status_code == 422  # Validation error


# ─── 4. Veri Bütünlüğü Testleri ─────────────────────────────────────────────

class TestDataIntegrity:
    """match_number, finance_events upsert ve eşleştirme testleri."""

    def test_match_number_uniqueness_concurrent(self):
        """Eş zamanlı match_number üretimi çakışma olmadan benzersiz değerler döndürmeli."""
        from app.routers.finance.transaction_tags import _next_match_number

        results = []
        lock = threading.Lock()

        def get_number():
            db = TestSessionLocal()
            try:
                n = _next_match_number(db)
                with lock:
                    results.append(n)
            finally:
                db.close()

        threads = [threading.Thread(target=get_number) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10, f"10 thread'den {len(results)} sonuç"
        assert len(set(results)) == 10, f"Çakışan match_number: {results}"

    def test_finance_event_upsert_idempotent(self):
        """Aynı kayıt için birden fazla upsert — tek kayıt oluşturulmalı."""
        from app.models.bank_account import BankAccount
        from app.models.bank_transaction import BankTransaction

        db = TestSessionLocal()
        try:
            # Test hesabı bul
            acc = db.query(BankAccount).first()
            if not acc:
                pytest.skip("Test verisi yok (banka hesabı bulunamadı)")

            # Test işlemi bul
            tx = db.query(BankTransaction).filter(
                BankTransaction.account_id == acc.id
            ).first()
            if not tx:
                pytest.skip("Test verisi yok (banka işlemi bulunamadı)")

            # Aynı işlemi 5 kez upsert et
            for _ in range(5):
                finance_event_svc.upsert_bank_tx(db, tx, acc)

            # finance_events'te yalnızca 1 kayıt olmalı
            count = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == "bank",
                FinanceEvent.source_id == tx.id,
            ).count()
            assert count == 1, f"Beklenen 1 kayıt, bulunan: {count}"
        finally:
            db.close()

    def test_finance_event_invalidate(self):
        """invalidate() çağrısı finance_events kaydını silmeli."""
        db = TestSessionLocal()
        try:
            # Mevcut kayıtlardan bir tanesini bul
            event = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == "bank"
            ).first()
            if not event:
                pytest.skip("Test verisi yok")

            source_type = event.source_type
            source_id = event.source_id

            # Önce var olduğunu doğrula
            assert db.query(FinanceEvent).filter(
                FinanceEvent.source_type == source_type,
                FinanceEvent.source_id == source_id,
            ).count() == 1

            # invalidate
            finance_event_svc.invalidate(db, source_type, source_id)

            # Silinmiş olmalı
            count_after = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == source_type,
                FinanceEvent.source_id == source_id,
            ).count()
            assert count_after == 0

            # Geri al — test sonrası yeniden ekle
            db.rollback()
        finally:
            db.close()

    def test_finance_event_match_sets_is_matched(self):
        """match() çağrısı is_matched flag'ini doğru setlenmeli."""
        db = TestSessionLocal()
        try:
            # Eşleşmemiş check ve bank event bul
            from app.models.finance_event import SOURCE_BANK, SOURCE_CHECK
            bank_event = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == SOURCE_BANK,
                FinanceEvent.is_matched == False,
            ).first()
            check_event = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == SOURCE_CHECK,
                FinanceEvent.is_matched == False,
            ).first()

            if not bank_event or not check_event:
                pytest.skip("Test için eşleşmemiş bank/check eventi yok")

            # match çağır
            finance_event_svc.match(db, SOURCE_BANK, bank_event.source_id,
                                    SOURCE_CHECK, check_event.source_id)

            # Kontrol
            db.expire_all()
            bank_refreshed = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == SOURCE_BANK,
                FinanceEvent.source_id == bank_event.source_id,
            ).first()
            check_refreshed = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == SOURCE_CHECK,
                FinanceEvent.source_id == check_event.source_id,
            ).first()

            assert bank_refreshed.is_matched == False, "Bank event görünür kalmalı"
            assert check_refreshed.is_matched == True, "Check event gizlenmeli"

            # Geri al
            db.rollback()
        finally:
            db.close()


# ─── 5. Rate Limiting Testleri ───────────────────────────────────────────────

class TestRateLimiting:
    """Rate limiting kontrolleri."""

    def test_heavy_endpoint_rate_limited(self, client, auth_headers):
        """Ağır endpoint'ler 10 istek/dakika limitine sahip olmalı."""
        heavy_limiter._requests.clear()

        success_count = 0
        rate_limited_count = 0

        for _ in range(12):
            r = client.get("/api/finance/cash-flow/?page=1&page_size=10", headers=auth_headers)
            if r.status_code == 200:
                success_count += 1
            elif r.status_code == 429:
                rate_limited_count += 1

        assert success_count <= 10, f"Limit aşıldı: {success_count} başarılı istek"
        assert rate_limited_count >= 2, f"Rate limiting çalışmıyor: {rate_limited_count} 429 yanıtı"

    def test_unauthorized_requests_no_rate_limit_bypass(self, client):
        """Yetkisiz istek rate limit değil 401 dönmeli."""
        r = client.get("/api/finance/cash-flow/")
        assert r.status_code == 401
        assert "rate" not in r.json().get("detail", "").lower()


# ─── 6. Connection Pool Testleri ─────────────────────────────────────────────

class TestConnectionPool:
    """Bağlantı havuzu doğrulamaları."""

    def test_connection_pool_config(self):
        """Bağlantı havuzu 25 kullanıcı için yeterli yapılandırılmış olmalı."""
        from app.database import engine
        pool = engine.pool
        # pool_size >= 20 olmalı
        assert pool.size() >= 20, f"Pool boyutu yetersiz: {pool.size()}"

    def test_pool_recycle_not_too_long(self):
        """Bağlantı yenileme süresi 20 dakikadan uzun olmamalı."""
        from app.database import engine
        recycle = engine.pool._recycle
        assert recycle <= 1200, f"Pool recycle çok uzun: {recycle}s (max: 1200s)"

    def test_db_health_under_load(self, client, auth_headers):
        """10 hızlı ardışık istek sonrası health endpoint hala 200 dönmeli."""
        heavy_limiter._requests.clear()
        for _ in range(10):
            client.get("/api/finance/cash-flow/summary", headers=auth_headers)

        r = client.get("/api/health")
        assert r.status_code == 200
