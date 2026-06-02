"""Döviz kurları modülü testleri (exchange_rates).

Endpoint'ler:
- GET /api/finance/exchange-rates/latest — En son kurlar + EUR/USD parite
- GET /api/finance/exchange-rates/history — Tarihçe (paginated)
- GET /api/finance/exchange-rates/chart — Grafik için veri
- GET /api/finance/exchange-rates/parity/history — Parite tarihçesi

TCMB HTTP çağrısı yapan kod yoktur — bu router sadece DB'den okur.
Test verisi `ExchangeRate` modeli ile manuel insert edilir.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.exchange_rate import ExchangeRate


PREFIX = "/api/finance/exchange-rates"


@pytest.fixture(autouse=True)
def _wipe_rates(db):
    """Her test başında exchange_rates tablosunu temizle."""
    db.query(ExchangeRate).delete()
    db.flush()
    yield


def _seed_rate(db, **overrides):
    defaults = dict(
        date=date(2026, 4, 15),
        currency_code="EUR",
        currency_name="EURO",
        unit=1,
        forex_buying=Decimal("36.50"),
        forex_selling=Decimal("36.80"),
        banknote_buying=Decimal("36.40"),
        banknote_selling=Decimal("36.90"),
        source="tcmb",
    )
    defaults.update(overrides)
    rate = ExchangeRate(**defaults)
    db.add(rate)
    db.flush()
    return rate


# ─── Yetki ──────────────────────────────────────────────


def test_latest_requires_auth(client):
    res = client.get(f"{PREFIX}/latest")
    assert res.status_code in (401, 403)


def test_history_requires_auth(client):
    res = client.get(f"{PREFIX}/history?currency_code=EUR")
    assert res.status_code in (401, 403)


def test_chart_requires_auth(client):
    res = client.get(f"{PREFIX}/chart?currency_code=EUR")
    assert res.status_code in (401, 403)


def test_parity_requires_auth(client):
    res = client.get(f"{PREFIX}/parity/history")
    assert res.status_code in (401, 403)


# ─── /latest ─────────────────────────────────────────────


def test_latest_empty(client, auth_headers):
    """Hiç kayıt yokken date=None, rates=[]."""
    res = client.get(f"{PREFIX}/latest", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["date"] is None
    assert data["rates"] == []
    assert data["eur_usd_parity"] is None


def test_latest_returns_most_recent_date(client, auth_headers, db):
    """En yeni tarihteki tüm para birimleri döner."""
    # Eski tarih
    _seed_rate(db, date=date(2026, 4, 10), currency_code="EUR")
    # Yeni tarih
    _seed_rate(db, date=date(2026, 4, 15), currency_code="EUR", forex_selling=Decimal("36.80"))
    _seed_rate(db, date=date(2026, 4, 15), currency_code="USD", forex_selling=Decimal("34.20"))

    res = client.get(f"{PREFIX}/latest", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["date"] == "2026-04-15"
    assert len(data["rates"]) == 2
    codes = {r["currency_code"] for r in data["rates"]}
    assert codes == {"EUR", "USD"}


def test_latest_calculates_eur_usd_parity(client, auth_headers, db):
    """EUR/USD paritesi hesaplanır = eur_selling / usd_selling."""
    _seed_rate(db, date=date(2026, 4, 15), currency_code="EUR", forex_selling=Decimal("36.80"))
    _seed_rate(db, date=date(2026, 4, 15), currency_code="USD", forex_selling=Decimal("34.20"))

    res = client.get(f"{PREFIX}/latest", headers=auth_headers)
    assert res.status_code == 200
    parity = res.json()["eur_usd_parity"]
    # 36.80 / 34.20 = 1.076...
    assert parity is not None
    assert parity == pytest.approx(1.076, abs=0.005)


def test_latest_response_field_shape(client, auth_headers, db):
    """Her rate kaydı doğru alanları içermeli."""
    _seed_rate(db, currency_code="GBP", forex_buying=Decimal("43.10"), forex_selling=Decimal("43.50"))

    res = client.get(f"{PREFIX}/latest", headers=auth_headers)
    assert res.status_code == 200
    rate = res.json()["rates"][0]
    for key in ("id", "date", "currency_code", "currency_name", "unit",
                "forex_buying", "forex_selling", "source"):
        assert key in rate, f"rate response'ta '{key}' yok"
    # Float dönüşümü
    assert isinstance(rate["forex_buying"], float)
    assert rate["forex_buying"] == 43.10


# ─── /history ───────────────────────────────────────────


def test_history_requires_currency_code(client, auth_headers):
    """currency_code zorunlu — yoksa 422."""
    res = client.get(f"{PREFIX}/history", headers=auth_headers)
    assert res.status_code == 422


def test_history_validates_currency_pattern(client, auth_headers):
    """Sadece USD/EUR/GBP geçerli (pattern)."""
    res = client.get(f"{PREFIX}/history?currency_code=JPY", headers=auth_headers)
    assert res.status_code == 422


def test_history_returns_paginated(client, auth_headers, db):
    """Sadece istenen para biriminin tarihçesi döner."""
    base = date(2026, 4, 1)
    for i in range(5):
        _seed_rate(db, date=base + timedelta(days=i), currency_code="EUR",
                   forex_selling=Decimal("36.00") + Decimal(i))
    # Karışacak USD kaydı
    _seed_rate(db, date=base, currency_code="USD")

    res = client.get(f"{PREFIX}/history?currency_code=EUR", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert all(item["currency_code"] == "EUR" for item in data["items"])
    # En yeniden eskiye sıralı
    dates = [item["date"] for item in data["items"]]
    assert dates == sorted(dates, reverse=True)


def test_history_filters_by_date_range(client, auth_headers, db):
    """start_date ve end_date filtreleri çalışır."""
    for i in range(10):
        _seed_rate(db, date=date(2026, 4, 1) + timedelta(days=i), currency_code="USD")

    res = client.get(
        f"{PREFIX}/history?currency_code=USD&start_date=2026-04-03&end_date=2026-04-07",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    # 04-03, 04-04, 04-05, 04-06, 04-07 → 5 kayıt
    assert data["total"] == 5


def test_history_pagination(client, auth_headers, db):
    """page + page_size doğru çalışır."""
    base = date(2026, 4, 1)
    for i in range(30):
        _seed_rate(db, date=base + timedelta(days=i), currency_code="GBP")

    res = client.get(
        f"{PREFIX}/history?currency_code=GBP&page=1&page_size=10",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 30
    assert data["page_size"] == 10
    assert data["pages"] == 3
    assert len(data["items"]) == 10


# ─── /chart ─────────────────────────────────────────────


def test_chart_returns_recent_window(client, auth_headers, db):
    """Sadece son N gün için alış/satış döner."""
    today = date.today()
    for i in range(5):
        _seed_rate(db, date=today - timedelta(days=i), currency_code="EUR",
                   forex_selling=Decimal("36.00") + Decimal(i))

    res = client.get(f"{PREFIX}/chart?currency_code=EUR&days=10", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    # 5 günde 5 kayıt
    assert len(data) == 5
    # Tarihe göre ascending sıralı (grafik için)
    dates = [d["date"] for d in data]
    assert dates == sorted(dates)


def test_chart_excludes_older_than_window(client, auth_headers, db):
    """`days` parametresi dışındaki kayıtlar dahil edilmez."""
    today = date.today()
    # 100 gün eski — dahil değil
    _seed_rate(db, date=today - timedelta(days=100), currency_code="USD")
    # 5 gün eski — dahil
    _seed_rate(db, date=today - timedelta(days=5), currency_code="USD")

    res = client.get(f"{PREFIX}/chart?currency_code=USD&days=30", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1


def test_chart_days_validation(client, auth_headers):
    """days < 7 ise 422."""
    res = client.get(f"{PREFIX}/chart?currency_code=EUR&days=5", headers=auth_headers)
    assert res.status_code == 422


# ─── /parity/history ────────────────────────────────────


def test_parity_history_calculates_per_date(client, auth_headers, db):
    """Her tarih için EUR/USD paritesi hesaplanır."""
    today = date.today()
    _seed_rate(db, date=today - timedelta(days=2), currency_code="EUR",
               forex_selling=Decimal("36.00"))
    _seed_rate(db, date=today - timedelta(days=2), currency_code="USD",
               forex_selling=Decimal("32.00"))
    _seed_rate(db, date=today - timedelta(days=1), currency_code="EUR",
               forex_selling=Decimal("36.50"))
    _seed_rate(db, date=today - timedelta(days=1), currency_code="USD",
               forex_selling=Decimal("33.00"))

    res = client.get(f"{PREFIX}/parity/history?days=30", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    # İlk gün: 36.00 / 32.00 = 1.125
    parities = {d["date"]: d["parity"] for d in data}
    first_day = (today - timedelta(days=2)).isoformat()
    assert parities[first_day] == pytest.approx(1.125, abs=0.005)


def test_parity_history_returns_empty_when_no_data(client, auth_headers):
    """Veri yoksa [] döner."""
    res = client.get(f"{PREFIX}/parity/history?days=30", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []
