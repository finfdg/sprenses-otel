"""Stok / Depo Maliyet — Sedna içe aktarma + maliyet analizi testleri.

fetch_stock_* mock'lanır. Type 12=Alış(in), 29=Tüketim(consume); period date'ten türetilir.
"""
from datetime import date
from unittest.mock import patch

PREFIX = "/api/stok"
TARGET = "app.routers.stock"
SERVICE = "app.services.stock_service"

DEPOTS = [
    {"code": "002", "name": "ANA MUTFAK", "no_consumption": 0, "is_expense": 0},
    {"code": "003", "name": "BARLAR", "no_consumption": 0, "is_expense": 0},
]
PRODUCTS = [
    {"sedna_id": 1, "code": "P1", "name": "DOMATES", "currency": "TRY", "stock_type": 0,
     "current_stock": 100, "last_cost": 5},
    {"sedna_id": 2, "code": "P2", "name": "PEYNİR", "currency": "TRY", "stock_type": 0,
     "current_stock": 20, "last_cost": 50},
]
MOVES = [
    # Alış (in) — tedarikçi TEDARİK A, 500 TL
    {"owner_id": 1, "line_id": 1, "type_code": 12, "date": date(2026, 2, 1), "doc_no": "A1",
     "cons_depot": None, "supplier_code": "320.1", "supplier_name": "TEDARİK A",
     "product_id": 1, "product_code": "P1", "product_name": "DOMATES",
     "entry_depot": "001", "exit_depot": "", "quantity": 100, "unit_cost": 5, "net_amount": 500},
    # Tüketim (consume) ANA MUTFAK 300
    {"owner_id": 2, "line_id": 2, "type_code": 29, "date": date(2026, 3, 1), "doc_no": "Count",
     "cons_depot": "002", "supplier_code": None, "supplier_name": None,
     "product_id": 1, "product_code": "P1", "product_name": "DOMATES",
     "entry_depot": "", "exit_depot": "", "quantity": 60, "unit_cost": 5, "net_amount": 300},
    # Tüketim (consume) BARLAR 200
    {"owner_id": 3, "line_id": 3, "type_code": 29, "date": date(2026, 3, 1), "doc_no": "Count",
     "cons_depot": "003", "supplier_code": None, "supplier_name": None,
     "product_id": 2, "product_code": "P2", "product_name": "PEYNİR",
     "entry_depot": "", "exit_depot": "", "quantity": 4, "unit_cost": 50, "net_amount": 200},
]


def _import(client, headers, depots=DEPOTS, products=PRODUCTS, moves=MOVES):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{SERVICE}.fetch_stock_depots", return_value=depots), \
         patch(f"{SERVICE}.fetch_stock_products", return_value=products), \
         patch(f"{SERVICE}.fetch_stock_movements", return_value=moves):
        return client.post(f"{PREFIX}/sedna-import", headers=headers)


def test_import_requires_use(client, no_perm_user_headers):
    assert client.post(f"{PREFIX}/sedna-import", headers=no_perm_user_headers).status_code == 403


def test_import_creates_and_dedups(client, auth_headers):
    r = _import(client, auth_headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["depots_new"] == 2 and j["products_new"] == 2 and j["movements_new"] == 3
    # re-run → dedup (hareketler değişmez)
    j2 = _import(client, auth_headers).json()
    assert j2["movements_new"] == 0 and j2["products_new"] == 0


def test_summary(client, auth_headers):
    _import(client, auth_headers)
    s = client.get(f"{PREFIX}/summary", headers=auth_headers).json()
    assert s["purchases_total"] == 500.0 and s["consumption_total"] == 500.0
    assert s["product_count"] == 2 and s["in_stock_count"] == 2 and s["depot_count"] == 2
    # stok değeri = 100×5 + 20×50 = 1500
    assert s["stock_value"] == 1500.0


def test_cost_by_department(client, auth_headers):
    _import(client, auth_headers)
    items = client.get(f"{PREFIX}/cost-by-department", headers=auth_headers).json()["items"]
    by = {x["name"]: x["total"] for x in items}
    assert by["ANA MUTFAK"] == 300.0 and by["BARLAR"] == 200.0
    # azalan sıralı: ANA MUTFAK önce
    assert items[0]["name"] == "ANA MUTFAK"


def test_monthly_trend(client, auth_headers):
    _import(client, auth_headers)
    items = client.get(f"{PREFIX}/monthly-trend", headers=auth_headers).json()["items"]
    by = {x["period"]: x for x in items}
    assert by["2026-02"]["purchases"] == 500.0 and by["2026-02"]["consumption"] == 0.0
    assert by["2026-03"]["consumption"] == 500.0 and by["2026-03"]["purchases"] == 0.0


def test_by_supplier(client, auth_headers):
    _import(client, auth_headers)
    items = client.get(f"{PREFIX}/by-supplier", headers=auth_headers).json()["items"]
    assert items and items[0]["name"] == "TEDARİK A" and items[0]["total"] == 500.0


def test_products_filter(client, auth_headers):
    _import(client, auth_headers)
    # arama
    r = client.get(f"{PREFIX}/products?search=PEYN", headers=auth_headers).json()
    assert r["total"] == 1 and r["items"][0]["name"] == "PEYNİR"
    assert r["items"][0]["current_value"] == 1000.0  # 20×50
    # değer azalan sıralı (PEYNİR 1000 > DOMATES 500)
    full = client.get(f"{PREFIX}/products", headers=auth_headers).json()
    assert full["items"][0]["name"] == "PEYNİR"


def test_movements_filter(client, auth_headers):
    _import(client, auth_headers)
    # yön filtresi: tüketim 2, alış 1
    assert client.get(f"{PREFIX}/movements?direction=consume", headers=auth_headers).json()["total"] == 2
    assert client.get(f"{PREFIX}/movements?direction=in", headers=auth_headers).json()["total"] == 1
    # arama: tedarikçi
    r = client.get(f"{PREFIX}/movements?search=TEDAR", headers=auth_headers).json()
    assert r["total"] == 1 and r["items"][0]["type_label"] == "Alış"


def test_depots_with_consumption(client, auth_headers):
    _import(client, auth_headers)
    items = client.get(f"{PREFIX}/depots", headers=auth_headers).json()["items"]
    by = {x["name"]: x["consumption_total"] for x in items}
    assert by["ANA MUTFAK"] == 300.0 and by["BARLAR"] == 200.0


def test_view_requires_permission(client, no_perm_user_headers):
    assert client.get(f"{PREFIX}/summary", headers=no_perm_user_headers).status_code == 403
