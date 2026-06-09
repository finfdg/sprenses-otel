"""Kullanıcı Fiş İcmali — Sedna fiş icmali + drill-down endpoint'leri (fetch_* mock'lanır)."""
from datetime import date
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


# ─── Drill-down: fiş listesi + fiş detayı ───────────────

FAKE_VOUCHERS = [
    {"rec_id": 6895, "voucher": "6722", "fiche_date": date(2026, 5, 26), "record_date": date(2026, 6, 1),
     "remark": "AHMET FERİT MAYIS AVANS", "total": 140000},
    {"rec_id": 6896, "voucher": "6723", "fiche_date": date(2026, 5, 26), "record_date": date(2026, 6, 1),
     "remark": "VAKIF EFT", "total": 2901.55},
]
FAKE_DETAIL = {
    "header": {"rec_id": 6895, "voucher": "6722", "fiche_date": date(2026, 5, 26),
               "record_date": date(2026, 6, 1), "remark": "AHMET FERİT MAYIS AVANS", "total": 140000,
               "record_user": "YASEMIN", "change_user": "TUĞÇE"},
    "lines": [
        {"code": "335.01.01.0018", "account_name": "AHMET FERİT ÇEVLİK", "debit": 70000, "credit": 0, "remark": "x"},
        {"code": "102.01.13.0001", "account_name": "VAKIFBANK", "debit": 0, "credit": 70000, "remark": "x"},
    ],
}


def test_vouchers_drilldown(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_user_vouchers", return_value=FAKE_VOUCHERS):
        j = client.get(f"{PREFIX}/vouchers?user_code=YASEMIN&start_date=2026-05-14&end_date=2026-06-09",
                       headers=auth_headers).json()
    assert j["count"] == 2 and j["total"] == 142901.55
    v0 = j["vouchers"][0]
    assert v0["voucher"] == "6722" and v0["rec_id"] == 6895 and v0["record_date"] == "2026-06-01"


def test_vouchers_requires_view(client, no_perm_user_headers):
    r = client.get(f"{PREFIX}/vouchers?user_code=X&start_date=2026-01-01&end_date=2026-01-31",
                   headers=no_perm_user_headers)
    assert r.status_code == 403


def test_voucher_detail(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_voucher_detail", return_value=FAKE_DETAIL):
        j = client.get(f"{PREFIX}/voucher-detail?rec_id=6895", headers=auth_headers).json()
    assert j["voucher"] == "6722" and len(j["lines"]) == 2
    assert j["total_debit"] == 70000.0 and j["total_credit"] == 70000.0
    assert j["lines"][0]["account_name"] == "AHMET FERİT ÇEVLİK"
    assert j["record_user"] == "YASEMIN"


def test_voucher_detail_404(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_voucher_detail", return_value={"header": None, "lines": []}):
        assert client.get(f"{PREFIX}/voucher-detail?rec_id=999", headers=auth_headers).status_code == 404
