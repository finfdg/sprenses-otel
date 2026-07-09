"""Yapı Kredi API içe-aktarma — response parse (doküman örneğiyle) + para birimi eşleme.

Dış HTTP çağrısı monkeypatch ile taklit edilir (kimlik/ağ yok). Doküman "Account Transaction
List" örnek response'u üzerinden: işaretli tutar, tarih (DD.MM.YYYY), availBal→balance eşlemesi,
açıklama, dekont no ve response zarfı (response.return.list) doğrulanır.
"""
from datetime import date

from app.utils import yapikredi_api as yk

# Doküman "Output Parametreleri" örneği (kısaltılmış — 2 kayıt, 100'den az → tek sayfa)
_DOC_LIST = [
    {"amount": "-1000", "postNarr": "Vadeli mevduat açılış", "inputDate": "26.10.2017",
     "availBal": "800", "balance": "1800", "tranType": "D", "createTime": "11:41:38",
     "trxnName": "YATIS", "receiptId": "261017005026", "postNo": "23"},
    {"amount": "250", "postNarr": "Hesaba Havale", "inputDate": "26.10.2017",
     "availBal": "2350", "balance": "2100", "tranType": "C", "createTime": "10:03:49",
     "trxnName": "EFTVR", "receiptId": "261017005008", "postNo": "20"},
]


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _patch_httpx(monkeypatch, txn_list):
    def fake_post(url, **kwargs):
        if "token" in url:
            return _FakeResp({"access_token": "TESTTOKEN", "token_type": "Bearer", "expires_in": 3600})
        return _FakeResp({"response": {"return": {"postNo": "19", "list": txn_list}}})
    monkeypatch.setattr(yk.httpx, "post", fake_post)


class TestYapikrediParse:
    def test_parses_doc_example(self, monkeypatch):
        _patch_httpx(monkeypatch, _DOC_LIST)
        res = yk.fetch_yapikredi_statement("10002000", "TL", date(2017, 10, 1), date(2017, 11, 1))
        txns = res.transactions
        assert len(txns) == 2
        # işaretli tutar → yön
        assert txns[0].amount == -1000.0 and txns[0].type == "expense"
        assert txns[1].amount == 250.0 and txns[1].type == "income"
        # bakiye = availBal (işlem SONRASI), balance (öncesi) DEĞİL
        assert txns[0].balance == 800.0
        assert txns[1].balance == 2350.0
        # tarih DD.MM.YYYY, dekont, açıklama, saat
        assert txns[0].date == date(2017, 10, 26)
        assert txns[0].receipt_no == "261017005026"
        assert txns[0].description == "Vadeli mevduat açılış"
        assert txns[0].time == "11:41:38"
        # header
        assert res.header.account_no == "10002000" and res.header.currency == "TL"

    def test_empty_list(self, monkeypatch):
        _patch_httpx(monkeypatch, [])
        res = yk.fetch_yapikredi_statement("10002000", "TL", date(2017, 10, 1), date(2017, 11, 1))
        assert res.transactions == []

    def test_same_day_dup_gets_distinct_hash(self, monkeypatch):
        # Aynı gün + aynı tutar + aynı açıklama iki kez → tx_hash seq ile ayrışır (çift kayıt olmaz)
        dup = [_DOC_LIST[0], dict(_DOC_LIST[0])]
        _patch_httpx(monkeypatch, dup)
        res = yk.fetch_yapikredi_statement("10002000", "TL", date(2017, 10, 1), date(2017, 11, 1))
        assert len(res.transactions) == 2
        assert res.transactions[0].tx_hash != res.transactions[1].tx_hash


class TestCurrencyMapping:
    def test_ykb_ccy(self):
        from cron_fetch_bank_statements import _ykb_ccy
        assert _ykb_ccy("TRY") == "TL"    # sistem TRY → YKB TL
        assert _ykb_ccy("TL") == "TL"
        assert _ykb_ccy(None) == "TL"
        assert _ykb_ccy("EUR") == "EUR"   # döviz aynen
        assert _ykb_ccy("USD") == "USD"
