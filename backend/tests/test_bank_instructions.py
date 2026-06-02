"""Banka talimatları modülü testleri (bank_instructions).

Endpoint'ler:
- POST /api/finance/bank-instructions/transfer — EFT/Havale PDF
- POST /api/finance/bank-instructions/currency-exchange — Döviz bozma PDF
- GET /api/finance/bank-instructions/accounts — Hesap listesi (talimat için)

PDF içeriği binary olarak parse edilmez; sadece status=200 ve content-type=
application/pdf seviyesinde doğrulanır.
"""
import pytest

from app.models.bank_account import BankAccount


PREFIX = "/api/finance/bank-instructions"


def _seed_account(db, **overrides):
    defaults = dict(
        bank_name="Test Bank",
        branch_name="Merkez",
        account_no="12345",
        iban="TR000000000000000000000001",
        currency="TRY",
        holder_name="Sprenses Otel",
        is_active=True,
    )
    defaults.update(overrides)
    acc = BankAccount(**defaults)
    db.add(acc)
    db.flush()
    return acc


# ─── Yetki ──────────────────────────────────────────────


def test_accounts_requires_auth(client):
    """GET accounts auth gerektirir."""
    res = client.get(f"{PREFIX}/accounts")
    assert res.status_code in (401, 403)


def test_transfer_requires_auth(client):
    """POST transfer auth gerektirir."""
    res = client.post(
        f"{PREFIX}/transfer",
        json={"source_account_id": 1, "dest_account_id": 2, "amount": 1000},
    )
    assert res.status_code in (401, 403)


def test_currency_exchange_requires_auth(client):
    """POST currency-exchange auth gerektirir."""
    res = client.post(
        f"{PREFIX}/currency-exchange",
        json={"source_account_id": 1, "target_currency": "EUR", "amount": 1000},
    )
    assert res.status_code in (401, 403)


# ─── /accounts ──────────────────────────────────────────


def test_list_accounts_returns_active_only(client, auth_headers, db):
    """Sadece aktif hesaplar listelenir."""
    _seed_account(db, iban="TR" + "1" * 22, bank_name="Aktif Bank", is_active=True)
    _seed_account(db, iban="TR" + "2" * 22, bank_name="Pasif Bank", is_active=False)

    res = client.get(f"{PREFIX}/accounts", headers=auth_headers)
    assert res.status_code == 200
    accounts = res.json()
    assert isinstance(accounts, list)
    bank_names = {a["bank_name"] for a in accounts}
    assert "Aktif Bank" in bank_names
    assert "Pasif Bank" not in bank_names


def test_list_accounts_response_shape(client, auth_headers, db):
    """Her hesap doğru alanları içermeli."""
    _seed_account(db, iban="TR" + "9" * 22, bank_name="Form Bank", currency="EUR")

    res = client.get(f"{PREFIX}/accounts", headers=auth_headers)
    assert res.status_code == 200
    accounts = res.json()
    found = next((a for a in accounts if a["bank_name"] == "Form Bank"), None)
    assert found is not None
    for key in ("id", "bank_name", "iban", "currency", "label"):
        assert key in found
    # Label IBAN'ın son 4 karakteriyle bitmeli
    assert found["label"].endswith("9999)")


# ─── /transfer ──────────────────────────────────────────


