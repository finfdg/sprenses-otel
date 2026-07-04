"""Nakit Akım T Hesap Cetveli (`GET /finance/cash-flow/t-account`) testleri.

FinanceEvent kayıtları doğrudan insert edilir (TestPaidChecksVisible._mk_fe deseni);
EUR çevrimi için ExchangeRate (unit=1, forex_selling) eklenir.
"""

import calendar
import itertools
from datetime import date, timedelta

import pytest

from app.routers.finance.cash_flow.t_account import taccount_limiter
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.utils.finance_helpers import MIN_DATE

URL = "/api/finance/cash-flow/t-account"

# source_id çakışmasın diye (uq_finance_events_source) modül-geneli sayaç
_SEQ = itertools.count(987001)


@pytest.fixture(autouse=True)
def _reset_heavy_limiter():
    """taccount_limiter conftest'te sıfırlanmıyor — dosya içi testler 429'a düşmesin."""
    taccount_limiter._requests.clear()
    yield


def _mk_fe(db, **overrides):
    """FinanceEvent insert helper (test_finance.py::TestPaidChecksVisible deseni)."""
    defaults = dict(
        event_date=date.today(),
        amount=1000,
        direction=-1,
        currency="TRY",
        source_type="bank",
        source_id=next(_SEQ),
        description="T-HESAP TEST KALEMİ",
        is_matched=False,
        is_realized=True,
    )
    defaults.update(overrides)
    fe = FinanceEvent(**defaults)
    db.add(fe)
    db.flush()
    return fe


def _reset_eur_rates(db):
    """Deterministik kur testi için mevcut tüm EUR kurlarını temizle (rollback'li)."""
    db.query(ExchangeRate).filter(ExchangeRate.currency_code == "EUR").delete()
    db.flush()


def _mk_rate(db, dt, selling):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == "EUR"
    ).delete()
    rate = ExchangeRate(date=dt, currency_code="EUR", unit=1, forex_selling=selling)
    db.add(rate)
    db.flush()
    return rate


def _group(body, side, label):
    """Yanıttaki giris/cikis listesinden etikete göre grup bul."""
    return next((g for g in body[side] if g["label"] == label), None)


class TestTAccountAuth:
    def test_requires_auth(self, client):
        assert client.get(URL).status_code == 401

    def test_no_permission_returns_403(self, client, no_perm_user_headers):
        assert client.get(URL, headers=no_perm_user_headers).status_code == 403

    def test_viewer_can_access(self, client, viewer_user_headers):
        """Salt-görüntüleme (can_view) yetkisi yeter — GET/read-only, onaydan muaf."""
        resp = client.get(URL, headers=viewer_user_headers)
        assert resp.status_code == 200
        body = resp.json()
        for key in ("period", "offset", "start_date", "end_date", "giris", "cikis",
                    "total_in_eur", "total_out_eur", "net_eur", "skipped_no_rate"):
            assert key in body

    def test_invalid_period_rejected(self, client, auth_headers):
        assert client.get(f"{URL}?period=hourly", headers=auth_headers).status_code == 422

    def test_positive_offset_rejected(self, client, auth_headers):
        """offset yalnız 0 veya negatif (geçmiş) olabilir."""
        assert client.get(f"{URL}?offset=1", headers=auth_headers).status_code == 422
        assert client.get(f"{URL}?offset=-121", headers=auth_headers).status_code == 422


