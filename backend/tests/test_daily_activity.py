"""Günlük Rezervasyon Hareketleri — Sedna canlı gelen/iptal akışı (fetch_* mock'lanır)."""
from datetime import date
from unittest.mock import patch

import pytest

PREFIX = "/api/sales/daily-activity"
TARGET = "app.routers.sales.reservations.daily_activity"

# EUR=1, TL=0.02 (1 TL = 0.02 EUR) — çevrim hesabı deterministik
FACTORS = {"EUR": 1.0, "TL": 0.02, "TRY": 0.02}


def _row(rec_id, record_date, cancel_date=None, status_code=1, *, checkin=date(2026, 7, 1),
         checkout=date(2026, 7, 8), adult=2, child_paid=1, child_free=0, baby=1,
         room_price=700.0, currency="EUR", agency="ALLTOURS", voucher="V1",
         nation="DEU", room_type="STD DNZ", board="AI"):
    """fetch_reservation_activity'nin döndürdüğü ham Sedna satırı (misafir adı çekilmez)."""
    return {
        "rec_id": rec_id, "agency": agency, "room_type": room_type, "voucher": voucher,
        "checkin_date": checkin, "checkout_date": checkout,
        "record_date": record_date, "board": board, "adult": adult,
        "child_paid": child_paid, "child_free": child_free, "baby": baby,
        "nation": nation, "room_price": room_price, "currency": currency,
        "status_code": status_code, "cancel_date": cancel_date,
    }


# 09.06: 2 gelen (#1 aktif, #2 sonradan 10.06'da iptal) · 10.06: 1 gelen (#3, TL) + #2'nin iptali
FAKE_ROWS = [
    _row(1, date(2026, 6, 9)),
    _row(2, date(2026, 6, 9), cancel_date=date(2026, 6, 10), status_code=-1,
         room_price=500.0, agency="TUI", voucher="V2"),
    _row(3, date(2026, 6, 10), room_price=10000.0, currency="TL", agency="WEBRES",
         voucher="V3", adult=1, child_paid=0, checkin=date(2026, 8, 1), checkout=date(2026, 8, 4)),
]


@pytest.fixture(autouse=True)
def _clear_cache():
    """Süreç-içi TTL cache testler arasında sızmasın."""
    from app.routers.sales.reservations import daily_activity
    daily_activity._cache.clear()
    yield
    daily_activity._cache.clear()


def _get(client, headers, path):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_reservation_activity", return_value=FAKE_ROWS), \
         patch(f"{TARGET}._currency_to_eur_factors", return_value=FACTORS):
        return client.get(f"{PREFIX}{path}", headers=headers)


def _summary(client, headers, qs="start_date=2026-06-09&end_date=2026-06-10"):
    return _get(client, headers, f"/summary?{qs}")


# ─── İzin + durum ───────────────────────────────────────

def test_summary_requires_view(client, no_perm_user_headers):
    r = client.get(f"{PREFIX}/summary?start_date=2026-06-09&end_date=2026-06-10",
                   headers=no_perm_user_headers)
    assert r.status_code == 403


def test_details_requires_view(client, no_perm_user_headers):
    r = client.get(f"{PREFIX}/details?activity_date=2026-06-09&type=new",
                   headers=no_perm_user_headers)
    assert r.status_code == 403


def test_view_only_user_can_read(client, make_user_with_perms):
    headers = make_user_with_perms({"sales.daily_reservations": {"view": True, "use": False}})
    assert _summary(client, headers).status_code == 200


