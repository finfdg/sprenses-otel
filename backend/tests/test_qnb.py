"""QNB Account Statement V2 — response parse (doküman örneğiyle) + yön (A/B) + token akışı.

Parse saf fonksiyonlarla, fetch monkeypatch'li (ağ/kimlik yok) test edilir.
"""
from datetime import date

from app.utils import qnb_api as qnb

# Doküman "Account Statement" örnek accountTransactionList (2 kayıt)
_DOC_ROWS = [
    {"transactionAmount": "50000", "debitOrCreditCode": "A", "balanceAfterTransaction": "50000",
     "transactionDate": "11.04.2025 13:26:36", "transactionDescription": "FDSFSFSF",
     "transactionId": "2560007925763013", "currencyCode": "TRY", "processCode": "MSC"},
    {"transactionAmount": "500", "debitOrCreditCode": "B", "balanceAfterTransaction": "49500",
     "transactionDate": "11.04.2025 13:27:44", "transactionDescription": "Swift Teleks Ücreti Giden havale",
     "transactionId": "2770008195919701", "currencyCode": "TRY", "processCode": "CHG"},
]


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class TestQnbParse:
    def test_parse_date_two_formats(self):
        assert qnb._parse_qnb_date("11.04.2025 13:26:36") == date(2025, 4, 11)
        assert qnb._parse_qnb_date("20241210") == date(2024, 12, 10)  # ticket biçimi
        assert qnb._parse_qnb_date("") is None
        assert qnb._parse_qnb_date(None) is None

    def test_parse_time(self):
        assert qnb._parse_qnb_time("11.04.2025 13:26:36") == "13:26:36"
        assert qnb._parse_qnb_time("20241210") is None

    def test_txn_list_direction_and_balance(self):
        txns = qnb._parse_txn_list(_DOC_ROWS, {})
        assert len(txns) == 2
        # A = Alacak (gelir, +) · B = Borç (gider, −)
        assert txns[0].amount == 50000.0 and txns[0].type == "income"
        assert txns[1].amount == -500.0 and txns[1].type == "expense"
        # balance = balanceAfterTransaction (yürüyen)
        assert txns[0].balance == 50000.0 and txns[1].balance == 49500.0
        assert txns[0].date == date(2025, 4, 11)
        assert txns[0].receipt_no == "2560007925763013"  # transactionId
        assert txns[0].description == "FDSFSFSF"
        assert txns[0].time == "13:26:36"

    def test_same_day_dup_distinct_hash(self):
        dup = [_DOC_ROWS[0], dict(_DOC_ROWS[0])]
        txns = qnb._parse_txn_list(dup, {})
        assert len(txns) == 2
        assert txns[0].tx_hash != txns[1].tx_hash

    def test_skips_unparsable(self):
        rows = [{"debitOrCreditCode": "A", "balanceAfterTransaction": "5"},   # tutar yok
                {"transactionAmount": "5", "transactionDate": "bozuk"}]        # tarih bozuk
        assert qnb._parse_txn_list(rows, {}) == []


class TestQnbFetch:
    def test_fetch_one_day(self, monkeypatch):
        monkeypatch.setattr(qnb, "_get_access_token", lambda: "TESTTOKEN")
        monkeypatch.setattr(qnb.httpx, "get",
                            lambda url, **kw: _FakeResp({"accountTransactionList": _DOC_ROWS, "resultCode": "0"}))
        res = qnb.fetch_qnb_statement(date(2025, 4, 11), date(2025, 4, 11), iban="TR870011100000000021385308")
        assert len(res.transactions) == 2
        assert res.header.iban.endswith("385308")
        assert [t.type for t in res.transactions] == ["income", "expense"]

    def test_ticket_fallback(self, monkeypatch):
        # İlk çağrı "çok kayıt" (ticketNo) → ticket servisi tek sayfa döner
        monkeypatch.setattr(qnb, "_get_access_token", lambda: "TESTTOKEN")
        calls = {"n": 0}

        def fake_get(url, **kw):
            if url.endswith("/ticket"):
                return _FakeResp({"accountTransactionList": _DOC_ROWS, "nextPageExist": "false"})
            calls["n"] += 1
            return _FakeResp({"ticketNo": "T123", "resultCode": "1",
                              "resultDescription": "Sorgunuz çok sayıda kayıt getirmektedir."})
        monkeypatch.setattr(qnb.httpx, "get", fake_get)
        res = qnb.fetch_qnb_statement(date(2025, 4, 11), date(2025, 4, 11), iban="TR870011100000000021385308")
        assert len(res.transactions) == 2  # ticket'tan geldi

    def test_configured_false_when_unset(self):
        # Test ortamında QNB kimliği yok → kapalı
        assert qnb.qnb_configured() is False