class TestTAccountGrouping:
    def test_monthly_grouping_bank_category_and_check_label(self, client, auth_headers, db):
        """Banka kalemleri category_name ile, çek kalemleri sabit etiketle gruplanır."""
        today = date.today()
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)

        _mk_fe(db, direction=1, amount=5000, category_name="T-TEST KONAKLAMA",
               description="ACENTE HAVALESİ A")
        _mk_fe(db, direction=1, amount=2500, category_name="T-TEST KONAKLAMA",
               description="ACENTE HAVALESİ B")
        # Kategorisiz banka kalemi → Etiketsiz; description boş → bank_name fallback
        _mk_fe(db, direction=1, amount=1000, category_name=None,
               description=None, bank_name="T-Test Bankası")
        # Çek kalemi → sabit Türkçe etiket
        _mk_fe(db, source_type="check", direction=-1, amount=4000,
               check_no="0088001", description="T-TEST ÇEK FİRMASI")
        db.commit()

        resp = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        # Dönem = içinde bulunulan takvim ayı
        last_day = calendar.monthrange(today.year, today.month)[1]
        assert body["start_date"] == date(today.year, today.month, 1).isoformat()
        assert body["end_date"] == date(today.year, today.month, last_day).isoformat()

        konaklama = _group(body, "giris", "T-TEST KONAKLAMA")
        assert konaklama is not None
        assert konaklama["item_count"] == 2
        assert konaklama["total_eur"] == 150.0  # (5000+2500)/50
        # items tarih artan sıralı, amount_eur alanlı
        assert [i["name"] for i in konaklama["items"]] == ["ACENTE HAVALESİ A", "ACENTE HAVALESİ B"]
        assert konaklama["items"][0]["amount_eur"] == 100.0
        assert konaklama["items"][0]["date"] == today.isoformat()

        etiketsiz = _group(body, "giris", "Etiketsiz")
        assert etiketsiz is not None
        # description boş → bank_name fallback
        assert any(i["name"] == "T-Test Bankası" for i in etiketsiz["items"])

        cekler = _group(body, "cikis", "Verilen Çekler")
        assert cekler is not None
        assert any(i["name"] == "T-TEST ÇEK FİRMASI" and i["amount_eur"] == 80.0
                   for i in cekler["items"])

    def test_transfer_categories_fully_excluded(self, client, auth_headers, db):
        """Virman / Döviz Satım / İade kalemleri cetvelde hiç yer almaz."""
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        for cat in ("Virman", "Döviz Satım", "İade"):
            _mk_fe(db, direction=1, amount=9999, category_name=cat,
                   description=f"T-TRANSFER {cat}")
        db.commit()

        resp = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        for cat in ("Virman", "Döviz Satım", "İade"):
            assert _group(body, "giris", cat) is None
            assert _group(body, "cikis", cat) is None
        all_names = [i["name"] for g in body["giris"] + body["cikis"] for i in g["items"]]
        assert not any(n.startswith("T-TRANSFER") for n in all_names)

    def test_matched_events_excluded(self, client, auth_headers, db):
        """is_matched=True (çift sayım engeli) kalemler cetvele girmez."""
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        _mk_fe(db, source_type="check", direction=-1, amount=5000,
               description="T-EŞLEŞMİŞ ÇEK", is_matched=True, event_status="paid")
        _mk_fe(db, direction=-1, amount=5000, category_name="T-EŞLEŞME TEST",
               description="T-EŞLEŞMİŞ BANKA", is_matched=True)
        db.commit()

        resp = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        all_names = [i["name"] for g in body["giris"] + body["cikis"] for i in g["items"]]
        assert "T-EŞLEŞMİŞ ÇEK" not in all_names
        assert "T-EŞLEŞMİŞ BANKA" not in all_names


class TestTAccountEurConversion:
    def test_try_amount_divided_by_rate(self, client, auth_headers, db):
        """53 kur → 5300 TRY = 100 EUR; EUR kalem aynen; amount_try öncelikli."""
        today = date.today()
        _reset_eur_rates(db)
        _mk_rate(db, today - timedelta(days=3), 53)  # <= event_date en yakın kur

        _mk_fe(db, direction=1, amount=5300, currency="TRY",
               category_name="T-KUR GELİR", description="TRY KALEM")
        _mk_fe(db, direction=1, amount=75, currency="EUR",
               category_name="T-KUR GELİR", description="EUR KALEM")
        # Döviz kalem: amount_try (106 TL) kur 53'e bölünür → 2 EUR
        _mk_fe(db, direction=-1, amount=10, currency="USD", amount_try=106,
               category_name="T-KUR GİDER", description="USD KALEM")
        db.commit()

        resp = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        gelir = _group(body, "giris", "T-KUR GELİR")
        assert gelir is not None
        assert gelir["item_count"] == 2
        assert gelir["total_eur"] == 175.0  # 100 + 75
        by_name = {i["name"]: i["amount_eur"] for i in gelir["items"]}
        assert by_name["TRY KALEM"] == 100.0
        assert by_name["EUR KALEM"] == 75.0

        gider = _group(body, "cikis", "T-KUR GİDER")
        assert gider is not None
        assert gider["total_eur"] == 2.0

    def test_missing_rate_skips_item_and_counts(self, client, auth_headers, db):
        """Kur hiç yoksa TRY kalem 1'e bölünmez — dışarıda kalır, sayaç artar."""
        _reset_eur_rates(db)  # hiç EUR kuru yok
        _mk_fe(db, direction=-1, amount=7000, currency="TRY",
               category_name="T-KURSUZ", description="KURSUZ KALEM")
        db.commit()

        resp = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["skipped_no_rate"] >= 1
        assert _group(body, "cikis", "T-KURSUZ") is None
        all_names = [i["name"] for g in body["giris"] + body["cikis"] for i in g["items"]]
        assert "KURSUZ KALEM" not in all_names


