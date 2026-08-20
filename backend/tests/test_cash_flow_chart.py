"""Nakit Akım grafiği (`GET /finance/cash-flow/chart`) testleri.

En kritik testi `TestChartSingleNumberRule`: grafiğin her kovası, AYNI (period, offset)
için T-Hesap cetveliyle (`/cash-flow/t-account`) birebir aynı toplamı vermeli. İki görünüm
ayrışırsa kullanıcı hangi sayıya güveneceğini bilemez (FIN-001 sınıfı sessiz drift).

İkinci kritik testi `TestChartOverdue`: vadesi geçmiş ödenmemiş kalemler grafikte AYRI
seri olarak GÖRÜNÜR ama toplama/net'e GİRMEZ — "ödenmedi, para hâlâ bankada" kuralı.
"""

import itertools
from datetime import date, timedelta

import pytest

from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.routers.finance.cash_flow.chart import MAX_BUCKETS, chart_limiter
from app.routers.finance.cash_flow.t_account import taccount_limiter
from app.utils.finance_helpers import MIN_DATE

URL = "/api/finance/cash-flow/chart"
TA_URL = "/api/finance/cash-flow/t-account"

# source_id çakışmasın diye (uq_finance_events_source) modül-geneli sayaç
_SEQ = itertools.count(994001)


@pytest.fixture(autouse=True)
def _reset_limiters():
    """chart/taccount limiter'ları conftest'te sıfırlanmıyor — dosya içi testler 429'a düşmesin."""
    chart_limiter._requests.clear()
    taccount_limiter._requests.clear()
    yield


def _mk_fe(db, **overrides):
    """FinanceEvent insert helper (test_cash_flow_taccount._mk_fe deseni)."""
    defaults = dict(
        event_date=date.today(),
        amount=1000,
        direction=-1,
        currency="TRY",
        source_type="bank",
        source_id=next(_SEQ),
        description="GRAFİK TEST KALEMİ",
        is_matched=False,
        is_realized=True,
    )
    defaults.update(overrides)
    fe = FinanceEvent(**defaults)
    db.add(fe)
    db.flush()
    return fe


def _mk_rate(db, dt, value, code="EUR"):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == code
    ).delete()
    rate = ExchangeRate(date=dt, currency_code=code, unit=1,
                        forex_selling=value, forex_buying=value)
    db.add(rate)
    db.flush()
    return rate


def _reset_eur_rates(db):
    db.query(ExchangeRate).filter(ExchangeRate.currency_code == "EUR").delete()
    db.flush()


def _bucket(body, offset):
    return next((b for b in body["buckets"] if b["offset"] == offset), None)


class TestChartAuth:
    def test_requires_auth(self, client):
        assert client.get(URL).status_code == 401

    def test_no_permission_returns_403(self, client, no_perm_user_headers):
        assert client.get(URL, headers=no_perm_user_headers).status_code == 403

    def test_viewer_can_access(self, client, viewer_user_headers):
        """Salt-görüntüleme yetkisi yeter — GET/read-only, onaydan muaf."""
        resp = client.get(URL, headers=viewer_user_headers)
        assert resp.status_code == 200
        body = resp.json()
        for key in ("period", "offset", "back", "forward", "today", "start_date",
                    "end_date", "buckets", "accounts", "total_balance_eur",
                    "overdue_expense_eur", "overdue_income_eur", "skipped_no_rate"):
            assert key in body


class TestChartParams:
    def test_invalid_period_rejected(self, client, auth_headers):
        assert client.get(URL + "?period=hourly", headers=auth_headers).status_code == 422

    def test_offset_bounds(self, client, auth_headers):
        assert client.get(URL + "?offset=24", headers=auth_headers).status_code == 200
        assert client.get(URL + "?offset=25", headers=auth_headers).status_code == 422
        assert client.get(URL + "?offset=-121", headers=auth_headers).status_code == 422

    def test_window_size_follows_back_forward(self, client, auth_headers):
        resp = client.get(URL + "?period=monthly&back=3&forward=2", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["buckets"]) == 6  # 3 geçmiş + bugün + 2 gelecek
        assert [b["offset"] for b in body["buckets"]] == [-3, -2, -1, 0, 1, 2]
        assert sum(1 for b in body["buckets"] if b["is_current"]) == 1

    def test_bucket_count_capped(self, client, auth_headers):
        """back+forward tavanı aşarsa GELECEK kırpılır (geçmiş gerçekleşen veriyi taşır)."""
        resp = client.get(
            URL + "?period=daily&back={}&forward={}".format(MAX_BUCKETS - 1, MAX_BUCKETS - 1),
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["buckets"]) == MAX_BUCKETS
        assert body["back"] == MAX_BUCKETS - 1
        assert body["forward"] == 0

    def test_buckets_are_contiguous_and_ordered(self, client, auth_headers):
        """Kovalar bitişik: her kovanın başlangıcı bir öncekinin bitişinin ertesi günü."""
        for period in ("daily", "weekly", "monthly", "yearly"):
            body = client.get(URL + "?period=" + period, headers=auth_headers).json()
            buckets = body["buckets"]
            assert buckets[0]["start_date"] == body["start_date"]
            assert buckets[-1]["end_date"] == body["end_date"]
            for prev, cur in zip(buckets, buckets[1:]):
                prev_end = date.fromisoformat(prev["end_date"])
                cur_start = date.fromisoformat(cur["start_date"])
                assert cur_start == prev_end + timedelta(days=1), period


