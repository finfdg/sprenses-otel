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
    rate = ExchangeRate(date=dt, currency_code="EUR", unit=1, forex_selling=selling, forex_buying=selling)
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

    def test_offset_bounds(self, client, auth_headers):
        """offset -120 (geçmiş) .. +24 (gelecek) aralığında; dışı 422."""
        assert client.get(f"{URL}?offset=24", headers=auth_headers).status_code == 200
        assert client.get(f"{URL}?offset=25", headers=auth_headers).status_code == 422
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

    def test_overdue_unpaid_expense_excluded_realized_kept(self, client, auth_headers, db):
        """Vadesi geçmiş ÖDENMEMİŞ (is_realized=False) çıkış cetvele GİRMEZ (Vadesi Geçenler'de);
        vadesi geçmiş GERÇEKLEŞMİŞ (banka) çıkış GİRER. Geçen ay = tamamen bugünden önce (deterministik)."""
        _reset_eur_rates(db)
        today = date.today()
        mid_last = (today.replace(day=1) - timedelta(days=1)).replace(day=15)  # geçen ay 15'i
        _mk_rate(db, mid_last, 40.0)
        _mk_fe(db, event_date=mid_last, direction=-1, is_realized=False,
               source_type="vendor_payment", amount=5000, description="ODENMEMIS CARI")
        _mk_fe(db, event_date=mid_last, direction=-1, is_realized=True,
               source_type="bank", amount=3000, description="BANKA GERCEKLESEN")
        db.commit()

        body = client.get(f"{URL}?period=monthly&offset=-1", headers=auth_headers).json()
        names = [i["name"] for g in body["cikis"] for i in g["items"]]
        assert "ODENMEMIS CARI" not in names     # vadesi geçmiş ödenmemiş → hariç
        assert "BANKA GERCEKLESEN" in names       # gerçekleşmiş → dahil

    def test_overdue_unrealized_income_excluded(self, client, auth_headers, db):
        """Vadesi geçmiş GERÇEKLEŞMEMİŞ GELİR de girişe GİRMEZ (gider gibi simetrik; gelmemiş
        avans/tahsilat → "Vadesi Geçen Tahsilatlar"da; kullanıcı isteği 2026-07-07)."""
        _reset_eur_rates(db)
        today = date.today()
        mid_last = (today.replace(day=1) - timedelta(days=1)).replace(day=15)
        _mk_rate(db, mid_last, 50.0)
        _mk_fe(db, event_date=mid_last, direction=1, is_realized=False,
               source_type="advance", amount=10000, currency="EUR", description="GELMEMIS AVANS")
        _mk_fe(db, event_date=mid_last, direction=1, is_realized=True,
               source_type="bank", amount=5000, description="GERCEKLESEN GELIR")
        db.commit()

        body = client.get(f"{URL}?period=monthly&offset=-1", headers=auth_headers).json()
        names = [i["name"] for g in body["giris"] for i in g["items"]]
        assert "GELMEMIS AVANS" not in names       # vadesi geçmiş gerçekleşmemiş gelir → hariç
        assert "GERCEKLESEN GELIR" in names         # gerçekleşmiş gelir → dahil