class TestTAccountPeriods:
    def test_offset_minus_one_is_previous_calendar_month(self, client, auth_headers, db):
        """offset=-1 → önceki takvim ayı aralığı; bu ayın kalemi kapsanmaz."""
        today = date.today()
        total = today.year * 12 + (today.month - 1) - 1
        prev_year, prev_month0 = divmod(total, 12)
        prev_month = prev_month0 + 1
        prev_start = date(prev_year, prev_month, 1)
        prev_end = date(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1])

        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        _mk_fe(db, direction=-1, amount=5000, category_name="T-OFFSET TEST",
               description="BU AYIN KALEMİ")
        if prev_start >= MIN_DATE:
            _mk_fe(db, event_date=prev_start, direction=-1, amount=5000,
                   category_name="T-OFFSET TEST", description="GEÇEN AYIN KALEMİ")
        db.commit()

        resp = client.get(f"{URL}?period=monthly&offset=-1", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["offset"] == -1
        assert body["start_date"] == prev_start.isoformat()
        assert body["end_date"] == prev_end.isoformat()

        all_names = [i["name"] for g in body["giris"] + body["cikis"] for i in g["items"]]
        assert "BU AYIN KALEMİ" not in all_names
        if prev_start >= MIN_DATE:
            assert "GEÇEN AYIN KALEMİ" in all_names

    def test_weekly_range_starts_monday(self, client, auth_headers):
        """weekly dönem Pazartesi başlar, 7 gün sürer; offset hafta kaydırır."""
        resp = client.get(f"{URL}?period=weekly&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        start = date.fromisoformat(body["start_date"])
        end = date.fromisoformat(body["end_date"])
        assert start.weekday() == 0  # Pazartesi
        assert (end - start).days == 6  # Pazartesi–Pazar
        assert start <= date.today() <= end

        prev = client.get(f"{URL}?period=weekly&offset=-1", headers=auth_headers).json()
        assert date.fromisoformat(prev["start_date"]) == start - timedelta(days=7)
        assert date.fromisoformat(prev["end_date"]) == end - timedelta(days=7)

    def test_yearly_range_covers_calendar_year(self, client, auth_headers):
        resp = client.get(f"{URL}?period=yearly&offset=0", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        year = date.today().year
        assert body["start_date"] == f"{year}-01-01"
        assert body["end_date"] == f"{year}-12-31"


class TestTAccountCcProjection:
    """Yüklenmemiş cari ay kredi kartı ekstresi rezervi ÇIKIŞ 'KK Borç Ödemeleri'nde görünür."""

    @staticmethod
    def _current_month_card(db):
        import calendar
        import json

        from app.models.credit_product import CreditProduct
        today = date.today()
        last = calendar.monthrange(today.year, today.month)[1]
        # Son ödeme ay sonunda (>= bugün) → cari ay limit rezervi üretilir (deterministik)
        card = CreditProduct(
            type="kredi_karti", name="T-TEST KK", bank_name="T-Test Bank",
            total_amount=100000, remaining_amount=0, status="active",
            details=json.dumps({"ekstre_kesim_gunu": max(1, last - 1), "son_odeme_gunu": last}),
        )
        db.add(card)
        db.commit()
        return card

    def test_monthly_includes_cc_projection_reserve(self, client, auth_headers, db):
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)  # 1 EUR = 50 TRY
        self._current_month_card(db)

        body = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers).json()
        kk = _group(body, "cikis", "KK Borç Ödemeleri")
        assert kk is not None, "Tahmini KK rezervi ÇIKIŞ'ta bekleniyor"
        # 100000 TRY / 50 = 2000 EUR; kalem "(Tahmini)" etiketli
        assert any(it["amount_eur"] == 2000.0 and "(Tahmini)" in it["name"] for it in kk["items"])

    def test_past_month_excludes_cc_projection(self, client, auth_headers, db):
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        self._current_month_card(db)
        # Geçmiş ay (offset=-1): tahmini rezerv cari ay kalemidir → görünmez
        body = client.get(f"{URL}?period=monthly&offset=-1", headers=auth_headers).json()
        assert _group(body, "cikis", "KK Borç Ödemeleri") is None
