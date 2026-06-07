"""Otel rezervasyonlarının SednaPrenses (önbüro) DB'sinden içe aktarımı.

`fetch_reservations` mock'lanır (CI'da tünel yok). Aktif-yalnız değişmezliği: aktifler
upsert, iptal/silinmiş süpürülür → tablo Sedna aktif rezervasyonlarının aynası. Senkronlanan
veri `occupancy_metrics`'i besler (kişi başı maliyet KPI'sının paydası).
"""
from datetime import date, timedelta
from unittest.mock import patch

from app.models.exchange_rate import ExchangeRate
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.routers.sales.reservations.sedna_import import _window_start
from app.utils.occupancy import occupancy_metrics

PREFIX = "/api/sales/reservations"
TARGET = "app.routers.sales.reservations.sedna_import"

WS = _window_start()                 # cari yıl 1 Ocak (pencere başı)
CI = date(WS.year, 3, 2)             # pencere içi check-in
CO = date(WS.year, 3, 4)            # 2 gece (checkout exclusive)


def _row(rec_id, ci=CI, co=CO, agency="ALLTOURS D", nation="DEU", adult=2, child_paid=0,
         child_free=0, baby=0, room_price=300, currency="EUR", status_code=1, cancel_date=None,
         room_type="STD DNZ", voucher="V1", guests="Mr X,Mrs Y", board="AI", vip_type="Normal"):
    """Sedna `fetch_reservations` satırını taklit eder (sorgu kolon anahtarlarıyla)."""
    return {
        "rec_id": rec_id, "agency": agency, "room_type": room_type, "voucher": voucher,
        "guests": guests, "checkin_date": ci, "checkout_date": co, "record_date": ci,
        "board": board, "vip_type": vip_type, "adult": adult, "child_paid": child_paid,
        "child_free": child_free, "baby": baby, "nation": nation, "room_price": room_price,
        "currency": currency, "status_code": status_code, "cancel_date": cancel_date,
    }


def _import(client, headers, rows):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_reservations", return_value=rows):
        return client.post(f"{PREFIX}/sedna-import", headers=headers)


def test_import_requires_use(client, no_perm_user_headers):
    assert client.post(f"{PREFIX}/sedna-import", headers=no_perm_user_headers).status_code == 403


def test_status_endpoint(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True):
        assert client.get(f"{PREFIX}/sedna-status", headers=auth_headers).json()["configured"] is True


def test_creates_and_maps(client, auth_headers, db):
    """Aktif rezervasyon eklenir + alanlar doğru eşlenir (EUR, nation, nights, pax, durum)."""
    j = _import(client, auth_headers, [_row(900001, room_price=300, adult=2, child_paid=1)]).json()
    assert j["reservations_new"] == 1 and j["reservations_active"] == 1 and j["removed"] == 0
    r = db.query(Reservation).filter_by(rec_id=900001).first()
    assert r.agency == "ALLTOURS D" and r.nation == "DEU" and r.currency == "EUR"
    assert r.nights == 2 and r.rooms == 1 and r.adult == 2 and r.child_paid == 1
    assert float(r.eur_total) == 300.0 and r.rez_status == "Definite" and r.status == "Reservation"


def test_upsert_updates_existing(client, auth_headers, db):
    """Aynı rec_id ikinci kez → güncellenir, mükerrer olmaz."""
    _import(client, auth_headers, [_row(900001, agency="ESKİ")])
    j = _import(client, auth_headers, [_row(900001, agency="YENİ")]).json()
    assert j["reservations_new"] == 0 and j["reservations_updated"] == 1
    assert db.query(Reservation).filter_by(rec_id=900001).count() == 1
    assert db.query(Reservation).filter_by(rec_id=900001).first().agency == "YENİ"


def test_cancelled_is_deleted(client, auth_headers, db):
    """Status=-1 (iptal) olan kayıt tablodan silinir → doluluğu şişirmez."""
    _import(client, auth_headers, [_row(900001), _row(900002)])
    rows = [_row(900001), _row(900002, status_code=-1, cancel_date=WS)]
    j = _import(client, auth_headers, rows).json()
    assert j["removed"] == 1
    assert db.query(Reservation).filter_by(rec_id=900002).first() is None
    assert db.query(Reservation).filter_by(rec_id=900001).first() is not None


def test_hard_delete_swept(client, auth_headers, db):
    """Kaynakta artık olmayan (fetch'te gelmeyen) pencere-içi kayıt süpürülür."""
    _import(client, auth_headers, [_row(900001), _row(900002)])
    j = _import(client, auth_headers, [_row(900001)]).json()  # 900002 fetch'te yok
    assert j["removed"] == 1
    assert db.query(Reservation).filter_by(rec_id=900002).first() is None


def test_out_of_window_preserved(client, auth_headers, db):
    """Pencere dışı (geçmiş yıl, XLS'ten) kayıt süpürmeden etkilenmez."""
    old = Reservation(
        rec_id=900099, checkin_date=WS - timedelta(days=40), checkout_date=WS - timedelta(days=38),
        nights=2, record_date=WS - timedelta(days=50), rooms=1, adult=2, rez_status="Definite",
    )
    db.add(old)
    db.flush()
    _import(client, auth_headers, [_row(900001)])
    assert db.query(Reservation).filter_by(rec_id=900099).first() is not None


def test_currency_conversion_tl_to_eur(client, auth_headers, db):
    """TL sözleşmeli rezervasyon EUR'ya çevrilir (ciro şişmesin); EUR olduğu gibi kalır.

    Regresyon: önceki sürüm RoomPrice'ı hep EUR sayıyordu → TL sözleşmeler (yerli/WEBRES)
    2026 cirosunu ~2× şişiriyordu (₺5,9M = €5,9M gibi).
    """
    db.add(ExchangeRate(date=date(WS.year, 1, 2), currency_code="EUR", forex_selling=50.0, unit=1))
    db.flush()
    _import(client, auth_headers, [
        _row(900010, currency="EUR", room_price=300),     # EUR → 300 €
        _row(900011, currency="TL", room_price=15000),    # TL 15.000 ÷ 50 = 300 €
    ])
    eur = db.query(Reservation).filter_by(rec_id=900010).first()
    tl = db.query(Reservation).filter_by(rec_id=900011).first()
    assert float(eur.eur_total) == 300.0 and eur.currency == "EUR"
    assert float(tl.eur_total) == 300.0 and tl.currency == "TL"   # çevrildi (15000≠300)
    assert float(tl.net_amount) == 15000.0                        # ham TL tutarı korunur


def test_synced_data_feeds_occupancy(client, auth_headers, db):
    """Uçtan uca: senkronlanan rezervasyonlar occupancy_metrics gecelemesini üretir."""
    db.add(RoomType(code="STD", name="Standart", total_rooms=100, is_active=True))
    db.flush()
    _import(client, auth_headers, [
        _row(900001, adult=2, child_paid=1),   # pax 3 × 2 gece = 6
        _row(900002, adult=2),                 # pax 2 × 2 gece = 4
    ])
    m = occupancy_metrics(db, date(WS.year, 3, 1), date(WS.year, 3, 31))
    assert m["guest_nights"] == 10 and m["room_nights"] == 4
