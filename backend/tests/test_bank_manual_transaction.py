"""Manuel (ekstre-dışı) banka hareketi + ekstre yüklenince dedup (çift kayıt yok) testleri.

Manuel satır source='manual'; ilgili ekstre yüklenince o tarih aralığında otomatik silinir
(finance_event'i de invalidate edilir) → ekstre asıl kaynak, çift kayıt olmaz.
"""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction

PREFIX = "/api/finance/banks"


@pytest.fixture
def eur_account(db):
    acc = BankAccount(bank_name="Test EUR Bank", currency="EUR", iban="TR" + uuid.uuid4().hex[:24])
    db.add(acc)
    db.flush()
    # Açılış (ekstre) işlemi — bakiye temeli
    db.add(BankTransaction(
        account_id=acc.id, date=date(2026, 6, 1), description="Açılış",
        amount=100000, balance=100000, type="income", tx_hash=uuid.uuid4().hex, source="statement",
    ))
    db.flush()
    return acc.id


def test_manual_tx_requires_use(client, viewer_user_headers, eur_account):
    r = client.post(f"{PREFIX}/accounts/{eur_account}/manual-transaction",
                    json={"date": "2026-06-03", "amount": -20000, "description": "x"},
                    headers=viewer_user_headers)
    assert r.status_code == 403


def test_manual_tx_creates_and_computes_balance(client, auth_headers, eur_account, db):
    r = client.post(f"{PREFIX}/accounts/{eur_account}/manual-transaction",
                    json={"date": "2026-06-03", "amount": -20000, "description": "virman test"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["source"] == "manual"
    assert j["balance"] == 80000.0          # 100000 - 20000
    assert j["amount"] == -20000.0 and j["type"] == "expense"
    assert "[MANUEL]" in j["description"]
    # finance_event oluştu (yön -1)
    fe = db.execute(text("SELECT direction FROM finance_events WHERE source_type='bank' AND source_id=:i"),
                    {"i": j["id"]}).scalar()
    assert fe == -1


def test_manual_tx_validations(client, auth_headers, eur_account):
    # tutar sıfır
    assert client.post(f"{PREFIX}/accounts/{eur_account}/manual-transaction",
                       json={"date": "2026-06-03", "amount": 0, "description": "x"},
                       headers=auth_headers).status_code == 400
    # açıklama boş
    assert client.post(f"{PREFIX}/accounts/{eur_account}/manual-transaction",
                       json={"date": "2026-06-03", "amount": -10, "description": "  "},
                       headers=auth_headers).status_code == 400
    # hesap yok
    assert client.post(f"{PREFIX}/accounts/999999/manual-transaction",
                       json={"date": "2026-06-03", "amount": -10, "description": "x"},
                       headers=auth_headers).status_code == 404


def test_upload_purges_manual_no_duplicate(client, auth_headers, eur_account, db):
    from app.models.user import User
    from app.routers.finance.banks import _process_statement
    from app.utils.bank_parser import ParsedHeader, ParsedTransaction, ParseResult, compute_tx_hash

    # 1) Manuel hareket (06-10, -20000)
    r = client.post(f"{PREFIX}/accounts/{eur_account}/manual-transaction",
                    json={"date": "2026-06-10", "amount": -20000, "description": "ekstre bekleniyor"},
                    headers=auth_headers)
    assert r.status_code == 201
    manual_id = r.json()["id"]
    assert db.execute(text("SELECT count(*) FROM bank_transactions WHERE id=:i AND source='manual'"),
                      {"i": manual_id}).scalar() == 1
    assert db.execute(text("SELECT count(*) FROM finance_events WHERE source_type='bank' AND source_id=:i"),
                      {"i": manual_id}).scalar() == 1

    # 2) Ekstre yükle — gerçek -20000 (06-10) içinde, aralık [06-05, 06-10]
    user = db.query(User).first()
    parsed = ParseResult(
        header=ParsedHeader(iban=None, currency="EUR", period_start=date(2026, 6, 5), period_end=date(2026, 6, 15)),
        transactions=[
            ParsedTransaction(date=date(2026, 6, 5), receipt_no=None, description="onceki",
                              amount=-1000, balance=99000, type="expense",
                              tx_hash=compute_tx_hash(date(2026, 6, 5), None, -1000, "onceki")),
            ParsedTransaction(date=date(2026, 6, 10), receipt_no=None, description="GERCEK EKSTRE TRANSFER",
                              amount=-20000, balance=79000, type="expense",
                              tx_hash=compute_tx_hash(date(2026, 6, 10), None, -20000, "GERCEK EKSTRE TRANSFER")),
        ],
    )
    acc = db.query(BankAccount).filter(BankAccount.id == eur_account).first()
    res = _process_statement(db, acc, parsed, SimpleNamespace(filename="t.xlsx"),
                             "/tmp/t.xlsx", "xlsx", "t.xlsx", user, "127.0.0.1")
    assert res["manual_purged"] == 1

    # 3) Manuel satır silindi + fe invalidate + ÇİFT -20000 YOK (yalnız gerçek ekstre satırı)
    assert db.execute(text("SELECT count(*) FROM bank_transactions WHERE id=:i"), {"i": manual_id}).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM finance_events WHERE source_type='bank' AND source_id=:i"),
                      {"i": manual_id}).scalar() == 0
    rows = db.execute(text("SELECT source FROM bank_transactions WHERE account_id=:a AND amount=-20000"),
                      {"a": eur_account}).scalars().all()
    assert rows == ["statement"]  # tam olarak 1 satır ve o da ekstreden