class TestTAccountRealizedSplit:
    """Grup bazında gerçekleşen/bekleyen bölünmesi (2026-07-06) — frontend '✓ Gerçekleşen'
    panelinin veri sözleşmesi: grup `realized_eur`/`realized_count` sayaçları + `item.is_realized`.
    Bölme SAYAÇLARLA yapılır (items MAX_ITEMS_PER_GROUP ile kırpık olabilir)."""

    def test_group_realized_counters_and_item_flags(self, client, auth_headers, db):
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        today = date.today()
        # Aynı grupta (Düzenli Ödemeler) karışık: 1 gerçekleşen + 2 bekleyen.
        # Bekleyenler bugüne yazılır (event_date < today olsa vadesi-geçmiş filtresi eler).
        _mk_fe(db, source_type="recurring", direction=-1, amount=5000,
               is_realized=True, event_date=today, description="T-REC ODENDI")
        _mk_fe(db, source_type="recurring", direction=-1, amount=2000,
               is_realized=False, event_date=today, description="T-REC BEKLIYOR A")
        _mk_fe(db, source_type="recurring", direction=-1, amount=3000,
               is_realized=False, event_date=today, description="T-REC BEKLIYOR B")
        db.commit()

        body = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers).json()
        g = _group(body, "cikis", "Düzenli Ödemeler")
        assert g is not None
        assert g["item_count"] == 3
        assert g["total_eur"] == 200.0          # (5000+2000+3000)/50
        assert g["realized_count"] == 1
        assert g["realized_eur"] == 100.0       # 5000/50
        flags = {i["name"]: i["is_realized"] for i in g["items"]}
        assert flags["T-REC ODENDI"] is True
        assert flags["T-REC BEKLIYOR A"] is False
        assert flags["T-REC BEKLIYOR B"] is False

    def test_group_realized_sums_reconcile_with_column(self, client, auth_headers, db):
        """Σ grup.realized_eur == kolon realized_*_eur (aynı olaylardan iki ayrı toplama)."""
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        today = date.today()
        _mk_fe(db, direction=1, amount=4000, is_realized=True, event_date=today,
               category_name="T-SPLIT GELIR", description="T-GELIR BANKA")
        _mk_fe(db, source_type="advance", direction=1, amount=6000, is_realized=False,
               event_date=today, description="T-GELIR AVANS")
        _mk_fe(db, direction=-1, amount=1500, is_realized=True, event_date=today,
               category_name="T-SPLIT GIDER", description="T-GIDER BANKA")
        db.commit()

        body = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers).json()
        for side, col_key in (("giris", "realized_in_eur"), ("cikis", "realized_out_eur")):
            group_sum = sum(g.get("realized_eur", 0.0) for g in body[side])
            # Grup-başına yuvarlama ile kolon yuvarlaması arasında kuruş payı olabilir
            assert abs(group_sum - body[col_key]) < 0.5, (side, group_sum, body[col_key])
        # Bekleyen taraf da tutarlı: Σ(total-realized) == total − realized
        for side, tot_key, real_key in (("giris", "total_in_eur", "realized_in_eur"),
                                        ("cikis", "total_out_eur", "realized_out_eur")):
            pending_sum = sum(g["total_eur"] - g.get("realized_eur", 0.0) for g in body[side])
            assert abs(pending_sum - (body[tot_key] - body[real_key])) < 0.5


class TestTAccountItemOrdering:
    """Grup items'ı HER ZAMAN tarih sıralı dönmeli (2026-07-06 düzeltmesi) — CC projeksiyonları
    grup SONUNA kart sırasıyla eklenir; sıralanmazsa frontend tarih-bucket'ları (keyed each,
    day.date anahtarı) mükerrer anahtar üretir → svelte-each-dupkey donma sınıfı."""

    def test_cc_projection_appended_out_of_order_gets_sorted(self, client, auth_headers, db, monkeypatch):
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        today = date.today()
        d_early = date(today.year, today.month, 10)
        d_late = date(today.year, today.month, 20)
        # Gerçek ekstre FE'si ayın 20'sinde (grup items'ına ÖNCE girer)
        _mk_fe(db, source_type="cc_payment", direction=-1, amount=1000, is_realized=True,
               event_date=d_late, description="T-GERCEK EKSTRE")
        db.commit()
        # Projeksiyon ayın 10'unda ama grup SONUNA eklenir (kart-id sırası) → sırasız senaryo
        monkeypatch.setattr(
            "app.services.cc_projection_service.due_reserve_projections",
            lambda db, today=None: [
                {"date": d_early.isoformat(), "amount": 500, "description": "T-PROJ KART"},
            ],
        )
        body = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers).json()
        kk = _group(body, "cikis", "KK Borç Ödemeleri")
        assert kk is not None
        dates = [i["date"] for i in kk["items"]]
        assert dates == sorted(dates), f"items tarih sıralı değil: {dates}"
        assert dates[0] == d_early.isoformat()  # projeksiyon kronolojik yerine oturdu


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


