"""Oda tipleri modülü testleri (sales.room_types) + doluluk hesabı testi."""
from datetime import date

import pytest

from app.models.reservation import Reservation
from app.models.room_type import RoomType


@pytest.fixture(autouse=True)
def _wipe_room_types(db):
    """Her test başında room_types tablosunu temizle.

    Migration seed (9 satır) testler için belirsiz başlangıç yaratıyor.
    Her test kendi senaryosunu kursun. SAVEPOINT zaten test sonunda rollback eder.
    """
    db.query(RoomType).delete()
    db.flush()
    yield


# ─── CRUD: Liste ────────────────────────────────────────


def test_list_empty(client, auth_headers):
    res = client.get("/api/sales/room-types/", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["total_capacity"] == 0
    assert data["active_count"] == 0


def test_list_returns_active_total(client, auth_headers, db):
    db.add_all([
        RoomType(code="A", name="A tipi", total_rooms=100, max_occupancy=2, sort_order=10),
        RoomType(code="B", name="B tipi", total_rooms=50, max_occupancy=3, sort_order=20),
        RoomType(code="C", name="C tipi", total_rooms=10, max_occupancy=4, sort_order=30, is_active=False),
    ])
    db.flush()

    res = client.get("/api/sales/room-types/", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_capacity"] == 150  # Sadece aktif (10 hariç)
    assert data["active_count"] == 2
    assert len(data["items"]) == 2  # Pasif gizli

    # include_inactive=true ile pasif de gelir
    res2 = client.get("/api/sales/room-types/?include_inactive=true", headers=auth_headers)
    assert res2.status_code == 200
    assert len(res2.json()["items"]) == 3


# ─── CRUD: Oluştur ──────────────────────────────────────


def test_create_room_type(client, auth_headers, db):
    payload = {
        "code": "std kara",  # küçük harf → büyük harfe normalize
        "name": "Standart Kara",
        "total_rooms": 126,
        "max_occupancy": 3,
        "sort_order": 10,
        "is_active": True,
    }
    res = client.post("/api/sales/room-types/", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["code"] == "STD KARA"  # uppercase normalize
    assert data["total_rooms"] == 126

    # DB'de doğrula
    db.expire_all()
    rt = db.query(RoomType).filter(RoomType.code == "STD KARA").first()
    assert rt is not None
    assert rt.total_rooms == 126


def test_create_duplicate_code_fails(client, auth_headers, db):
    db.add(RoomType(code="DUP", name="İlk", total_rooms=5, max_occupancy=2))
    db.flush()

    res = client.post(
        "/api/sales/room-types/",
        json={"code": "DUP", "name": "İkinci", "total_rooms": 10},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "zaten kayıtlı" in res.json()["detail"].lower()


def test_create_validation_errors(client, auth_headers):
    # Boş kod
    res = client.post(
        "/api/sales/room-types/",
        json={"code": "", "name": "X", "total_rooms": 5},
        headers=auth_headers,
    )
    assert res.status_code == 422

    # Negatif oda sayısı
    res2 = client.post(
        "/api/sales/room-types/",
        json={"code": "NEG", "name": "X", "total_rooms": -1},
        headers=auth_headers,
    )
    assert res2.status_code == 422


# ─── CRUD: Güncelle ─────────────────────────────────────


def test_update_room_type(client, auth_headers, db):
    rt = RoomType(code="UPD", name="Eski Ad", total_rooms=10, max_occupancy=2)
    db.add(rt)
    db.flush()
    rt_id = rt.id

    res = client.patch(
        f"/api/sales/room-types/{rt_id}",
        json={"name": "Yeni Ad", "total_rooms": 20},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Yeni Ad"
    assert res.json()["total_rooms"] == 20

    db.expire_all()
    refreshed = db.query(RoomType).filter(RoomType.id == rt_id).first()
    assert refreshed.name == "Yeni Ad"
    assert refreshed.total_rooms == 20


def test_update_nonexistent_returns_404(client, auth_headers):
    res = client.patch(
        "/api/sales/room-types/99999",
        json={"name": "X"},
        headers=auth_headers,
    )
    assert res.status_code == 404


# ─── CRUD: Sil ──────────────────────────────────────────


def test_delete_room_type_no_reservations(client, auth_headers, db):
    rt = RoomType(code="DEL", name="Silinecek", total_rooms=5, max_occupancy=2)
    db.add(rt)
    db.flush()
    rt_id = rt.id

    res = client.delete(f"/api/sales/room-types/{rt_id}", headers=auth_headers)
    assert res.status_code == 204

    db.expire_all()
    assert db.query(RoomType).filter(RoomType.id == rt_id).first() is None


def test_delete_blocked_when_reservations_exist(client, auth_headers, db):
    """Bu tipe ait rezervasyon varsa silme engellenmelidir."""
    rt = RoomType(code="USED", name="Kullanımda", total_rooms=5, max_occupancy=2)
    db.add(rt)
    db.flush()

    db.add(Reservation(
        rec_id=99001,
        room_type="USED",
        checkin_date=date(2026, 5, 1),
        checkout_date=date(2026, 5, 8),
        nights=7,
        record_date=date(2026, 1, 1),
        rooms=1,
    ))
    db.flush()

    res = client.delete(f"/api/sales/room-types/{rt.id}", headers=auth_headers)
    assert res.status_code == 400
    assert "rezervasyon" in res.json()["detail"].lower()
    # Pasif yapma önerisi mesajda olmalı
    assert "pasif" in res.json()["detail"].lower()


# ─── Yetki ──────────────────────────────────────────────


def test_unauthorized_blocked(client):
    res = client.get("/api/sales/room-types/")
    assert res.status_code == 401


# ─── Doluluk hesabı (asıl entegrasyon testi) ────────────


def test_summary_occupancy_calculations(client, auth_headers, db):
    """/summary endpoint'i doluluk metriklerini doğru hesaplar."""
    # 2 oda tipi: A (10 oda), B (5 oda) → toplam 15 kapasite
    db.add_all([
        RoomType(code="ROOM_A", name="A", total_rooms=10, max_occupancy=2, sort_order=10),
        RoomType(code="ROOM_B", name="B", total_rooms=5, max_occupancy=2, sort_order=20),
    ])

    # 2 rezervasyon:
    # rez1: A tipi, 10 gece, 1 oda → 10 oda-gece
    # rez2: B tipi, 5 gece, 2 oda → 10 oda-gece
    # Toplam: 20 oda-gece
    db.add_all([
        Reservation(
            rec_id=80001,
            room_type="ROOM_A",
            checkin_date=date(2026, 6, 1),
            checkout_date=date(2026, 6, 11),
            nights=10,
            record_date=date(2026, 5, 1),
            rooms=1,
            adult=2,
            eur_total=1000.0,
        ),
        Reservation(
            rec_id=80002,
            room_type="ROOM_B",
            checkin_date=date(2026, 6, 1),
            checkout_date=date(2026, 6, 6),
            nights=5,
            record_date=date(2026, 5, 1),
            rooms=2,
            adult=4,
            eur_total=500.0,
        ),
    ])
    db.flush()

    # Filtre: tam haziran (30 gün)
    res = client.get(
        "/api/sales/reservations/summary?start_date=2026-06-01&end_date=2026-06-30",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    kpi = data["kpi"]

    # KPI doluluk metrikleri
    assert kpi["total_capacity"] == 15  # 10 + 5
    assert kpi["date_range_days"] == 30  # haziran tam
    assert kpi["total_room_nights"] == 20  # 10 + 10
    # occupancy = 20 / (15 * 30) * 100 = 4.44%
    assert kpi["occupancy_pct"] == pytest.approx(4.44, abs=0.01)

    # Tip başına doluluk
    types = {t["name"]: t for t in data["by_room_type"]}
    assert "ROOM_A" in types
    assert types["ROOM_A"]["total_rooms"] == 10
    # A: 10 oda-gece / (10 oda * 30 gün) * 100 = 3.33%
    assert types["ROOM_A"]["occupancy_pct"] == pytest.approx(3.33, abs=0.01)

    assert "ROOM_B" in types
    assert types["ROOM_B"]["total_rooms"] == 5
    # B: 10 oda-gece / (5 oda * 30 gün) * 100 = 6.67%
    assert types["ROOM_B"]["occupancy_pct"] == pytest.approx(6.67, abs=0.01)


def test_summary_occupancy_no_room_types(client, auth_headers, db):
    """room_types boşken doluluk %0 olmalı, hata vermemeli."""
    # room_types boş (autouse fixture temizledi)
    db.add(Reservation(
        rec_id=80003,
        room_type="UNKNOWN",
        checkin_date=date(2026, 7, 1),
        checkout_date=date(2026, 7, 6),
        nights=5,
        record_date=date(2026, 6, 1),
        rooms=1,
        eur_total=500.0,
    ))
    db.flush()

    res = client.get("/api/sales/reservations/summary", headers=auth_headers)
    assert res.status_code == 200
    kpi = res.json()["kpi"]
    assert kpi["total_capacity"] == 0
    assert kpi["occupancy_pct"] == 0.0


def test_summary_occupancy_monthly_distribution(client, auth_headers, db):
    """Aylık doluluk her ayın günlerine göre hesaplanır."""
    db.add(RoomType(code="MON_A", name="A", total_rooms=10, max_occupancy=2))

    # Rezervasyon 28 Şubat → 7 Mart (8 gece)
    # Şubat: 1 gece (28'i) — Mart: 7 gece (1-7)
    db.add(Reservation(
        rec_id=80004,
        room_type="MON_A",
        checkin_date=date(2026, 2, 28),
        checkout_date=date(2026, 3, 8),
        nights=8,
        record_date=date(2026, 1, 1),
        rooms=1,
        eur_total=800.0,
    ))
    db.flush()

    res = client.get(
        "/api/sales/reservations/summary?start_date=2026-02-01&end_date=2026-03-31",
        headers=auth_headers,
    )
    assert res.status_code == 200
    monthly = {m["month"]: m for m in res.json()["monthly"]}

    # Şubat: 1 oda-gece / (10 oda * 28 gün) * 100 = 0.357%
    assert "2026-02" in monthly
    assert monthly["2026-02"]["room_nights"] == 1
    assert monthly["2026-02"]["occupancy_pct"] == pytest.approx(0.36, abs=0.01)
    # capacity_nights = 10 oda × 28 gün = 280; empty = 280 - 1 = 279
    assert monthly["2026-02"]["capacity_nights"] == 280
    assert monthly["2026-02"]["empty_nights"] == 279

    # Mart: 7 oda-gece / (10 oda * 31 gün) * 100 = 2.258%
    assert "2026-03" in monthly
    assert monthly["2026-03"]["room_nights"] == 7
    assert monthly["2026-03"]["occupancy_pct"] == pytest.approx(2.26, abs=0.02)
    # capacity_nights = 10 oda × 31 gün = 310; empty = 310 - 7 = 303
    assert monthly["2026-03"]["capacity_nights"] == 310
    assert monthly["2026-03"]["empty_nights"] == 303
