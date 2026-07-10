"""VakıfBank API içe-aktarma — şema normalize + dedup ingest + finance_event + RBAC.

Şema bankanın resmî Postman collection'ı + örnek yanıtıyla doğrulandı (2026-07-10); canlı
sandbox uçtan uca test edildi. Burada ağ çağrısı YOK — testlenebilir çekirdek: normalize
(işaretli tutar/bakiye zinciri/yedek), payload biçimi, hesap seçimi, dedup, FE, izinler.
"""
from datetime import date

from app.models.bank_account import BankAccount
from app.models.finance_event import FinanceEvent
from app.routers.finance.vakifbank import (
    _ingest_transactions,
    _is_vakifbank,
    _vakifbank_accounts,
)
from app.utils.vakifbank_client import (
    _build_transactions_payload,
    _extract_account_list,
    _extract_transaction_list,
    _normalize_batch,
    _parse_iso_z,
)

API = "/api/finance/vakifbank"


def _mk_account(db, bank_name="VakıfBank", iban="TR000000000000000000000901", active=True):
    acc = BankAccount(bank_name=bank_name, iban=iban, currency="TRY", is_active=active)
    db.add(acc)
    db.flush()
    return acc


class TestVakifbankHelpers:
    def test_is_vakifbank_turkish_case(self):
        assert _is_vakifbank("VakıfBank")
        assert _is_vakifbank("VAKIFBANK")
        assert _is_vakifbank("Vakif Katılım")
        assert not _is_vakifbank("Halkbank")
        assert not _is_vakifbank("")

    def test_account_selection_filters(self, db):
        v1 = _mk_account(db, "VakıfBank", "TR000000000000000000000911")
        _mk_account(db, "Halkbank", "TR000000000000000000000912")             # yanlış banka
        _mk_account(db, "VakıfBank", "TR000000000000000000000913", active=False)  # pasif
        picked = {a.id for a in _vakifbank_accounts(db)}
        assert v1.id in picked
        assert len(picked) == 1  # yalnız aktif VakıfBank


class TestIngestDedup:
    def _rows(self):
        return [
            {"date": date(2026, 7, 1), "amount": -1000.0, "balance": 5000.0,
             "description": "EFT ödeme", "type": "expense", "receipt_no": "R1"},
            {"date": date(2026, 7, 2), "amount": 2500.0, "balance": 7500.0,
             "description": "Havale gelen", "type": "income", "receipt_no": "R2"},
        ]

    def test_ingest_creates_and_dedups(self, db):
        acc = _mk_account(db, iban="TR000000000000000000000921")
        new, skipped = _ingest_transactions(db, acc, self._rows())
        assert new == 2 and skipped == 0
        # İkinci kez aynı hareketler → bakiye-bazlı dedup ile tamamı atlanır
        new2, skipped2 = _ingest_transactions(db, acc, self._rows())
        assert new2 == 0 and skipped2 == 2

    def test_ingest_writes_finance_events(self, db):
        acc = _mk_account(db, iban="TR000000000000000000000922")
        _ingest_transactions(db, acc, self._rows())
        db.flush()
        fes = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "bank",
            FinanceEvent.bank_account_id == acc.id,
        ).all()
        assert len(fes) == 2
        # Yön işaretten türer: gider → expense, gelir → income (upsert_bank_tx abs + direction)
        dirs = sorted(fe.direction for fe in fes)
        assert dirs == [-1, 1]

    def test_ingest_missing_fields_skipped(self, db):
        acc = _mk_account(db, iban="TR000000000000000000000923")
        rows = [{"date": None, "amount": -5.0}, {"date": date(2026, 7, 3), "amount": None}]
        new, skipped = _ingest_transactions(db, acc, rows)
        assert new == 0 and skipped == 2


class TestNormalizeSchema:
    """VakıfBank gerçek response şeması (Data.AccountTransactions) → ortak şema + işaretli tutar."""

    def _raw(self):
        # Doküman şekli; bakiye zinciri: 1650 → 1450 → 1950
        return [
            {"TransactionDate": "2026-07-01T10:00:00.000Z", "Amount": "650.0", "Balance": "1650.0",
             "TransactionType": "1", "Description": "Gelen havale", "TransactionId": "1000000000000001",
             "CurrencyCode": "TL", "TransactionName": "Havale"},
            {"TransactionDate": "2026-07-02T11:00:00.000Z", "Amount": "200.0", "Balance": "1450.0",
             "TransactionType": "2", "Description": "Giden EFT", "TransactionId": "1000000000000002",
             "CurrencyCode": "TL", "TransactionName": "EFT"},
            {"TransactionDate": "2026-07-03T12:00:00.000Z", "Amount": "500.0", "Balance": "1950.0",
             "TransactionType": "1", "Description": "Senet tahsilatı", "TransactionId": "1000000000000003",
             "CurrencyCode": "TL", "TransactionName": "Senet tahsilatı"},
        ]

    def test_parse_iso_z(self):
        assert _parse_iso_z("2020-02-05T10:47:47.000Z") == date(2020, 2, 5)
        assert _parse_iso_z("2023-08-08T13:56:51") == date(2023, 8, 8)  # resmî örnek: Z'siz
        assert _parse_iso_z("") is None
        assert _parse_iso_z(None) is None

    def test_request_payload_shape(self):
        # Tarih formatı resmî Postman collection ile doğrulandı: +03:00 offset (Z değil)
        p = _build_transactions_payload("00158000000000001", date(2026, 7, 1), date(2026, 7, 9))
        assert p["AccountNumber"] == "00158000000000001"
        assert p["StartDate"] == "2026-07-01T00:00:00+03:00"
        assert p["EndDate"] == "2026-07-09T23:59:59+03:00"

    def test_extract_list_from_envelope(self):
        body = {"Header": {"StatusCode": "APIGW000000"}, "Data": {"AccountTransactions": self._raw()}}
        assert len(_extract_transaction_list(body)) == 3
        assert _extract_transaction_list({}) == []
        assert _extract_transaction_list({"Data": {}}) == []

    def test_balance_chain_signs(self):
        out = _normalize_batch(self._raw())
        assert [r["amount"] for r in out] == [650.0, -200.0, 500.0]  # ilk=type, sonrası=bakiye delta
        assert [r["type"] for r in out] == ["income", "expense", "income"]
        assert [r["receipt_no"] for r in out] == ["1000000000000001", "1000000000000002", "1000000000000003"]
        assert out[0]["date"] == date(2026, 7, 1)

    def test_sorts_out_of_order_input(self):
        out = _normalize_batch(list(reversed(self._raw())))  # ters sırayla ver
        # kronolojik sıralanır → aynı işaretler
        assert [r["amount"] for r in out] == [650.0, -200.0, 500.0]

    def test_skips_unparsable_rows(self):
        raw = [{"Amount": "5", "Balance": "10"},                       # tarih yok
               {"TransactionDate": "2026-07-01T00:00:00.000Z", "Balance": "10"}]  # tutar yok
        assert _normalize_batch(raw) == []


class TestNormalizeOfficialSample:
    """Bankanın resmî Postman örnek yanıtı (2026-07-10): Amount İŞARETLİ gelir, bakiyeler
    sandbox'ta tutarsız (zincir kurulamaz) → yön Amount işareti / TransactionType'tan."""

    def _official(self):
        return [
            {"CurrencyCode": "TL", "TransactionType": "1", "Description": "deneme / PARA Yatirma",
             "Amount": 97979, "Balance": 999999, "TransactionName": "Çek BST Giriş",
             "TransactionDate": "2023-08-08T13:56:51", "TransactionId": "2014000007740171"},
            {"CurrencyCode": "TL", "TransactionType": "2", "Description": "Ek Hesap gecikmeli kredi tahsilatı",
             "Amount": -1.74, "Balance": 999999492.16, "TransactionName": "Gecikmeli Kmh Tahsilatı",
             "TransactionDate": "2023-08-08T13:58:41", "TransactionId": "2023000012500913"},
        ]

    def test_signed_amount_direction(self):
        out = _normalize_batch(self._official())
        assert [r["amount"] for r in out] == [97979.0, -1.74]
        assert [r["type"] for r in out] == ["income", "expense"]

    def test_unsigned_type2_falls_back_to_expense(self):
        # Banka işaretsiz gönderirse (bakiye zinciri de yoksa) type "2" → gider
        raw = [{"TransactionDate": "2023-08-08T13:58:41", "Amount": "1.74",
                "TransactionType": "2", "Description": "KMH", "TransactionId": "X1"}]
        out = _normalize_batch(raw)
        assert out[0]["amount"] == -1.74 and out[0]["type"] == "expense"

    def test_unknown_type_positive_defaults_income(self):
        raw = [{"TransactionDate": "2023-08-08T13:58:41", "Amount": "10.0",
                "TransactionType": "7", "Description": "?", "TransactionId": "X2"}]
        out = _normalize_batch(raw)
        assert out[0]["amount"] == 10.0 and out[0]["type"] == "income"

    def test_extract_account_list_shapes(self):
        rows = [{"AccountNumber": "123", "IBAN": "TR00"}]
        assert _extract_account_list({"Data": {"Accounts": rows}}) == rows   # dict içinde liste
        assert _extract_account_list({"Data": rows}) == rows                 # doğrudan liste
        single = {"AccountNumber": "123"}
        assert _extract_account_list({"Data": single}) == [single]           # tek dict
        assert _extract_account_list({}) == []
        assert _extract_account_list(None) == []


def _force_unconfigured(monkeypatch):
    """Kimlik durumunu deterministik yap (gerçek .env'e bağlı kalmasın)."""
    monkeypatch.setattr("app.routers.finance.vakifbank.vakifbank_configured", lambda: False)


class TestEndpoints:
    def test_status_requires_view(self, client, no_perm_user_headers):
        client.cookies.clear()  # fixture login'inin bıraktığı cookie'yi temizle (gerçek kimliksiz)
        assert client.get(f"{API}/status").status_code == 401
        assert client.get(f"{API}/status", headers=no_perm_user_headers).status_code == 403

    def test_status_shape(self, client, auth_headers, monkeypatch):
        _force_unconfigured(monkeypatch)
        r = client.get(f"{API}/status", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["configured"] is False and body["account_count"] == 0
        assert "lookback_days" in body and "has_riza" in body

    def test_sync_permission_then_503_unconfigured(self, client, auth_headers, no_perm_user_headers, monkeypatch):
        # İzinsiz → 403 (permission dependency önce çalışır, config'ten bağımsız)
        assert client.post(f"{API}/sync", headers=no_perm_user_headers).status_code == 403
        # Yetkili ama kapalı → 503 (ağ çağrısı YOK)
        _force_unconfigured(monkeypatch)
        assert client.post(f"{API}/sync", headers=auth_headers).status_code == 503

    def test_test_connection_permission_then_503_unconfigured(self, client, auth_headers, no_perm_user_headers, monkeypatch):
        assert client.post(f"{API}/test-connection", headers=no_perm_user_headers).status_code == 403
        _force_unconfigured(monkeypatch)  # ağ çağrısı olmadan 503
        assert client.post(f"{API}/test-connection", headers=auth_headers).status_code == 503