class TestTAccountFaaliyetFinansman:
    """Faaliyet / Finansman ayrımı (3a tasarımı) — salt yeniden-mercek, net değişmez."""

    def test_section_labels_and_nets_reconcile(self, client, auth_headers, db):
        today = date.today()
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)  # 1 EUR = 50 TRY

        # Faaliyet geliri (banka kategori) + faaliyet gideri (cari ödeme)
        _mk_fe(db, direction=1, amount=10000, category_name="T-FF KONAKLAMA")   # +200 EUR
        _mk_fe(db, direction=-1, amount=5000, source_type="vendor_payment",
               description="T-FF CARİ ÖDEME")                                    # -100 EUR faaliyet
        # Finansman: alınan avans (income) + kredi taksiti (expense)
        _mk_fe(db, direction=1, amount=4000, source_type="advance",
               description="T-FF AVANS")                                         # +80 EUR finansman
        _mk_fe(db, direction=-1, amount=2000, source_type="credit",
               description="T-FF KREDİ TAKSİTİ")                                 # -40 EUR finansman

        body = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers).json()

        # section alanı gruplarda var
        avans = _group(body, "giris", "Avanslar")
        kredi = _group(body, "cikis", "Kredi / Leasing Taksitleri")
        cari = _group(body, "cikis", "Cari Ödemeleri")
        assert avans and avans["section"] == "finansman"
        assert kredi and kredi["section"] == "finansman"
        assert cari and cari["section"] == "faaliyet"

        # Net = Faaliyet Neti + Finansman Neti (mutabakat — yeniden-mercek toplamı değiştirmez)
        assert "faaliyet_net_eur" in body and "finansman_net_eur" in body
        assert round(body["faaliyet_net_eur"] + body["finansman_net_eur"], 2) == body["net_eur"]
        # Finansman neti = +80 (avans) - 40 (kredi) = +40 EUR
        assert body["finansman_net_eur"] == 40.0


class TestTAccountBankName:
    """Kalemler banka adını taşır — frontend satır başı banka amblemi (2026-07-13)."""

    def test_items_carry_bank_name(self, client, auth_headers, db):
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)

        _mk_fe(db, direction=1, amount=5000, category_name="T-BANKA ROZET",
               bank_name="Yapı Kredi", description="T-BANKA ROZET GELİR")
        _mk_fe(db, direction=-1, amount=2000, source_type="check",
               bank_name="VakıfBank", description="T-BANKA ROZET ÇEK")
        _mk_fe(db, direction=-1, amount=1000, source_type="vendor_payment",
               description="T-BANKA ROZET CARİ")  # bankasız → None

        body = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers).json()

        g = _group(body, "giris", "T-BANKA ROZET")
        assert g and g["items"][0]["bank_name"] == "Yapı Kredi"
        cek = _group(body, "cikis", "Verilen Çekler")
        item = next(i for i in cek["items"] if i["name"] == "T-BANKA ROZET ÇEK")
        assert item["bank_name"] == "VakıfBank"
        cari = _group(body, "cikis", "Cari Ödemeleri")
        item = next(i for i in cari["items"] if i["name"] == "T-BANKA ROZET CARİ")
        assert item["bank_name"] is None


class TestTAccountAgencyDisplayName:
    """Acenta banka kalemi adı tag_note'tan (çözülen acente adı) gelir (2026-07-13)."""

    def test_agency_item_shows_tag_note_instead_of_description(self, client, auth_headers, db):
        _reset_eur_rates(db)
        _mk_rate(db, MIN_DATE, 50)
        _mk_fe(db, direction=1, amount=5000, category_name="Acenta",
               tag_note="NORDİC LEİSURE TRAVEL",
               description="Diğer Diğer TRAVE/020726/278982")
        _mk_fe(db, direction=1, amount=3000, category_name="Acenta",
               description="Diğer Diğer SEYAHAT ACENT/999/1")  # tag_note yok → açıklama

        body = client.get(f"{URL}?period=monthly&offset=0", headers=auth_headers).json()
        g = _group(body, "giris", "Acenta")
        names = [i["name"] for i in g["items"]]
        assert "NORDİC LEİSURE TRAVEL" in names
        assert "Diğer Diğer SEYAHAT ACENT/999/1" in names
        assert "Diğer Diğer TRAVE/020726/278982" not in names