def test_status(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        assert client.get(f"{PREFIX}/status", headers=auth_headers).json()["configured"] is True


# ─── Özet: gün gruplama + toplamlar ─────────────────────

def test_summary_day_grouping(client, auth_headers):
    j = _summary(client, auth_headers).json()
    assert [d["date"] for d in j["days"]] == ["2026-06-10", "2026-06-09"]  # en yeni üstte

    d10 = j["days"][0]
    d09 = j["days"][1]
    # 09.06: 2 gelen (700 + 500 EUR), iptal yok
    assert d09["new"]["count"] == 2 and d09["new"]["eur"] == 1200.0
    assert d09["cancelled"]["count"] == 0
    # her rezervasyon 7 gece × 2 kayıt = 14; pax = (2+1+0) × 2 = 6 (bebek sayılmaz)
    assert d09["new"]["nights"] == 14 and d09["new"]["pax"] == 6
    # 10.06: 1 gelen (TL → 10000×0.02 = 200 EUR, 3 gece, pax=1) + 1 iptal (#2, 500 EUR)
    assert d10["new"]["count"] == 1 and d10["new"]["eur"] == 200.0
    assert d10["new"]["nights"] == 3 and d10["new"]["pax"] == 1
    assert d10["cancelled"]["count"] == 1 and d10["cancelled"]["eur"] == 500.0
    assert d10["net_count"] == 0 and d10["net_eur"] == -300.0


def test_summary_totals(client, auth_headers):
    t = _summary(client, auth_headers).json()["totals"]
    assert t["new"]["count"] == 3 and t["new"]["eur"] == 1400.0
    assert t["cancelled"]["count"] == 1 and t["cancelled"]["eur"] == 500.0
    assert t["net_count"] == 2 and t["net_eur"] == 900.0
    assert t["cancel_rate"] == 25.0  # 1 iptal / (3 gelen + 1 iptal)


def test_summary_quiet_days_zero_filled(client, auth_headers):
    """Hareketsiz günler 0'larla döner — aralıktaki her gün listede olmalı."""
    j = _summary(client, auth_headers, "start_date=2026-06-08&end_date=2026-06-11").json()
    assert len(j["days"]) == 4
    quiet = next(d for d in j["days"] if d["date"] == "2026-06-08")
    assert quiet["new"]["count"] == 0 and quiet["cancelled"]["count"] == 0


def test_summary_same_day_new_and_cancel(client, auth_headers):
    """Aynı gün gelip iptal edilen kayıt iki sayıma da girer → gün neti 0."""
    rows = [_row(9, date(2026, 6, 9), cancel_date=date(2026, 6, 9), status_code=-1)]
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_reservation_activity", return_value=rows), \
         patch(f"{TARGET}._currency_to_eur_factors", return_value=FACTORS):
        j = client.get(f"{PREFIX}/summary?start_date=2026-06-09&end_date=2026-06-09",
                       headers=auth_headers).json()
    d = j["days"][0]
    assert d["new"]["count"] == 1 and d["cancelled"]["count"] == 1
    assert d["net_count"] == 0 and d["net_eur"] == 0.0


# ─── Drill-down detayları ───────────────────────────────

def test_details_new(client, auth_headers):
    j = _get(client, auth_headers, "/details?activity_date=2026-06-09&type=new").json()
    assert j["count"] == 2 and j["eur_total"] == 1200.0
    by_voucher = {i["voucher"]: i for i in j["items"]}
    assert by_voucher["V1"]["is_cancelled"] is False
    assert by_voucher["V2"]["is_cancelled"] is True  # sonradan iptal işareti
    assert by_voucher["V2"]["cancel_date"] == "2026-06-10"
    assert by_voucher["V1"]["nights"] == 7 and by_voucher["V1"]["pax"] == 3


def test_details_no_guest_names(client, auth_headers):
    """Misafir adı (kişisel veri) yanıtta YER ALMAZ — bilinçli tasarım kararı."""
    j = _get(client, auth_headers, "/details?activity_date=2026-06-09&type=new").json()
    assert all("guests" not in item for item in j["items"])


def test_details_cancelled(client, auth_headers):
    j = _get(client, auth_headers, "/details?activity_date=2026-06-10&type=cancelled").json()
    assert j["count"] == 1
    item = j["items"][0]
    assert item["voucher"] == "V2" and item["record_date"] == "2026-06-09"
    assert item["eur"] == 500.0


def test_details_currency_conversion(client, auth_headers):
    """TL tutar EUR'ya çevrilir; ham tutar + para birimi korunur."""
    j = _get(client, auth_headers, "/details?activity_date=2026-06-10&type=new").json()
    item = j["items"][0]
    assert item["currency"] == "TL" and item["amount"] == 10000.0 and item["eur"] == 200.0


def test_details_bad_type_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/details?activity_date=2026-06-09&type=removed",
                       headers=auth_headers)
        assert r.status_code == 422


# ─── Doğrulama + Sedna kapalı ───────────────────────────

def test_not_configured_503(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=False):
        r = client.get(f"{PREFIX}/summary?start_date=2026-06-09&end_date=2026-06-10",
                       headers=auth_headers)
        assert r.status_code == 503


def test_invalid_date_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=BAD&end_date=2026-06-10",
                       headers=auth_headers)
        assert r.status_code == 422


def test_end_before_start_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=2026-06-10&end_date=2026-06-09",
                       headers=auth_headers)
        assert r.status_code == 422


def test_range_too_large_422(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        r = client.get(f"{PREFIX}/summary?start_date=2026-01-01&end_date=2026-06-10",
                       headers=auth_headers)
        assert r.status_code == 422