def test_transfer_rejects_zero_amount(client, auth_headers, db):
    """amount <= 0 ise 400."""
    src = _seed_account(db, iban="TR" + "a" * 22, bank_name="A")
    dst = _seed_account(db, iban="TR" + "b" * 22, bank_name="B")

    res = client.post(
        f"{PREFIX}/transfer",
        json={"source_account_id": src.id, "dest_account_id": dst.id, "amount": 0},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "sıfırdan büyük" in res.json()["detail"].lower()


def test_transfer_rejects_same_account(client, auth_headers, db):
    """Kaynak == hedef ise 400."""
    acc = _seed_account(db, iban="TR" + "c" * 22)

    res = client.post(
        f"{PREFIX}/transfer",
        json={"source_account_id": acc.id, "dest_account_id": acc.id, "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "aynı olamaz" in res.json()["detail"].lower()


def test_transfer_rejects_currency_mismatch(client, auth_headers, db):
    """Farklı para birimleri için 400 (TRY → EUR için Döviz Bozma kullanılır)."""
    src = _seed_account(db, iban="TR" + "d" * 22, bank_name="TL Bank", currency="TRY")
    dst = _seed_account(db, iban="TR" + "e" * 22, bank_name="EUR Bank", currency="EUR")

    res = client.post(
        f"{PREFIX}/transfer",
        json={"source_account_id": src.id, "dest_account_id": dst.id, "amount": 1000},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "farklı para" in res.json()["detail"].lower() or "döviz bozma" in res.json()["detail"].lower()


def test_transfer_404_when_account_not_found(client, auth_headers, db):
    """Var olmayan hesap için 404."""
    src = _seed_account(db, iban="TR" + "f" * 22)

    res = client.post(
        f"{PREFIX}/transfer",
        json={"source_account_id": src.id, "dest_account_id": 99999999, "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_transfer_returns_pdf(client, auth_headers, db):
    """Geçerli istek PDF binary döner."""
    src = _seed_account(
        db, iban="TR" + "g" * 22, bank_name="Garanti", branch_name="Manavgat",
        account_no="100200300", currency="TRY",
    )
    dst = _seed_account(
        db, iban="TR" + "h" * 22, bank_name="İş Bankası", branch_name="Antalya",
        account_no="400500600", currency="TRY",
    )

    res = client.post(
        f"{PREFIX}/transfer",
        json={
            "source_account_id": src.id,
            "dest_account_id": dst.id,
            "amount": 50000.50,
            "instruction_date": "2026-04-15",
            "description": "Test transferi",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/pdf")
    # PDF magic bytes
    assert res.content[:4] == b"%PDF"
    # filename header
    cd = res.headers.get("content-disposition", "")
    assert "talimat" in cd.lower()


def test_transfer_pdf_naming_same_bank_is_havale(client, auth_headers, db):
    """Aynı banka + TL → 'havale' dosya adı."""
    src = _seed_account(
        db, iban="TR" + "i" * 22, bank_name="Halkbank", currency="TRY",
    )
    dst = _seed_account(
        db, iban="TR" + "j" * 22, bank_name="HALKBANK", currency="TRY",
    )

    res = client.post(
        f"{PREFIX}/transfer",
        json={"source_account_id": src.id, "dest_account_id": dst.id, "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    assert "havale" in cd.lower()


def test_transfer_pdf_naming_different_bank_is_eft(client, auth_headers, db):
    """Farklı banka + TL → 'eft' dosya adı."""
    src = _seed_account(db, iban="TR" + "k" * 22, bank_name="Garanti", currency="TRY")
    dst = _seed_account(db, iban="TR" + "l" * 22, bank_name="Akbank", currency="TRY")

    res = client.post(
        f"{PREFIX}/transfer",
        json={"source_account_id": src.id, "dest_account_id": dst.id, "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    assert "eft" in cd.lower()


# ─── /currency-exchange ──────────────────────────────────


def test_currency_exchange_rejects_zero_amount(client, auth_headers, db):
    """amount <= 0 → 400."""
    src = _seed_account(db, iban="TR" + "m" * 22, currency="TRY")

    res = client.post(
        f"{PREFIX}/currency-exchange",
        json={"source_account_id": src.id, "target_currency": "EUR", "amount": 0},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_currency_exchange_rejects_invalid_currency(client, auth_headers, db):
    """Geçersiz para birimi → 400."""
    src = _seed_account(db, iban="TR" + "n" * 22, currency="TRY")

    res = client.post(
        f"{PREFIX}/currency-exchange",
        json={"source_account_id": src.id, "target_currency": "JPY", "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "geçersiz" in res.json()["detail"].lower()


def test_currency_exchange_rejects_same_currency(client, auth_headers, db):
    """Kaynak ile hedef para birimi aynı ise 400."""
    src = _seed_account(db, iban="TR" + "o" * 22, currency="TRY")

    res = client.post(
        f"{PREFIX}/currency-exchange",
        json={"source_account_id": src.id, "target_currency": "TRY", "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "aynı olamaz" in res.json()["detail"].lower()


def test_currency_exchange_returns_pdf(client, auth_headers, db):
    """Geçerli döviz bozma → PDF döner."""
    src = _seed_account(
        db, iban="TR" + "p" * 22, bank_name="Garanti",
        branch_name="Şube", account_no="111", currency="TRY",
    )

    res = client.post(
        f"{PREFIX}/currency-exchange",
        json={
            "source_account_id": src.id,
            "target_currency": "EUR",
            "amount": 25000,
            "instruction_date": "2026-05-01",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content[:4] == b"%PDF"


def test_currency_exchange_with_target_account(client, auth_headers, db):
    """target_account_id verilirse PDF üretilir (aktarım talimatı)."""
    src = _seed_account(db, iban="TR" + "q" * 22, bank_name="Garanti", currency="TRY")
    target = _seed_account(db, iban="TR" + "r" * 22, bank_name="Garanti", currency="EUR")

    res = client.post(
        f"{PREFIX}/currency-exchange",
        json={
            "source_account_id": src.id,
            "target_account_id": target.id,
            "target_currency": "EUR",
            "amount": 1000,
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.content[:4] == b"%PDF"
