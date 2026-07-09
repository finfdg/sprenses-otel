"""Garanti BBVA Account Transactions — response parse (doküman örneğiyle) + yön (A/B).

Parse saf fonksiyonlarla, fetch monkeypatch'li (ağ/kimlik yok) test edilir.
"""
from datetime import date

from app.utils import garanti_api as gb

# Doküman "Sample Response" transactions[] (kısaltılmış — A ve B örnekleri)
_DOC_ROWS = [
    {"accountNum": 6291296, "currencyCode": "TL", "IBAN": "TR620006200029500006291296",
     "activityDate": "2020-12-25", "valueDate": "2020-12-28", "txnCreditDebitIndicator": "A",
     "amount": 1250.67, "balanceAfterTransaction": 9836180.2, "explanation": "00000",
     "transactionId": "WPDT", "transactionInstanceId": "2020-12-25T16:13:36.862988"},
    {"accountNum": 6291335, "currencyCode": None, "IBAN": "TR760006200029500006291335",
     "activityDate": "2020-11-04", "valueDate": "2020-11-04", "txnCreditDebitIndicator": "B",
     "amount": 20, "balanceAfterTransaction": 1071.46, "explanation": "MAAŞ ÖDEMESİ",
     "transactionId": "ELMS", "transactionInstanceId": "2020-12-25T13:44:38.453646"},
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


class TestGarantiParse:
    def test_parse_date(self):
        assert gb._parse_date("2020-12-25") == date(2020, 12, 25)
        assert gb._parse_date("") is None
        assert gb._parse_date(None) is None

    def test_iso_ts(self):
        assert gb._iso_ts(date(2026, 7, 1)) == "2026-07-01T00:00:00.000"
        assert gb._iso_ts(date(2026, 7, 9), end=True) == "2026-07-09T23:59:59.999"

    def test_direction_and_balance(self):
        txns = gb._parse_txn_list(_DOC_ROWS, {})
        assert len(txns) == 2
        # A = Alacak (gelir, +) · B = Borç (gider, −)
        assert txns[0].amount == 1250.67 and txns[0].type == "income"
        assert txns[1].amount == -20.0 and txns[1].type == "expense"
        # balance = balanceAfterTransaction (yürüyen)
        assert txns[0].balance == 9836180.2 and txns[1].balance == 1071.46
        assert txns[0].date == date(2020, 12, 25)
        # dedup = transactionInstanceId
        assert txns[0].receipt_no == "2020-12-25T16:13:36.862988"
        assert txns[1].description == "MAAŞ ÖDEMESİ"

    def test_same_day_dup_distinct_hash(self):
        dup = [_DOC_ROWS[0], dict(_DOC_ROWS[0])]
        txns = gb._parse_txn_list(dup, {})
        assert len(txns) == 2 and txns[0].tx_hash != txns[1].tx_hash

    def test_skips_unparsable(self):
        rows = [{"txnCreditDebitIndicator": "A"},                         # tutar/tarih yok
                {"amount": 5, "activityDate": "bozuk"}]                    # tarih bozuk
        assert gb._parse_txn_list(rows, {}) == []


class TestGarantiFetch:
    def test_fetch_paginates_and_parses(self, monkeypatch):
        monkeypatch.setattr(gb, "_get_token", lambda: "TESTTOKEN")
        # tek sayfa (2 < 500) → tek POST
        monkeypatch.setattr(gb.httpx, "post",
                            lambda url, **kw: _FakeResp({"result": {"returnCode": 200}, "transactions": _DOC_ROWS}))
        res = gb.fetch_garanti_statement(date(2020, 12, 1), date(2020, 12, 25),
                                         iban="TR620006200029500006291296", currency="TRY")
        assert len(res.transactions) == 2
        assert [t.type for t in res.transactions] == ["income", "expense"]

    def test_business_error_raises(self, monkeypatch):
        monkeypatch.setattr(gb, "_get_token", lambda: "TESTTOKEN")
        monkeypatch.setattr(gb.httpx, "post",
                            lambda url, **kw: _FakeResp({"result": {"returnCode": 400, "messageText": "Consent id zorunludur."}}))
        import pytest
        with pytest.raises(gb.GarantiUnavailable):
            gb.fetch_garanti_statement(date(2020, 12, 1), date(2020, 12, 25), iban="TR62...")

    def test_configured_false_when_unset(self):
        assert gb.garanti_configured() is False
