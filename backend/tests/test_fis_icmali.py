"""Kullanıcı Fiş İcmali — Sedna fiş icmali endpoint (fetch_voucher_summary mock'lanır)."""
from unittest.mock import patch

PREFIX = "/api/accounting/fis-icmali"
TARGET = "app.routers.accounting.fis_icmali"

FAKE_ROWS = [
    {"user_code": "SERCAN", "user_name": "SERCAN BALCI", "period": "2026-01", "cnt": 100},
    {"user_code": "SERCAN", "user_name": "SERCAN BALCI", "period": "2026-02", "cnt": 150},
    {"user_code": "MERYEM", "user_name": "MERYEM CENGİZ", "period": "2026-01", "cnt": 80},
    {"user_code": "MERYEM", "user_name": "MERYEM CENGİZ", "period": "2026-02", "cnt": 200},
]


def _get(client, headers, qs="start_date=2026-01-01&end_date=2026-12-31"):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_voucher_summary", return_value=FAKE_ROWS):
        return client.get(f"{PREFIX}/summary?{qs}", headers=headers)


def test_requires_view(client, no_perm_user_headers):
    r = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-12-31", headers=no_perm_user_headers)
    assert r.status_code == 403


def test_status(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        assert client.get(f"{PREFIX}/status", headers=auth_headers).json()["configured"] is True


def test_pivot_build(client, auth_headers):
    """Satırlardan kullanıcı×dönem pivot + satır/sütun toplamı + en aktif sıralaması."""
    j = _get(client, auth_headers).json()
    assert j["grand_total"] == 530 and j["user_count"] == 2
    assert j["periods"] == ["2026-01", "2026-02"]
    # MERYEM toplam 280 > SERCAN 250 → en üstte (azalan)
    assert j["users"][0]["user_name"] == "MERYEM CENGİZ" and j["users"][0]["total"] == 280
    assert j["users"][0]["by_period"] == {"2026-01": 80, "2026-02": 200}
    assert j["period_totals"] == {"2026-01": 180, "2026-02": 350}
    assert j["granularity"] == "month" and j["date_field"] == "record"


def test_not_configured_503(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=False):
        r = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-12-31", headers=auth_headers)
        assert r.status_code == 503


def test_invalid_date_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=BAD&end_date=2026-12-31", headers=auth_headers)
        assert r.status_code == 422


def test_range_too_large_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=2024-01-01&end_date=2026-12-31", headers=auth_headers)
        assert r.status_code == 422


def test_end_before_start_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=2026-12-31&end_date=2026-01-01", headers=auth_headers)
        assert r.status_code == 422


def test_bad_granularity_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-12-31&granularity=week", headers=auth_headers)
        assert r.status_code == 422
