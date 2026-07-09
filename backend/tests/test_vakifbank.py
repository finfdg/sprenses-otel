"""VakıfBank API içe-aktarma iskeleti — dedup ingest + finance_event + RBAC/kapalı davranış.

Dış API çağrısı test EDİLMEZ (kimlik/şema henüz yok); testlenebilir çekirdek: hesap seçimi,
bakiye-bazlı dedup, finance_event üretimi ve endpoint izin/kapalı-özellik davranışı.
"""
from datetime import date

from app.models.bank_account import BankAccount
from app.models.finance_event import FinanceEvent
from app.routers.finance.vakifbank import (
    _ingest_transactions,
    _is_vakifbank,
    _vakifbank_accounts,
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


class TestEndpoints:
    def test_status_requires_view(self, client, no_perm_user_headers):
        client.cookies.clear()  # fixture login'inin bıraktığı cookie'yi temizle (gerçek kimliksiz)
        assert client.get(f"{API}/status").status_code == 401
        assert client.get(f"{API}/status", headers=no_perm_user_headers).status_code == 403

    def test_status_ok_when_unconfigured(self, client, auth_headers):
        r = client.get(f"{API}/status", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["configured"] is False  # test ortamında kimlik yok
        assert "account_count" in body and "lookback_days" in body

    def test_sync_requires_use_then_503_unconfigured(self, client, auth_headers, no_perm_user_headers):
        # İzinsiz → 403 (permission dependency önce çalışır)
        assert client.post(f"{API}/sync", headers=no_perm_user_headers).status_code == 403
        # Yetkili ama kimlik yok → 503 (özellik kapalı)
        assert client.post(f"{API}/sync", headers=auth_headers).status_code == 503

    def test_test_connection_503_unconfigured(self, client, auth_headers, no_perm_user_headers):
        assert client.post(f"{API}/test-connection", headers=no_perm_user_headers).status_code == 403
        assert client.post(f"{API}/test-connection", headers=auth_headers).status_code == 503
