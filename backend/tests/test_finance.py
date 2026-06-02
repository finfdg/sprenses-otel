"""Finance modülleri detaylı testleri (cash_flow, banks, exchange_rates, transaction_tags, cariler)."""

import pytest
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload
from app.models.exchange_rate import ExchangeRate
from datetime import date
from decimal import Decimal


@pytest.fixture
def test_bank_account(db):
    """Test banka hesabı."""
    acc = db.query(BankAccount).filter(BankAccount.iban == "TR000000000000000000000099").first()
    if not acc:
        acc = BankAccount(
            bank_name="Test Bank",
            iban="TR000000000000000000000099",
            currency="TRY",
            holder_name="Test Hesap",
            is_active=True,
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)
    return acc


@pytest.fixture
def test_transactions(db, test_bank_account):
    """Test banka işlemleri."""
    txs = []
    for i in range(3):
        tx = BankTransaction(
            account_id=test_bank_account.id,
            date=date(2026, 3, 10 + i),
            description=f"Test işlem {i+1}",
            amount=Decimal("1000.00") if i % 2 == 0 else Decimal("-500.00"),
            balance=Decimal("5000.00"),
            type="income" if i % 2 == 0 else "expense",
            tx_hash=f"test_hash_{i}_{test_bank_account.id}",
        )
        db.add(tx)
        txs.append(tx)
    db.commit()
    for tx in txs:
        db.refresh(tx)
    yield txs
    # Temizlik
    for tx in txs:
        existing = db.query(BankTransaction).filter(BankTransaction.id == tx.id).first()
        if existing:
            db.delete(existing)
    db.commit()


@pytest.fixture
def test_category(db):
    """Test kategori."""
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Test Kategori").first()
    if not cat:
        cat = TransactionCategory(name="Test Kategori", color="#FF0000", sort_order=999)
        db.add(cat)
        db.commit()
        db.refresh(cat)
    yield cat
    existing = db.query(TransactionCategory).filter(TransactionCategory.id == cat.id).first()
    if existing:
        db.delete(existing)
        db.commit()


@pytest.fixture
def test_exchange_rate(db):
    """Test döviz kuru."""
    er = db.query(ExchangeRate).filter(
        ExchangeRate.date == date(2026, 3, 20),
        ExchangeRate.currency_code == "USD",
    ).first()
    if not er:
        er = ExchangeRate(
            date=date(2026, 3, 20),
            currency_code="USD",
            currency_name="ABD DOLARI",
            unit=1,
            forex_buying=Decimal("36.50"),
            forex_selling=Decimal("36.60"),
            banknote_buying=Decimal("36.40"),
            banknote_selling=Decimal("36.70"),
            source="test",
        )
        db.add(er)
        db.commit()
        db.refresh(er)
    yield er
    existing = db.query(ExchangeRate).filter(ExchangeRate.id == er.id).first()
    if existing:
        db.delete(existing)
        db.commit()


# ==================== CASH FLOW TESTLERİ ====================