class TestChartSingleNumberRule:
    """Grafik ↔ T-Hesap birebir aynı sayıyı vermeli (iki görünüm asla ayrışmaz)."""

    @pytest.mark.parametrize("period", ["daily", "weekly", "monthly", "yearly"])
    def test_bucket_totals_match_t_account(self, client, auth_headers, db, period):
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        today = date.today()
        # Gerçekleşen gider + gerçekleşen gelir (bugün) → iki görünümde de akışta
        _mk_fe(db, direction=-1, amount=3000, category_name="GRAFİK-TEST GİDER")
        _mk_fe(db, direction=1, amount=5000, category_name="GRAFİK-TEST GELİR")
        # Gelecek vadeli planlı gider → iki görünümde de bekleyen
        _mk_fe(db, direction=-1, amount=2000, is_realized=False,
               event_date=today + timedelta(days=1), source_type="tax",
               category_name=None, description="GRAFİK-TEST PLANLI")
        db.commit()

        body = client.get(URL + "?period=" + period + "&back=1&forward=1",
                          headers=auth_headers).json()
        for bucket in body["buckets"]:
            taccount_limiter._requests.clear()
            ta = client.get(
                "{}?period={}&offset={}".format(TA_URL, period, bucket["offset"]),
                headers=auth_headers,
            ).json()
            ctx = "{} offset={}".format(period, bucket["offset"])
            assert bucket["income_total"] == pytest.approx(ta["total_in_eur"], abs=0.02), ctx
            assert bucket["expense_total"] == pytest.approx(ta["total_out_eur"], abs=0.02), ctx
            assert bucket["income_realized"] == pytest.approx(ta["realized_in_eur"], abs=0.02), ctx
            assert bucket["expense_realized"] == pytest.approx(ta["realized_out_eur"], abs=0.02), ctx
            assert bucket["net_eur"] == pytest.approx(ta["net_eur"], abs=0.02), ctx


class TestChartSplit:
    def test_realized_and_planned_split(self, client, auth_headers, db):
        """Gerçekleşen bugünkü kalem realized'a, gelecek vadeli ödenmemiş planned'a düşer."""
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        today = date.today()
        _mk_fe(db, direction=-1, amount=1000, is_realized=True)                      # 20 €
        _mk_fe(db, direction=-1, amount=4000, is_realized=False, source_type="tax",  # 80 €
               event_date=today + timedelta(days=1))
        db.commit()

        body = client.get(URL + "?period=daily&back=0&forward=1", headers=auth_headers).json()
        bugun = _bucket(body, 0)
        yarin = _bucket(body, 1)
        assert bugun["expense_realized"] >= 20.0
        assert yarin["expense_planned"] >= 80.0
        # Net her iki kovada da realized+planned üzerinden
        assert bugun["net_eur"] == pytest.approx(
            bugun["income_total"] - bugun["expense_total"], abs=0.02)


class TestChartOverdue:
    def test_overdue_visible_but_out_of_total(self, client, auth_headers, db):
        """Vadesi geçmiş ödenmemiş kalem AYRI seride görünür, toplama/net'e GİRMEZ.

        Kural: "ödenmedi, para hâlâ bankada" (eur_balances 2026-07-06 notu) — T-Hesap
        onu listeden düşer, grafik ise kendi tarihinde ayrı seri olarak gösterir.
        """
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        gecmis = date.today() - timedelta(days=2)
        if gecmis < MIN_DATE:
            pytest.skip("MIN_DATE penceresinden önce — geçmiş vade kurulamıyor")

        base = client.get(URL + "?period=daily&back=3&forward=0", headers=auth_headers).json()
        offset = next(b["offset"] for b in base["buckets"] if b["start_date"] == gecmis.isoformat())
        before = _bucket(base, offset)

        _mk_fe(db, direction=-1, amount=6000, is_realized=False, source_type="tax",
               event_date=gecmis, description="GRAFİK-TEST VADESİ GEÇEN")
        db.commit()

        chart_limiter._requests.clear()
        after = _bucket(
            client.get(URL + "?period=daily&back=3&forward=0", headers=auth_headers).json(),
            offset,
        )
        assert after["expense_overdue"] == pytest.approx(before["expense_overdue"] + 120.0, abs=0.02)
        assert after["overdue_count"] == before["overdue_count"] + 1
        # Toplam ve net DEĞİŞMEDİ — vadesi geçen akışa girmez
        assert after["expense_total"] == pytest.approx(before["expense_total"], abs=0.02)
        assert after["net_eur"] == pytest.approx(before["net_eur"], abs=0.02)


class TestChartAccounts:
    def test_accounts_total_matches_runway_start_eur(self, client, auth_headers, db):
        """Hesap şeridi toplamı = runway "Bankadaki Nakit" (`_compute_start_eur`) — tek kaynak."""
        from app.routers.finance.cash_flow.runway import _compute_start_eur

        body = client.get(URL, headers=auth_headers).json()
        assert body["total_balance_eur"] == pytest.approx(_compute_start_eur(db), abs=0.02)
        summed = sum(a["balance_eur"] for a in body["accounts"] if a["balance_eur"] is not None)
        assert summed == pytest.approx(body["total_balance_eur"], abs=0.02)

    def test_account_rows_have_display_fields(self, client, auth_headers):
        body = client.get(URL, headers=auth_headers).json()
        for acc in body["accounts"]:
            for key in ("id", "bank_name", "currency", "last_balance", "blocked_amount",
                        "effective_balance", "balance_eur", "last_movement_date"):
                assert key in acc
            # Tam IBAN sızmaz — yalnız son 4 hane
            assert "iban" not in acc
            assert acc["iban_tail"] is None or len(acc["iban_tail"]) <= 4
