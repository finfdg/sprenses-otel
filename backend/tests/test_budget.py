"""Bütçe modülü CRUD testleri.

Endpoint'ler: /api/finance/butce/
Departman ve kategori yönetimi + bütçe kayıtları + özet.
"""

import pytest

PREFIX = "/api/finance/butce"
DEPT_PREFIX = "/api/finance/departmanlar"


# ─── Yardımcı ──────────────────────────────────────────────

def _create_category(client, auth_headers, **overrides):
    payload = {"name": "Test Kategori", "type": "expense", "is_active": True, "sort_order": 0}
    payload.update(overrides)
    return client.post(f"{PREFIX}/kategoriler", json=payload, headers=auth_headers)


def _get_or_create_department(client, auth_headers):
    """Test için departman ID'si al — varsa ilkini, yoksa oluştur."""
    resp = client.get(f"{DEPT_PREFIX}/", headers=auth_headers)
    if resp.status_code == 200:
        items = resp.json()
        if isinstance(items, list) and len(items) > 0:
            return items[0]["id"]
        elif isinstance(items, dict) and items.get("items") and len(items["items"]) > 0:
            return items["items"][0]["id"]
    # Oluştur
    create_resp = client.post(
        f"{DEPT_PREFIX}/",
        json={"name": "Test Departman", "code": "TEST_DEPT", "is_active": True},
        headers=auth_headers,
    )
    if create_resp.status_code in (200, 201):
        return create_resp.json()["id"]
    return None


def _create_budget(client, auth_headers, dept_id, cat_id, **overrides):
    payload = {
        "department_id": dept_id,
        "category_id": cat_id,
        "year": 2099,
        "month": 1,
        "planned_amount": 10000,
        "currency": "TRY",
    }
    payload.update(overrides)
    return client.post(f"{PREFIX}/", json=payload, headers=auth_headers)


# ─── KATEGORİ CRUD ──────────────────────────────────────────


