"""İşlem etiketleme modülü testleri (transaction_tags).

Endpoint'ler:
- GET/POST /api/finance/tags/categories — Kategori CRUD
- GET /api/finance/tags/untagged-count — Etiketsiz işlem sayısı
- PATCH /api/finance/tags/transactions/{tx_id} — Tekil etiket atama
- POST /api/finance/tags/transactions/bulk — Toplu etiket atama
- GET /api/finance/tags/payment-methods — Ödeme yöntemleri
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.transaction_category import TransactionCategory


PREFIX = "/api/finance/tags"


@pytest.fixture(autouse=True)
def _clean_tags(db):
    """Test izolasyonu: bank_transactions ve transaction_categories temizle.

    Test DB seed'inde mevcut işlemler/kategoriler testleri etkilemesin diye
    SAVEPOINT içinde silinir — test sonunda rollback ile geri gelir.
    """
    from app.models.finance_event import FinanceEvent
    db.query(FinanceEvent).delete()
    db.query(BankTransaction).delete()
    db.query(TransactionCategory).delete()
    db.flush()
    yield


def _seed_account(db, **overrides):
    defaults = dict(
        bank_name="Test Bank",
        iban="TR000000000000000000000001",
        currency="TRY",
        is_active=True,
    )
    defaults.update(overrides)
    acc = BankAccount(**defaults)
    db.add(acc)
    db.flush()
    return acc


def _seed_tx(db, account_id, **overrides):
    defaults = dict(
        account_id=account_id,
        date=date(2026, 4, 1),
        description="Test işlem",
        amount=Decimal("-100.00"),
        type="expense",
        tx_hash="testhash" + str(overrides.get("seq", 0)).zfill(4),
    )
    defaults.update(overrides)
    defaults.pop("seq", None)
    tx = BankTransaction(**defaults)
    db.add(tx)
    db.flush()
    return tx


def _seed_category(db, **overrides):
    defaults = dict(name="Test Kategori", color="blue", sort_order=0, is_active=True)
    defaults.update(overrides)
    # Mevcut (seed) kategoriyi yeniden eklemeye çalışma — varsa onu döndür
    existing = (
        db.query(TransactionCategory)
        .filter(TransactionCategory.name == defaults["name"])
        .first()
    )
    if existing:
        return existing
    cat = TransactionCategory(**defaults)
    db.add(cat)
    db.flush()
    return cat


# ─── Yetki ──────────────────────────────────────────────


def test_categories_list_requires_auth(client):
    """GET kategoriler auth gerektirir."""
    res = client.get(f"{PREFIX}/categories")
    assert res.status_code in (401, 403)


def test_categories_create_requires_auth(client):
    """POST kategori auth gerektirir."""
    res = client.post(f"{PREFIX}/categories", json={"name": "Yeni", "color": "red"})
    assert res.status_code in (401, 403)


def test_untagged_count_requires_auth(client):
    """untagged-count auth gerektirir."""
    res = client.get(f"{PREFIX}/untagged-count")
    assert res.status_code in (401, 403)


def test_tag_tx_requires_auth(client):
    """PATCH tx etiketleme auth gerektirir."""
    res = client.patch(f"{PREFIX}/transactions/1", json={"category_id": 1})
    assert res.status_code in (401, 403)


# ─── Kategori CRUD ──────────────────────────────────────


def test_list_categories(client, auth_headers, db):
    """Aktif kategoriler listelenir, sort_order'a göre sıralı."""
    _seed_category(db, name="ZSon", sort_order=10)
    _seed_category(db, name="Aİlk", sort_order=1)
    # Pasif kategori — listede görünmemeli
    _seed_category(db, name="Pasif", sort_order=5, is_active=False)

    res = client.get(f"{PREFIX}/categories", headers=auth_headers)
    assert res.status_code == 200
    cats = res.json()
    assert isinstance(cats, list)
    names = [c["name"] for c in cats]
    # Pasif gizli
    assert "Pasif" not in names
    assert "Aİlk" in names
    assert "ZSon" in names
    # sort_order'a göre sıralı (1 < 10)
    assert names.index("Aİlk") < names.index("ZSon")


