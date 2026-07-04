"""Nakit Koruma / Runway (`GET /finance/cash-flow/runway`) testleri.

FinanceEvent kayıtları doğrudan insert edilir (t_account testi deseni); EUR
çevrimi için ExchangeRate (unit=1, forex_selling) eklenir. start_eur için
BankAccount + BankTransaction + kur insert edilir. heavy_limiter conftest'te
sıfırlanmadığından dosya-içi autouse reset fixture'ı eklenir.
"""

import calendar
import itertools
from datetime import date, timedelta

import pytest

from app.middleware.rate_limit import heavy_limiter
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.utils.finance_helpers import MIN_DATE

URL = "/api/finance/cash-flow/runway"

# source_id / IBAN çakışmasın diye modül-geneli sayaç
_SEQ = itertools.count(977001)


@pytest.fixture(autouse=True)
def _reset_heavy_limiter():
    """heavy_limiter conftest'te sıfırlanmıyor — dosya içi testler 429'a düşmesin."""
    heavy_limiter._requests.clear()
    yield


def _this_month_bounds():
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today, date(today.year, today.month, 1), date(today.year, today.month, last_day)


def _mid_month_date():
    """Bu ay içinde bugün ile ay sonu arasında güvenli bir tarih (bugün+2 clamp)."""
    today, _start, end = _this_month_bounds()
    d = today + timedelta(days=2)
    return min(d, end)


def _mk_fe(db, **overrides):
    """FinanceEvent insert helper (planlı hareket varsayılanları)."""
    defaults = dict(
        event_date=_mid_month_date(),
        amount=1000,
        direction=-1,
        currency="TRY",
        source_type="check",
        source_id=next(_SEQ),
        description="RUNWAY TEST KALEMİ",
        is_matched=False,
        is_realized=False,
    )
    defaults.update(overrides)
    fe = FinanceEvent(**defaults)
    db.add(fe)
    db.flush()
    return fe


def _reset_rates(db, code="EUR"):
    db.query(ExchangeRate).filter(ExchangeRate.currency_code == code).delete()
    db.flush()


def _mk_rate(db, dt, selling, code="EUR"):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == code
    ).delete()
    rate = ExchangeRate(date=dt, currency_code=code, unit=1, forex_selling=selling)
    db.add(rate)
    db.flush()
    return rate


