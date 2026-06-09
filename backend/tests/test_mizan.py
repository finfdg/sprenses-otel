"""Mizan — Sedna canlı geçici mizan (trial balance) endpoint'leri (fetch_* mock'lanır, CI'da tünel yok)."""
from datetime import date
from unittest.mock import patch

import pytest

from app.routers.accounting import mizan as mizan_mod

PREFIX = "/api/accounting/mizan"
TARGET = "app.routers.accounting.mizan"


@pytest.fixture(autouse=True)
def _clear_mizan_cache():
    """60sn TTL cache testler arası sızmasın (aynı tarih aralığı farklı mock veri çakışmasını önle)."""
    mizan_mod._cache.clear()
    yield
    mizan_mod._cache.clear()

# Leaf mizan satırları — dengeli: toplam borç = toplam alacak = 650
FAKE_MIZAN = [
    {"code": "320.01.01.0001", "borc": 100, "alacak": 300},
    {"code": "320.01.02.0002", "borc": 50, "alacak": 0},
    {"code": "102.01.0001", "borc": 500, "alacak": 200},
    {"code": "600.01", "borc": 0, "alacak": 150},
]
FAKE_NAMES = {
    "320": "SATICILAR", "320.01": "İŞLETME SATICILAR", "320.01.01.0001": "ABC LTD",
    "102": "BANKALAR", "102.01.0001": "İŞ BANKASI", "600": "YURTİÇİ SATIŞLAR", "600.01": "ODA",
}


def _summary(client, headers, qs="start_date=2026-01-01&end_date=2026-12-31&level=1"):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_mizan", return_value=FAKE_MIZAN), \
         patch(f"{TARGET}.fetch_account_names", return_value=FAKE_NAMES):
        return client.get(f"{PREFIX}/summary?{qs}", headers=headers)


def test_status(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        assert client.get(f"{PREFIX}/status", headers=auth_headers).json()["configured"] is True


def test_requires_view(client, no_perm_user_headers):
    r = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-12-31", headers=no_perm_user_headers)
    assert r.status_code == 403


def test_summary_level1_aggregates(client, auth_headers):
    """Leaf satırları kademe-1 (ana hesap) bazında toplanır + denge tutar."""
    j = _summary(client, auth_headers).json()
    assert j["balanced"] is True
    assert j["grand_total_borc"] == 650.0 and j["grand_total_alacak"] == 650.0
    assert j["account_count"] == 3  # 320, 102, 600
    by = {r["code"]: r for r in j["rows"]}
    # 320: borç 150 alacak 300 → alacak bakiye 150
    assert by["320"]["borc"] == 150.0 and by["320"]["alacak"] == 300.0
    assert by["320"]["alacak_bakiye"] == 150.0 and by["320"]["borc_bakiye"] == 0.0
    assert by["320"]["name"] == "SATICILAR" and by["320"]["has_children"] is True
    # 102: borç 500 alacak 200 → borç bakiye 300
    assert by["102"]["borc_bakiye"] == 300.0 and by["102"]["alacak_bakiye"] == 0.0
    # 600.01 tek segment fazlası → 600 has_children
    assert by["600"]["has_children"] is True


def test_summary_parent_drill(client, auth_headers):
    """parent=320 → 320'nin doğrudan alt hesapları (kademe 2)."""
    j = _summary(client, auth_headers, "start_date=2026-01-01&end_date=2026-12-31&parent=320").json()
    assert j["level"] == 2
    assert j["account_count"] == 1  # 320.01 (iki leaf'i toplar)
    row = j["rows"][0]
    assert row["code"] == "320.01" and row["borc"] == 150.0 and row["alacak"] == 300.0
    assert row["name"] == "İŞLETME SATICILAR" and row["has_children"] is True


def test_summary_unbalanced_flag(client, auth_headers):
    """Borç ≠ alacak → balanced=False (denge uyarısı)."""
    bad = [{"code": "320.01.0001", "borc": 100, "alacak": 50}]
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_mizan", return_value=bad), \
         patch(f"{TARGET}.fetch_account_names", return_value=FAKE_NAMES):
        j = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-12-31", headers=auth_headers).json()
    assert j["balanced"] is False and j["grand_total_borc"] == 100.0 and j["grand_total_alacak"] == 50.0


def test_summary_search(client, auth_headers):
    """search → kod/ad araması (kademe-1'de SATIŞLAR adına göre 600)."""
    j = _summary(client, auth_headers, "start_date=2026-01-01&end_date=2026-12-31&level=1&search=satış").json()
    assert j["account_count"] == 1 and j["rows"][0]["code"] == "600"
    # denge TÜM mizan üzerinden hesaplanır (filtreden bağımsız)
    assert j["grand_total_borc"] == 650.0


def test_not_configured_503(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=False):
        r = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-12-31", headers=auth_headers)
        assert r.status_code == 503


def test_invalid_date_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=BAD&end_date=2026-12-31", headers=auth_headers)
        assert r.status_code == 422


def test_bad_code_422(client, auth_headers):
    """Geçersiz hesap kodu (SQL gömme koruması) → 422."""
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_mizan", return_value=FAKE_MIZAN), \
         patch(f"{TARGET}.fetch_account_names", return_value=FAKE_NAMES):
        r = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-12-31&parent=320';DROP", headers=auth_headers)
        assert r.status_code == 422


def test_range_too_large_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=2020-01-01&end_date=2026-12-31", headers=auth_headers)
        assert r.status_code == 422


# ─── Drill-down: hesap hareketleri (defter) ───────────────

FAKE_TX = [
    {"fiche_date": date(2026, 1, 5), "voucher": "100", "code": "320.01.01.0001", "remark": "açılış", "debit": 0, "credit": 300},
    {"fiche_date": date(2026, 2, 5), "voucher": "200", "code": "320.01.01.0001", "remark": "ödeme", "debit": 100, "credit": 0},
]


def test_transactions(client, auth_headers):
    """Hesap hareketleri + yürüyen bakiye."""
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_account_transactions", return_value=FAKE_TX), \
         patch(f"{TARGET}.fetch_account_names", return_value=FAKE_NAMES):
        j = client.get(f"{PREFIX}/transactions?code=320.01.01.0001&start_date=2026-01-01&end_date=2026-12-31",
                       headers=auth_headers).json()
    assert j["count"] == 2 and j["total_debit"] == 100.0 and j["total_credit"] == 300.0
    assert j["balance"] == -200.0  # 0-300, sonra +100
    assert j["transactions"][0]["balance"] == -300.0 and j["transactions"][1]["balance"] == -200.0
    assert j["account_name"] == "ABC LTD"


def test_transactions_requires_view(client, no_perm_user_headers):
    r = client.get(f"{PREFIX}/transactions?code=320&start_date=2026-01-01&end_date=2026-12-31",
                   headers=no_perm_user_headers)
    assert r.status_code == 403


def test_transactions_bad_code_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/transactions?code=BAD CODE!&start_date=2026-01-01&end_date=2026-12-31",
                       headers=auth_headers)
        assert r.status_code == 422