class TestBudgetCategories:

    def test_list_categories(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/kategoriler", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_category(self, client, auth_headers):
        resp = _create_category(client, auth_headers, name="Ofis Giderleri")
        assert resp.status_code in (200, 201)
        assert resp.json()["name"] == "Ofis Giderleri"
        assert resp.json()["type"] == "expense"

    def test_create_income_category(self, client, auth_headers):
        resp = _create_category(client, auth_headers, name="Kira Geliri", type="income")
        assert resp.status_code in (200, 201)
        assert resp.json()["type"] == "income"

    def test_create_invalid_type(self, client, auth_headers):
        resp = _create_category(client, auth_headers, type="invalid")
        assert resp.status_code == 422

    def test_update_category(self, client, auth_headers):
        create_resp = _create_category(client, auth_headers, name="Güncellenecek")
        cat_id = create_resp.json()["id"]
        resp = client.patch(
            f"{PREFIX}/kategoriler/{cat_id}",
            json={"name": "Güncellendi"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Güncellendi"

    def test_update_category_not_found(self, client, auth_headers):
        resp = client.patch(
            f"{PREFIX}/kategoriler/999999",
            json={"name": "X"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_delete_category(self, client, auth_headers):
        create_resp = _create_category(client, auth_headers, name="Silinecek Kat")
        cat_id = create_resp.json()["id"]
        resp = client.delete(f"{PREFIX}/kategoriler/{cat_id}", headers=auth_headers)
        assert resp.status_code == 200

    def test_delete_category_not_found(self, client, auth_headers):
        resp = client.delete(f"{PREFIX}/kategoriler/999999", headers=auth_headers)
        assert resp.status_code == 404

    def test_without_auth(self, client):
        resp = client.get(f"{PREFIX}/kategoriler")
        assert resp.status_code in (401, 403)


# ─── BÜTÇE CRUD ─────────────────────────────────────────────


class TestBudgetCRUD:

    def test_list_budgets(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?year=2099", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_create_budget(self, client, auth_headers):
        dept_id = _get_or_create_department(client, auth_headers)
        if not dept_id:
            pytest.skip("Departman oluşturulamadı")
        cat_resp = _create_category(client, auth_headers, name="Bütçe Test Kat")
        cat_id = cat_resp.json()["id"]

        resp = _create_budget(client, auth_headers, dept_id, cat_id, year=2099, month=6)
        assert resp.status_code in (200, 201)

    def test_create_budget_upsert(self, client, auth_headers):
        """Aynı (dept, cat, year, month) için tekrar oluşturma → güncelleme."""
        dept_id = _get_or_create_department(client, auth_headers)
        if not dept_id:
            pytest.skip("Departman oluşturulamadı")
        cat_resp = _create_category(client, auth_headers, name="Upsert Kat")
        cat_id = cat_resp.json()["id"]

        resp1 = _create_budget(client, auth_headers, dept_id, cat_id, year=2099, month=3, planned_amount=5000)
        assert resp1.status_code in (200, 201)

        resp2 = _create_budget(client, auth_headers, dept_id, cat_id, year=2099, month=3, planned_amount=8000)
        assert resp2.status_code in (200, 201)
        assert resp2.json()["planned_amount"] == 8000.0

    def test_bulk_upsert(self, client, auth_headers):
        dept_id = _get_or_create_department(client, auth_headers)
        if not dept_id:
            pytest.skip("Departman oluşturulamadı")
        cat_resp = _create_category(client, auth_headers, name="Bulk Kat")
        cat_id = cat_resp.json()["id"]

        items = [
            {"department_id": dept_id, "category_id": cat_id, "year": 2099, "month": m, "planned_amount": 1000 * m}
            for m in range(1, 4)
        ]
        resp = client.post(f"{PREFIX}/bulk", json={"items": items}, headers=auth_headers)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "created" in data or "updated" in data

    def test_delete_budget(self, client, auth_headers):
        dept_id = _get_or_create_department(client, auth_headers)
        if not dept_id:
            pytest.skip("Departman oluşturulamadı")
        cat_resp = _create_category(client, auth_headers, name="Sil Kat")
        cat_id = cat_resp.json()["id"]

        create_resp = _create_budget(client, auth_headers, dept_id, cat_id, year=2099, month=11)
        budget_id = create_resp.json()["id"]

        resp = client.delete(f"{PREFIX}/{budget_id}", headers=auth_headers)
        assert resp.status_code == 200

    def test_delete_budget_not_found(self, client, auth_headers):
        resp = client.delete(f"{PREFIX}/999999", headers=auth_headers)
        assert resp.status_code == 404


# ─── ÖZET ────────────────────────────────────────────────────


class TestBudgetSummary:

    def test_summary_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/summary?year=2099", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_monthly_summary_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/monthly-summary?year=2099", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # 12 ay olmalı
        assert len(data) == 12

    def test_summary_without_auth(self, client):
        resp = client.get(f"{PREFIX}/summary?year=2099")
        assert resp.status_code in (401, 403)


# ─── YIL SEÇİCİ ───────────────────────────────────────────────


class TestBudgetYears:
    """Yıl seçici veriden türetilir — gelecekteki (sabit dizi dışı) yıl gizlenmemeli."""

    def test_years_includes_future_data_year(self, client, auth_headers):
        dept_id = _get_or_create_department(client, auth_headers)
        if not dept_id:
            pytest.skip("Departman oluşturulamadı")
        cat_id = _create_category(client, auth_headers, name="Yıl Kat").json()["id"]
        # Sabit dizinin (eski [2025..2028]) dışında bir gelecek yıl
        _create_budget(client, auth_headers, dept_id, cat_id, year=2099, month=6, planned_amount=1234)

        resp = client.get(f"{PREFIX}/years", headers=auth_headers)
        assert resp.status_code == 200
        years = resp.json()["years"]
        assert isinstance(years, list)
        assert 2099 in years
        # Artan sıralı
        assert years == sorted(years)

    def test_years_without_auth(self, client):
        resp = client.get(f"{PREFIX}/years")
        assert resp.status_code in (401, 403)
