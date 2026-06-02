"""Departmanlar modülü testleri (finance.departmanlar).

Endpoint'ler: /api/finance/departmanlar/
- GET — Liste
- POST — Yeni departman
- PATCH /{id} — Güncelle
- DELETE /{id} — Sil (cari/bütçe bağlı kayıt varsa engellenir)
"""
from datetime import date

import pytest

from app.models.budget import Budget, BudgetCategory
from app.models.department import Department
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload


PREFIX = "/api/finance/departmanlar"


@pytest.fixture(autouse=True)
def _wipe_departments(db):
    """Her test başında departments tablosunu boşalt.

    Test izolasyonu için, migration seed'den veya başka testlerden gelen
    departman kayıtlarını siler. SAVEPOINT rollback test sonunda DB'yi temizler.
    """
    # Önce departmana bağlı kayıtları temizle
    db.query(VendorTransaction).filter(VendorTransaction.department_id.isnot(None)).update(
        {"department_id": None}, synchronize_session=False
    )
    db.query(Budget).delete()
    db.query(Department).delete()
    db.flush()
    yield


def _seed_department(db, **overrides):
    defaults = dict(
        name="Mutfak",
        code="MTF",
        is_active=True,
        sort_order=0,
    )
    defaults.update(overrides)
    dept = Department(**defaults)
    db.add(dept)
    db.flush()
    return dept


# ─── Yetki ──────────────────────────────────────────────


def test_list_requires_auth(client):
    res = client.get(f"{PREFIX}/")
    assert res.status_code in (401, 403)


def test_create_requires_auth(client):
    res = client.post(f"{PREFIX}/", json={"name": "X", "code": "X"})
    assert res.status_code in (401, 403)


def test_update_requires_auth(client):
    res = client.patch(f"{PREFIX}/1", json={"name": "Y"})
    assert res.status_code in (401, 403)


def test_delete_requires_auth(client):
    res = client.delete(f"{PREFIX}/1")
    assert res.status_code in (401, 403)


# ─── Liste ──────────────────────────────────────────────


def test_list_empty(client, auth_headers):
    """Boş tablo döner."""
    res = client.get(f"{PREFIX}/", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_list_returns_departments_ordered(client, auth_headers, db):
    """sort_order, sonra name'e göre sıralanır."""
    _seed_department(db, name="Mutfak", code="MTF", sort_order=20)
    _seed_department(db, name="Resepsiyon", code="RES", sort_order=10)
    _seed_department(db, name="Animasyon", code="ANI", sort_order=10)

    res = client.get(f"{PREFIX}/", headers=auth_headers)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 3
    # sort_order=10 olanlar önce, alfabetik
    assert items[0]["name"] == "Animasyon"
    assert items[1]["name"] == "Resepsiyon"
    assert items[2]["name"] == "Mutfak"


def test_list_includes_manager_name(client, auth_headers, db):
    """Manager atanmışsa manager_name döner."""
    from app.models.user import User
    admin = db.query(User).filter(User.username == "admin").first()
    assert admin is not None

    _seed_department(db, name="Yönetilen", code="YON", manager_id=admin.id)

    res = client.get(f"{PREFIX}/", headers=auth_headers)
    assert res.status_code == 200
    dept = next((d for d in res.json() if d["name"] == "Yönetilen"), None)
    assert dept is not None
    assert dept["manager_id"] == admin.id
    # manager_name dolu olmalı (boşluk dahil)
    assert dept["manager_name"] is not None
    assert len(dept["manager_name"]) > 0


# ─── Oluştur ────────────────────────────────────────────


def test_create_department(client, auth_headers, db):
    """Yeni departman oluşturulur, 201 döner."""
    res = client.post(
        f"{PREFIX}/",
        json={
            "name": "Temizlik",
            "code": "TMZ",
            "is_active": True,
            "sort_order": 5,
        },
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["name"] == "Temizlik"
    assert data["code"] == "TMZ"
    assert data["sort_order"] == 5

    db.expire_all()
    dept = db.query(Department).filter(Department.code == "TMZ").first()
    assert dept is not None


def test_create_duplicate_code_fails(client, auth_headers, db):
    """Aynı kodu kullanan ikinci departman 400 verir."""
    _seed_department(db, name="Eski", code="DUP")

    res = client.post(
        f"{PREFIX}/",
        json={"name": "Yeni", "code": "DUP"},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "zaten kayıtlı" in res.json()["detail"].lower()


def test_create_duplicate_name_fails(client, auth_headers, db):
    """Aynı ismi kullanan ikinci departman 400 verir."""
    _seed_department(db, name="Aynı Ad", code="A1")

    res = client.post(
        f"{PREFIX}/",
        json={"name": "Aynı Ad", "code": "A2"},
        headers=auth_headers,
    )
    assert res.status_code == 400


# ─── Güncelle ───────────────────────────────────────────


def test_update_department(client, auth_headers, db):
    """Var olan departman güncellenir."""
    dept = _seed_department(db, name="EskiAd", code="ESK", sort_order=10)

    res = client.patch(
        f"{PREFIX}/{dept.id}",
        json={"name": "YeniAd", "sort_order": 99},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["name"] == "YeniAd"
    assert data["sort_order"] == 99
    # Code güncellenmedi, eski kaldı
    assert data["code"] == "ESK"


def test_update_nonexistent_returns_404(client, auth_headers):
    """Var olmayan departman için 404."""
    res = client.patch(
        f"{PREFIX}/9999999",
        json={"name": "Yeni"},
        headers=auth_headers,
    )
    assert res.status_code == 404


# ─── Sil ────────────────────────────────────────────────


def test_delete_department(client, auth_headers, db):
    """Bağlı kayıt yoksa silinir, 204 döner."""
    dept = _seed_department(db, name="Silinecek", code="SIL")
    dept_id = dept.id

    res = client.delete(f"{PREFIX}/{dept_id}", headers=auth_headers)
    assert res.status_code == 204

    db.expire_all()
    assert db.query(Department).filter(Department.id == dept_id).first() is None


def test_delete_nonexistent_returns_404(client, auth_headers):
    """Var olmayan ID için 404."""
    res = client.delete(f"{PREFIX}/9999999", headers=auth_headers)
    assert res.status_code == 404


def test_delete_blocked_when_vendor_tx_exists(client, auth_headers, db):
    """Departmana atanmış cari işlem varsa silme engellenir."""
    dept = _seed_department(db, name="Bağlı", code="BAG")

    # Önce bir vendor + upload + vendor_transaction oluştur
    vendor = Vendor(hesap_kodu="DEPT_TEST_V1", hesap_adi="Test Cari")
    db.add(vendor)
    upload = VendorUpload(file_name="t.xlsx", file_url="/x")
    db.add(upload)
    db.flush()
    vtx = VendorTransaction(
        vendor_id=vendor.id,
        upload_id=upload.id,
        date=date(2026, 4, 1),
        borc=0,
        alacak=100,
        tx_hash="testdep001",
        department_id=dept.id,
    )
    db.add(vtx)
    db.flush()

    res = client.delete(f"{PREFIX}/{dept.id}", headers=auth_headers)
    assert res.status_code == 400
    assert "cari işlem" in res.json()["detail"].lower()


def test_delete_blocked_when_budget_exists(client, auth_headers, db):
    """Departmana atanmış bütçe kaydı varsa silme engellenir."""
    dept = _seed_department(db, name="Bütçeli", code="BTC")

    # Bütçe kategori + bütçe kaydı (unique name/type'a dikkat — testdep prefix)
    cat = BudgetCategory(name="testdep_kategori", type="expense", is_active=True, sort_order=0)
    db.add(cat)
    db.flush()
    budget = Budget(
        department_id=dept.id,
        category_id=cat.id,
        year=2026,
        month=4,
        planned_amount=1000,
        actual_amount=0,
        currency="TRY",
    )
    db.add(budget)
    db.flush()

    res = client.delete(f"/api/finance/departmanlar/{dept.id}", headers=auth_headers)
    assert res.status_code == 400
    assert "bütçe" in res.json()["detail"].lower()