class TestCashFlow:
    """Nakit akım testleri."""

    def test_list_cash_flows(self, client, auth_headers):
        """Cash flow listesi döndürmeli."""
        response = client.get("/api/finance/cash-flow/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data

    def test_list_cash_flows_pagination(self, client, auth_headers):
        """Sayfalama parametreleri çalışmalı."""
        response = client.get("/api/finance/cash-flow/?page=1&page_size=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_list_cash_flows_type_filter(self, client, auth_headers):
        """Tip filtresi çalışmalı."""
        response = client.get("/api/finance/cash-flow/?type=income", headers=auth_headers)
        assert response.status_code == 200

        response2 = client.get("/api/finance/cash-flow/?type=expense", headers=auth_headers)
        assert response2.status_code == 200

    def test_list_cash_flows_invalid_type(self, client, auth_headers):
        """Geçersiz tip 422 dönmeli."""
        response = client.get("/api/finance/cash-flow/?type=invalid", headers=auth_headers)
        assert response.status_code == 422

    def test_cash_flow_summary(self, client, auth_headers):
        """Özet doğru yapıda olmalı."""
        response = client.get("/api/finance/cash-flow/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_income" in data
        assert "total_expense" in data
        assert "balance" in data
        assert isinstance(data["total_income"], (int, float))

    def test_monthly_summary(self, client, auth_headers):
        """Aylık özet doğru yapıda olmalı."""
        response = client.get("/api/finance/cash-flow/monthly-summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "year" in item
            assert "month" in item
            assert "total_income" in item
            assert "total_expense" in item
            assert "balance" in item

    def test_cash_flow_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/finance/cash-flow/")
        assert response.status_code == 401


# ==================== BANKA HESAP TESTLERİ ====================


class TestBankAccounts:
    """Banka hesap yönetimi testleri."""

    def test_list_accounts(self, client, auth_headers):
        """Hesap listesi döndürmeli."""
        response = client.get("/api/finance/banks/accounts/", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_accounts_structure(self, client, auth_headers, test_bank_account):
        """Hesap yapısı doğru olmalı."""
        response = client.get("/api/finance/banks/accounts/", headers=auth_headers)
        accounts = response.json()
        test_acc = next((a for a in accounts if a["iban"] == "TR000000000000000000000099"), None)
        assert test_acc is not None
        for field in ["id", "bank_name", "iban", "currency", "is_active", "transaction_count"]:
            assert field in test_acc

    def test_list_accounts_with_transaction_count(self, client, auth_headers, test_transactions):
        """İşlem sayısı doğru hesaplanmalı."""
        response = client.get("/api/finance/banks/accounts/", headers=auth_headers)
        accounts = response.json()
        test_acc = next((a for a in accounts if a["iban"] == "TR000000000000000000000099"), None)
        assert test_acc is not None
        assert test_acc["transaction_count"] >= 3

    def test_create_account(self, client, auth_headers, db):
        """Yeni hesap oluşturulabilmeli."""
        response = client.post("/api/finance/banks/accounts/", headers=auth_headers, json={
            "bank_name": "Yeni Test Bank",
            "iban": "TR110000000000000000000001",
            "currency": "TRY",
        })
        assert response.status_code == 201
        assert response.json()["bank_name"] == "Yeni Test Bank"
        # Temizlik
        acc = db.query(BankAccount).filter(BankAccount.iban == "TR110000000000000000000001").first()
        if acc:
            db.delete(acc)
            db.commit()

    def test_create_account_duplicate_iban(self, client, auth_headers, test_bank_account):
        """Aynı IBAN ile hesap oluşturma hata vermeli."""
        response = client.post("/api/finance/banks/accounts/", headers=auth_headers, json={
            "bank_name": "Duplicate Bank",
            "iban": "TR000000000000000000000099",
            "currency": "TRY",
        })
        assert response.status_code == 400

    def test_update_account(self, client, auth_headers, test_bank_account):
        """Hesap güncellenebilmeli."""
        response = client.patch(
            f"/api/finance/banks/accounts/{test_bank_account.id}",
            headers=auth_headers,
            json={"bank_name": "Güncel Test Bank"},
        )
        assert response.status_code == 200

    def test_update_account_not_found(self, client, auth_headers):
        """Olmayan hesap 404 dönmeli."""
        response = client.patch("/api/finance/banks/accounts/999999", headers=auth_headers, json={
            "bank_name": "Test",
        })
        assert response.status_code == 404

    def test_list_transactions(self, client, auth_headers, test_bank_account, test_transactions):
        """Hesap işlemleri listelenebilmeli."""
        response = client.get(
            f"/api/finance/banks/accounts/{test_bank_account.id}/transactions",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 3

    def test_list_transactions_not_found(self, client, auth_headers):
        """Olmayan hesap 404 dönmeli."""
        response = client.get("/api/finance/banks/accounts/999999/transactions", headers=auth_headers)
        assert response.status_code == 404

    def test_accounts_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/finance/banks/accounts/")
        assert response.status_code == 401


# ==================== KATEGORİ / ETİKET TESTLERİ ====================


class TestTransactionTags:
    """İşlem etiketleme testleri."""

    def test_list_categories(self, client, auth_headers):
        """Kategoriler listelenebilmeli."""
        response = client.get("/api/finance/tags/categories", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_category(self, client, auth_headers, db):
        """Yeni kategori oluşturulabilmeli."""
        response = client.post("/api/finance/tags/categories", headers=auth_headers, json={
            "name": "Test Yeni Kategori",
            "color": "#00FF00",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Yeni Kategori"
        assert data["color"] == "#00FF00"
        # Temizlik
        cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Test Yeni Kategori").first()
        if cat:
            db.delete(cat)
            db.commit()

    def test_create_category_duplicate(self, client, auth_headers, test_category):
        """Aynı isimle kategori oluşturma hata vermeli."""
        response = client.post("/api/finance/tags/categories", headers=auth_headers, json={
            "name": "Test Kategori",
            "color": "#0000FF",
        })
        assert response.status_code == 400

    def test_untagged_count(self, client, auth_headers):
        """Etiketlenmemiş sayısı döndürmeli."""
        response = client.get("/api/finance/tags/untagged-count", headers=auth_headers)
        assert response.status_code == 200
        assert "count" in response.json()

    def test_tag_transaction(self, client, auth_headers, test_transactions, test_category):
        """İşlem etiketlenebilmeli."""
        tx_id = test_transactions[0].id
        response = client.patch(
            f"/api/finance/tags/transactions/{tx_id}",
            headers=auth_headers,
            json={"category_id": test_category.id, "tag_note": "Test notu"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_tag_transaction_not_found(self, client, auth_headers):
        """Olmayan işlem 404 dönmeli."""
        response = client.patch(
            "/api/finance/tags/transactions/999999",
            headers=auth_headers,
            json={"category_id": None},
        )
        assert response.status_code == 404

    def test_bulk_tag(self, client, auth_headers, test_transactions, test_category):
        """Toplu etiketleme çalışmalı."""
        tx_ids = [tx.id for tx in test_transactions]
        response = client.post("/api/finance/tags/transactions/bulk", headers=auth_headers, json={
            "transaction_ids": tx_ids,
            "category_id": test_category.id,
        })
        assert response.status_code == 200
        assert response.json()["count"] == len(tx_ids)

    def test_bulk_tag_empty(self, client, auth_headers):
        """Boş liste hata vermeli."""
        response = client.post("/api/finance/tags/transactions/bulk", headers=auth_headers, json={
            "transaction_ids": [],
            "category_id": None,
        })
        assert response.status_code == 400

    def test_tags_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/finance/tags/categories")
        assert response.status_code == 401


# ==================== DÖVİZ KURU TESTLERİ ====================


class TestExchangeRates:
    """Döviz kuru testleri."""

    def test_latest_rates(self, client, auth_headers, test_exchange_rate):
        """En son kurlar döndürmeli."""
        response = client.get("/api/finance/exchange-rates/latest", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "rates" in data

    def test_rate_history(self, client, auth_headers, test_exchange_rate):
        """Kur tarihçesi çalışmalı."""
        response = client.get("/api/finance/exchange-rates/history?currency_code=USD", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_rate_history_invalid_currency(self, client, auth_headers):
        """Geçersiz döviz kodu 422 dönmeli."""
        response = client.get("/api/finance/exchange-rates/history?currency_code=XYZ", headers=auth_headers)
        assert response.status_code == 422

    def test_chart_data(self, client, auth_headers, test_exchange_rate):
        """Grafik verisi döndürmeli."""
        response = client.get("/api/finance/exchange-rates/chart?currency_code=USD", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_parity_history(self, client, auth_headers):
        """Parite tarihçesi çalışmalı."""
        response = client.get("/api/finance/exchange-rates/parity/history", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_rates_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/finance/exchange-rates/latest")
        assert response.status_code == 401


# ==================== CARİ TESTLERİ ====================


class TestCariler:
    """Cari hesap testleri."""

    def test_vendors_summary(self, client, auth_headers):
        """Cari özeti döndürmeli."""
        response = client.get("/api/finance/cariler/vendors/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        for field in ["total_borc", "total_alacak", "bakiye", "vendor_count"]:
            assert field in data

    def test_list_vendors(self, client, auth_headers):
        """Cari listesi döndürmeli."""
        response = client.get("/api/finance/cariler/vendors", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_list_vendors_pagination(self, client, auth_headers):
        """Sayfalama çalışmalı."""
        response = client.get("/api/finance/cariler/vendors?page=1&page_size=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_list_vendors_search(self, client, auth_headers):
        """Arama çalışmalı."""
        response = client.get("/api/finance/cariler/vendors?search=test", headers=auth_headers)
        assert response.status_code == 200

    def test_list_vendors_sort(self, client, auth_headers):
        """Sıralama çalışmalı."""
        response = client.get("/api/finance/cariler/vendors?sort_by=bakiye&sort_dir=desc", headers=auth_headers)
        assert response.status_code == 200

    def test_list_vendors_invalid_sort(self, client, auth_headers):
        """Geçersiz sıralama 422 dönmeli."""
        response = client.get("/api/finance/cariler/vendors?sort_by=invalid", headers=auth_headers)
        assert response.status_code == 422

    def test_vendor_detail_not_found(self, client, auth_headers):
        """Olmayan cari 404 dönmeli."""
        response = client.get("/api/finance/cariler/vendors/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_list_uploads(self, client, auth_headers):
        """Yükleme geçmişi listelenebilmeli."""
        response = client.get("/api/finance/cariler/uploads", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_payment_schedule(self, client, auth_headers):
        """Ödeme planı döndürmeli."""
        response = client.get("/api/finance/cariler/payment-schedule", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_cariler_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/finance/cariler/vendors")
        assert response.status_code == 401

    def test_delete_upload_not_found(self, client, auth_headers):
        """Olmayan yükleme 404 dönmeli."""
        response = client.delete("/api/finance/cariler/uploads/999999", headers=auth_headers)
        assert response.status_code == 404


# ==================== KAYNAKTA OLMAYAN KAYITLARIN SİLİNMESİ ====================


class TestRemovalCandidates:
    """Yükleme sırasında Excel'de bulunmayan kayıtların tespiti + toplu silme."""

    def _seed(self, db, code="320.99.99.TEST", txs=None):
        """Test cari + işlem fixture'ı oluştur."""
        from datetime import date
        from app.utils.vendor_parser import compute_vendor_tx_hash

        upload = VendorUpload(
            file_name="seed.xlsx",
            file_url="/tmp/seed.xlsx",
            uploaded_by=1,
            total_vendors=1,
            total_transactions=0,
            new_transactions=0,
            skipped_transactions=0,
        )
        db.add(upload)
        db.flush()

        vendor = Vendor(hesap_kodu=code, hesap_adi=f"Test Cari {code}")
        db.add(vendor)
        db.flush()

        created = []
        for i, (d, borc, alacak, evrak) in enumerate(txs or []):
            tx_hash = compute_vendor_tx_hash(code, d, evrak, borc, alacak)
            vtx = VendorTransaction(
                vendor_id=vendor.id,
                upload_id=upload.id,
                date=d,
                evrak_no=evrak,
                transaction_type="Test",
                description=f"Seed tx {i}",
                borc=borc,
                alacak=alacak,
                bakiye=0,
                tx_hash=tx_hash,
            )
            db.add(vtx)
            db.flush()
            created.append(vtx)
        db.commit()
        return vendor, created

    def test_compute_removal_candidates_basic(self, db):
        """Excel'de olmayan kayıt aday olmalı, Excel'de olan dokunulmamalı."""
        from datetime import date
        from app.routers.finance.cariler.uploads import _compute_removal_candidates
        from app.utils.vendor_parser import ParsedVendorTransaction, compute_vendor_tx_hash

        vendor, vtxs = self._seed(db, code="320.RC.001", txs=[
            (date(2026, 4, 1), 100.0, 0.0, "EV-1"),
            (date(2026, 4, 5), 200.0, 0.0, "EV-2"),
            (date(2026, 4, 10), 300.0, 0.0, "EV-3"),
        ])

        # Excel sadece EV-1 ve EV-3'ü içersin → EV-2 aday olmalı
        parsed = [
            ParsedVendorTransaction(
                hesap_kodu=vendor.hesap_kodu, hesap_adi=vendor.hesap_adi,
                date=date(2026, 4, 1), evrak_no="EV-1", transaction_type="Test",
                fis_no=None, description=None, borc=100.0, alacak=0.0, bakiye=None,
                tx_hash=compute_vendor_tx_hash(vendor.hesap_kodu, date(2026, 4, 1), "EV-1", 100.0, 0.0),
            ),
            ParsedVendorTransaction(
                hesap_kodu=vendor.hesap_kodu, hesap_adi=vendor.hesap_adi,
                date=date(2026, 4, 10), evrak_no="EV-3", transaction_type="Test",
                fis_no=None, description=None, borc=300.0, alacak=0.0, bakiye=None,
                tx_hash=compute_vendor_tx_hash(vendor.hesap_kodu, date(2026, 4, 10), "EV-3", 300.0, 0.0),
            ),
        ]
        candidates = _compute_removal_candidates(db, {vendor.hesap_kodu: vendor}, parsed)
        assert len(candidates) == 1
        assert candidates[0].evrak_no == "EV-2"
        assert candidates[0].borc == 200.0

    def test_compute_removal_candidates_date_scope(self, db):
        """Excel'in tarih aralığı dışındaki kayıtlar aday OLMAMALI."""
        from datetime import date
        from app.routers.finance.cariler.uploads import _compute_removal_candidates
        from app.utils.vendor_parser import ParsedVendorTransaction, compute_vendor_tx_hash

        vendor, _ = self._seed(db, code="320.RC.002", txs=[
            (date(2026, 1, 15), 50.0, 0.0, "OLD-1"),  # Excel kapsamı dışı (önce)
            (date(2026, 4, 5), 100.0, 0.0, "MID-1"),  # kapsamda, Excel'de yok → aday
            (date(2026, 5, 20), 200.0, 0.0, "FUT-1"),  # kapsam dışı (sonra)
        ])

        # Excel sadece Nisan dönemini içersin (4-1 ile 4-30)
        parsed = [
            ParsedVendorTransaction(
                hesap_kodu=vendor.hesap_kodu, hesap_adi=vendor.hesap_adi,
                date=date(2026, 4, 1), evrak_no="X-NEW", transaction_type="Test",
                fis_no=None, description=None, borc=10.0, alacak=0.0, bakiye=None,
                tx_hash=compute_vendor_tx_hash(vendor.hesap_kodu, date(2026, 4, 1), "X-NEW", 10.0, 0.0),
            ),
            ParsedVendorTransaction(
                hesap_kodu=vendor.hesap_kodu, hesap_adi=vendor.hesap_adi,
                date=date(2026, 4, 30), evrak_no="X-LAST", transaction_type="Test",
                fis_no=None, description=None, borc=20.0, alacak=0.0, bakiye=None,
                tx_hash=compute_vendor_tx_hash(vendor.hesap_kodu, date(2026, 4, 30), "X-LAST", 20.0, 0.0),
            ),
        ]
        candidates = _compute_removal_candidates(db, {vendor.hesap_kodu: vendor}, parsed)
        evrak_list = [c.evrak_no for c in candidates]
        assert "MID-1" in evrak_list
        assert "OLD-1" not in evrak_list
        assert "FUT-1" not in evrak_list

    def test_compute_removal_candidates_protected(self, db):
        """match_number ve dept_status dolu kayıtlar aday OLMAMALI."""
        from datetime import date
        from app.routers.finance.cariler.uploads import _compute_removal_candidates
        from app.utils.vendor_parser import ParsedVendorTransaction, compute_vendor_tx_hash

        vendor, vtxs = self._seed(db, code="320.RC.003", txs=[
            (date(2026, 4, 1), 100.0, 0.0, "EV-A"),
            (date(2026, 4, 2), 200.0, 0.0, "EV-B"),
            (date(2026, 4, 3), 300.0, 0.0, "EV-C"),
        ])
        # EV-A: match_number var (banka eşleşmesi)
        vtxs[0].match_number = 999
        # EV-B: dept_status assigned
        vtxs[1].dept_status = "assigned"
        db.commit()

        # Excel dosyası boş — yani hepsi diff'te aday olmaya aday ama EV-A ve EV-B korunmalı
        parsed = [
            ParsedVendorTransaction(
                hesap_kodu=vendor.hesap_kodu, hesap_adi=vendor.hesap_adi,
                date=date(2026, 4, 1), evrak_no="EV-A", transaction_type="Test",
                fis_no=None, description=None, borc=100.0, alacak=0.0, bakiye=None,
                tx_hash=compute_vendor_tx_hash(vendor.hesap_kodu, date(2026, 4, 1), "EV-A", 100.0, 0.0),
            ),
            ParsedVendorTransaction(
                hesap_kodu=vendor.hesap_kodu, hesap_adi=vendor.hesap_adi,
                date=date(2026, 4, 3), evrak_no="EV-C", transaction_type="Test",
                fis_no=None, description=None, borc=300.0, alacak=0.0, bakiye=None,
                tx_hash=compute_vendor_tx_hash(vendor.hesap_kodu, date(2026, 4, 3), "EV-C", 300.0, 0.0),
            ),
        ]
        # Excel'de sadece EV-A ve EV-C var → EV-B teorik aday ama dept_status='assigned' → atla
        candidates = _compute_removal_candidates(db, {vendor.hesap_kodu: vendor}, parsed)
        assert candidates == [], f"Korumalı kayıtlar aday OLMAMALI, geldi: {[c.evrak_no for c in candidates]}"

    def test_bulk_delete_empty(self, client, auth_headers):
        """Boş id listesi 0 silme döner."""
        response = client.post(
            "/api/finance/cariler/transactions/bulk-delete",
            headers=auth_headers,
            json={"ids": []},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 0
        assert data["skipped"] == 0

    def test_bulk_delete_unauthorized(self, client):
        """Token olmadan 401 dönmeli."""
        response = client.post(
            "/api/finance/cariler/transactions/bulk-delete",
            json={"ids": [1, 2]},
        )
        assert response.status_code == 401

    def test_bulk_delete_too_many(self, client, auth_headers):
        """5000'den fazla id 400 dönmeli."""
        response = client.post(
            "/api/finance/cariler/transactions/bulk-delete",
            headers=auth_headers,
            json={"ids": list(range(5001))},
        )
        assert response.status_code == 400

    def test_bulk_delete_skips_protected(self, client, auth_headers, db):
        """Korumalı kayıtlar atlanır, koruma altında olmayanlar silinir."""
        from datetime import date

        vendor, vtxs = self._seed(db, code="320.RC.004", txs=[
            (date(2026, 4, 1), 100.0, 0.0, "BD-1"),  # silinebilir
            (date(2026, 4, 2), 200.0, 0.0, "BD-2"),  # match_number dolu → atlanır
            (date(2026, 4, 3), 300.0, 0.0, "BD-3"),  # dept_status approved → atlanır
        ])
        vtxs[1].match_number = 12345
        vtxs[2].dept_status = "approved"
        db.commit()

        response = client.post(
            "/api/finance/cariler/transactions/bulk-delete",
            headers=auth_headers,
            json={"ids": [v.id for v in vtxs]},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["deleted"] == 1
        assert data["skipped"] == 2
        assert any("eşleşmiş" in r for r in data["skipped_reasons"])
        assert any("departmana" in r for r in data["skipped_reasons"])

        # BD-1 silinmiş, diğerleri durmalı
        remaining = db.query(VendorTransaction).filter(
            VendorTransaction.vendor_id == vendor.id,
        ).all()
        evraks = {v.evrak_no for v in remaining}
        assert evraks == {"BD-2", "BD-3"}

    def test_bulk_delete_missing_ids(self, client, auth_headers):
        """Bulunamayan id'ler skipped sayılır, hata vermez."""
        response = client.post(
            "/api/finance/cariler/transactions/bulk-delete",
            headers=auth_headers,
            json={"ids": [9999991, 9999992]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 0
        assert data["skipped"] == 2
        assert any("bulunamadı" in r for r in data["skipped_reasons"])