def test_create_category(client, auth_headers, db):
    """Yeni kategori oluşturulur, sort_order otomatik atanır."""
    res = client.post(
        f"{PREFIX}/categories",
        json={"name": "Test Kategorisi", "color": "purple"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["name"] == "Test Kategorisi"
    assert data["color"] == "purple"
    assert data["is_active"] is True

    # DB'de var
    db.expire_all()
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Test Kategorisi").first()
    assert cat is not None


def test_create_duplicate_category_fails(client, auth_headers, db):
    """Aynı isimde ikinci kategori 400 verir."""
    _seed_category(db, name="Tekrar")

    res = client.post(
        f"{PREFIX}/categories",
        json={"name": "Tekrar", "color": "red"},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "zaten var" in res.json()["detail"].lower()


def test_create_category_strips_whitespace(client, auth_headers, db):
    """Adın başı/sonu temizlenir."""
    res = client.post(
        f"{PREFIX}/categories",
        json={"name": "  Boşluklu  ", "color": "gray"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Boşluklu"


def test_create_category_validation(client, auth_headers):
    """Boş isim 422 verir (min_length=1)."""
    res = client.post(
        f"{PREFIX}/categories",
        json={"name": "", "color": "blue"},
        headers=auth_headers,
    )
    assert res.status_code == 422


# ─── Etiketsiz Sayım ────────────────────────────────────


def test_untagged_count_empty(client, auth_headers):
    """Banka işlemi yokken count=0."""
    res = client.get(f"{PREFIX}/untagged-count", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["count"] == 0


def test_untagged_count_excludes_pre_2026(client, auth_headers, db):
    """2026-01-01 öncesi etiketsiz işlemler sayılmaz (MIN_DATE filtresi)."""
    acc = _seed_account(db)
    # 2026 sonrası — sayılır
    _seed_tx(db, acc.id, date=date(2026, 4, 1), seq=1, category_id=None)
    # 2025 — sayılmaz
    _seed_tx(db, acc.id, date=date(2025, 4, 1), seq=2, category_id=None)

    res = client.get(f"{PREFIX}/untagged-count", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["count"] == 1


def test_untagged_count_excludes_tagged(client, auth_headers, db):
    """Kategori atanmış işlemler sayılmaz."""
    acc = _seed_account(db)
    cat = _seed_category(db, name="Etiketlendi")
    _seed_tx(db, acc.id, date=date(2026, 4, 1), seq=1, category_id=cat.id)
    _seed_tx(db, acc.id, date=date(2026, 4, 1), seq=2, category_id=None)

    res = client.get(f"{PREFIX}/untagged-count", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["count"] == 1


# ─── Etiket Atama ────────────────────────────────────────


def test_tag_transaction_basic(client, auth_headers, db):
    """Banka işlemine kategori atanır."""
    acc = _seed_account(db)
    tx = _seed_tx(db, acc.id, seq=1)
    cat = _seed_category(db, name="Diğer", color="gray")

    res = client.patch(
        f"{PREFIX}/transactions/{tx.id}",
        json={"category_id": cat.id, "tag_note": "Açıklama notu"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True

    db.expire_all()
    refreshed = db.query(BankTransaction).filter(BankTransaction.id == tx.id).first()
    assert refreshed.category_id == cat.id
    assert refreshed.tag_note == "Açıklama notu"
    assert refreshed.tag_source == "manual"


def test_tag_transaction_remove_tag(client, auth_headers, db):
    """category_id=None gönderince etiket kalkar."""
    acc = _seed_account(db)
    cat = _seed_category(db, name="Diğer")
    tx = _seed_tx(db, acc.id, seq=1, category_id=cat.id, tag_note="n", tag_source="manual")

    res = client.patch(
        f"{PREFIX}/transactions/{tx.id}",
        json={"category_id": None},
        headers=auth_headers,
    )
    assert res.status_code == 200

    db.expire_all()
    refreshed = db.query(BankTransaction).filter(BankTransaction.id == tx.id).first()
    assert refreshed.category_id is None
    assert refreshed.tag_source is None


def test_tag_transaction_not_found(client, auth_headers):
    """Var olmayan tx için 404."""
    res = client.patch(
        f"{PREFIX}/transactions/9999999",
        json={"category_id": None},
        headers=auth_headers,
    )
    assert res.status_code == 404


# ─── Toplu Etiket ────────────────────────────────────────


def test_bulk_tag_empty_list_fails(client, auth_headers):
    """Boş listede 400 dönmeli."""
    res = client.post(
        f"{PREFIX}/transactions/bulk",
        json={"transaction_ids": [], "category_id": None},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_bulk_tag_assigns_to_multiple(client, auth_headers, db):
    """Toplu etiketleme birden çok işleme uygulanır."""
    acc = _seed_account(db)
    cat = _seed_category(db, name="Toplu")
    tx1 = _seed_tx(db, acc.id, seq=1)
    tx2 = _seed_tx(db, acc.id, seq=2)
    tx3 = _seed_tx(db, acc.id, seq=3)

    res = client.post(
        f"{PREFIX}/transactions/bulk",
        json={
            "transaction_ids": [tx1.id, tx2.id, tx3.id],
            "category_id": cat.id,
            "tag_note": "toplu not",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["count"] == 3

    db.expire_all()
    refreshed = db.query(BankTransaction).filter(
        BankTransaction.id.in_([tx1.id, tx2.id, tx3.id])
    ).all()
    assert all(t.category_id == cat.id for t in refreshed)
    assert all(t.tag_note == "toplu not" for t in refreshed)


# ─── Ödeme Yöntemleri ───────────────────────────────────


def test_payment_methods_list(client, auth_headers):
    """Ödeme yöntemi listesi döner."""
    res = client.get(f"{PREFIX}/payment-methods", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    # PAYMENT_METHOD_LABELS dict döner
    assert isinstance(data, dict)
    # En azından bir ödeme yöntemi olmalı
    assert len(data) > 0