def _mk_account(db, currency="TRY", blocked=None):
    n = next(_SEQ)
    acc = BankAccount(
        bank_name=f"RW Test Bankası {n}",
        iban=f"TR{n:032d}"[:34],
        currency=currency,
        blocked_amount=blocked,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_tx(db, account, balance, amount=100, dt=None):
    tx = BankTransaction(
        account_id=account.id,
        date=dt or date.today(),
        description="RW BAKİYE",
        amount=amount,
        balance=balance,
        type="income" if amount >= 0 else "expense",
        tx_hash=f"rw-{next(_SEQ)}",
    )
    db.add(tx)
    db.flush()
    return tx


def _find(items, name):
    return next((i for i in items if i["name"] == name), None)


class TestRunwayAuth:
    def test_requires_auth(self, client):
        assert client.get(URL).status_code == 401

    def test_no_permission_returns_403(self, client, no_perm_user_headers):
        assert client.get(URL, headers=no_perm_user_headers).status_code == 403

    def test_viewer_can_access(self, client, viewer_user_headers):
        """Salt-görüntüleme (can_view) yeter — GET/read-only, onaydan muaf."""
        resp = client.get(URL, headers=viewer_user_headers)
        assert resp.status_code == 200
        body = resp.json()
        for key in ("month_label", "month_start", "month_end", "today",
                    "start_eur", "inflows", "outs", "skipped_no_rate"):
            assert key in body

    def test_month_bounds_and_label(self, client, auth_headers):
        today, start, end = _this_month_bounds()
        body = client.get(URL, headers=auth_headers).json()
        assert body["today"] == today.isoformat()
        assert body["month_start"] == start.isoformat()
        assert body["month_end"] == end.isoformat()
        tr_months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                     "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        assert body["month_label"] == f"{tr_months[today.month - 1]} {today.year}"


class TestRunwayStartEur:
    def test_start_eur_bank_balance_with_blocked(self, client, auth_headers, db):
        """TRY hesap son bakiyesi (blocked düşülmüş) 53 kurla EUR'a çevrilir."""
        _reset_rates(db, "EUR")
        _reset_rates(db, "USD")
        _mk_rate(db, date.today(), 53, "EUR")

        # baseline (mevcut prod-benzeri veri olmasın diye önce oku)
        before = client.get(URL, headers=auth_headers).json()["start_eur"]

        acc = _mk_account(db, currency="TRY", blocked=530)  # 530 TL bloke
        # son işlem bakiyesi 5.830 TL → effective 5.300 → /53 = 100 EUR
        _mk_tx(db, acc, balance=1000, amount=1000)
        _mk_tx(db, acc, balance=5830, amount=4830)
        db.commit()
        heavy_limiter._requests.clear()

        after = client.get(URL, headers=auth_headers).json()["start_eur"]
        assert round(after - before, 2) == 100.0

    def test_start_eur_eur_account_added_verbatim(self, client, auth_headers, db):
        """EUR hesap bakiyesi kur bölmesi olmadan aynen eklenir."""
        _reset_rates(db, "EUR")
        _mk_rate(db, date.today(), 53, "EUR")
        before = client.get(URL, headers=auth_headers).json()["start_eur"]

        acc = _mk_account(db, currency="EUR")
        _mk_tx(db, acc, balance=250, amount=250)
        db.commit()
        heavy_limiter._requests.clear()

        after = client.get(URL, headers=auth_headers).json()["start_eur"]
        assert round(after - before, 2) == 250.0


class TestRunwayEvents:
    def test_direction_split_and_id_format(self, client, auth_headers, db):
        """direction=1 → inflows, -1 → outs; id = source_type:source_id; out'ta source_type."""
        _reset_rates(db, "EUR")
        _mk_rate(db, MIN_DATE, 50)

        inflow = _mk_fe(db, direction=1, amount=1900000, source_type="bank",
                        currency="TRY", description="Acente tahsilatı")
        out = _mk_fe(db, direction=-1, amount=975000, source_type="credit",
                     currency="TRY", description="Kredi Taksiti")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(URL, headers=auth_headers).json()
        inf = _find(body["inflows"], "Acente tahsilatı")
        assert inf is not None
        assert inf["id"] == f"bank:{inflow.source_id}"
        assert inf["amount_eur"] == 38000.0  # 1.900.000 / 50
        assert "source_type" not in inf  # inflow'da source_type YOK

        o = _find(body["outs"], "Kredi Taksiti")
        assert o is not None
        assert o["id"] == f"credit:{out.source_id}"
        assert o["amount_eur"] == 19500.0  # 975.000 / 50
        assert o["source_type"] == "credit"

    def test_dates_sorted_ascending(self, client, auth_headers, db):
        _reset_rates(db, "EUR")
        _mk_rate(db, MIN_DATE, 50)
        today, start, end = _this_month_bounds()
        # iki farklı ay-içi tarih (bugün ve bugün+3, ay sonuna clamp)
        d_late = min(today + timedelta(days=3), end)
        _mk_fe(db, event_date=d_late, direction=-1, description="RW GEÇ", amount=500)
        _mk_fe(db, event_date=today, direction=-1, description="RW ERKEN", amount=500)
        db.commit()
        heavy_limiter._requests.clear()

        outs = client.get(URL, headers=auth_headers).json()["outs"]
        dates = [o["date"] for o in outs]
        assert dates == sorted(dates)

    def test_realized_and_matched_and_past_excluded(self, client, auth_headers, db):
        """is_realized=True / is_matched=True / geçmiş-ay kalemleri HARİÇ."""
        _reset_rates(db, "EUR")
        _mk_rate(db, MIN_DATE, 50)
        today, start, end = _this_month_bounds()

        _mk_fe(db, direction=-1, amount=500, description="RW REALIZED", is_realized=True)
        _mk_fe(db, direction=-1, amount=500, description="RW MATCHED", is_matched=True)
        # geçmiş ay (varsa) — MIN_DATE altına düşmeyen bir önceki gün
        past = start - timedelta(days=1)
        if past >= MIN_DATE:
            _mk_fe(db, event_date=past, direction=-1, amount=500, description="RW PAST")
        # sonraki ay başı → ay sonu üstü
        nxt = end + timedelta(days=1)
        _mk_fe(db, event_date=nxt, direction=-1, amount=500, description="RW NEXTMONTH")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(URL, headers=auth_headers).json()
        names = [i["name"] for i in body["inflows"] + body["outs"]]
        assert "RW REALIZED" not in names
        assert "RW MATCHED" not in names
        assert "RW PAST" not in names
        assert "RW NEXTMONTH" not in names

    def test_transfer_categories_excluded(self, client, auth_headers, db):
        """Virman / Döviz Satım / İade kalemleri runway'de hiç yer almaz."""
        _reset_rates(db, "EUR")
        _mk_rate(db, MIN_DATE, 50)
        for cat in ("Virman", "Döviz Satım", "İade"):
            _mk_fe(db, direction=1, amount=9999, source_type="bank",
                   category_name=cat, description=f"RW TRANSFER {cat}")
        # NULL kategori korunur (NOT IN NULL tuzağı yok)
        _mk_fe(db, direction=1, amount=1000, source_type="bank",
               category_name=None, description="RW NULLCAT")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(URL, headers=auth_headers).json()
        names = [i["name"] for i in body["inflows"] + body["outs"]]
        assert not any(n.startswith("RW TRANSFER") for n in names)
        assert "RW NULLCAT" in names  # NULL kategorili kalem korundu

    def test_eur_conversion_and_name_priority(self, client, auth_headers, db):
        """EUR kalem aynen; TRY /kur; amount_try öncelikli; ad önceliği desc→bank→check_no→etiket."""
        _reset_rates(db, "EUR")
        d = _mid_month_date()
        _mk_rate(db, d - timedelta(days=1), 53)  # <= event_date en yakın

        _mk_fe(db, event_date=d, direction=1, amount=75, currency="EUR",
               source_type="bank", description="RW EUR KALEM")
        _mk_fe(db, event_date=d, direction=-1, amount=5300, currency="TRY",
               source_type="check", description="RW TRY KALEM")
        # döviz kalem: amount_try (106) / 53 = 2 EUR
        _mk_fe(db, event_date=d, direction=-1, amount=10, currency="USD", amount_try=106,
               source_type="credit", description="RW USD KALEM")
        # ad önceliği: description boş → bank_name fallback
        _mk_fe(db, event_date=d, direction=1, amount=53, currency="TRY",
               source_type="bank", description=None, bank_name="RW Banka Adı")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(URL, headers=auth_headers).json()
        assert _find(body["inflows"], "RW EUR KALEM")["amount_eur"] == 75.0
        assert _find(body["outs"], "RW TRY KALEM")["amount_eur"] == 100.0
        assert _find(body["outs"], "RW USD KALEM")["amount_eur"] == 2.0
        assert _find(body["inflows"], "RW Banka Adı") is not None  # bank_name fallback

    def test_missing_rate_skips_item_and_counts(self, client, auth_headers, db):
        """Kur hiç yoksa TRY kalem 1'e bölünmez — dışarıda kalır, skipped_no_rate artar."""
        _reset_rates(db, "EUR")  # hiç EUR kuru yok
        _mk_fe(db, direction=-1, amount=7000, currency="TRY",
               source_type="check", description="RW KURSUZ KALEM")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(URL, headers=auth_headers).json()
        assert body["skipped_no_rate"] >= 1
        names = [i["name"] for i in body["inflows"] + body["outs"]]
        assert "RW KURSUZ KALEM" not in names
