"""Otel rezervasyon modülü testleri (sales.hotel_reservation)."""
import io
import os
from datetime import date

import pytest
import xlwt

from app.models.reservation import Reservation, ReservationUpload

# Gerçek dosya — entegrasyon testi için
REAL_XLS = "/home/ec2-user/uploads/2025berk.xls"
HAVE_REAL_XLS = os.path.exists(REAL_XLS)


def _build_minimal_xls() -> bytes:
    """Crystal Reports formatına uygun minimal bir test XLS oluştur.

    Yapı:
        R0: Otel adı + Reservation Report
        R1: Tarih aralıkları (Excel serial)
        R2: Boş
        R3: Header
        R4-R5: İki gerçek rezervasyon
        R6: Boş satır (atlanmalı)
        R7: Subtotal "Room" satırı (atlanmalı)
    """
    wb = xlwt.Workbook()
    s = wb.add_sheet("Sheet1")

    # R0
    s.write(0, 0, "TEST HOTEL")
    s.write(0, 1, "Reservation Report")
    # R1 — Excel serials: 46300 ~ 2026-10-05
    s.write(1, 0, "Checkin Date(s)")
    s.write(1, 1, ":")
    s.write(1, 2, 46300.0)
    s.write(1, 3, "-")
    s.write(1, 4, 46330.0)
    s.write(1, 18, 46000.0)  # record start
    s.write(1, 20, 46350.0)  # record end
    # R3 — header
    headers = [
        "Room", "RecId", "Agency", "Type", "Voucher", "Guests", "C/In", "C/Out",
        "#", "Record", "Board", "Viptype", "Rm", "Adl", "Pch", "Fch", "Bby",
        "Nation", "Net", "Curr", "EUR Total", "PerRoom", "PerAdult", "Rez.St", "Status",
    ]
    for i, h in enumerate(headers):
        s.write(3, i, h)

    # R4 — first reservation
    row1 = [
        "", 900001, "TEST AG", "STD DNZ", "V001", "Mr Tester", 46305.0, 46312.0,
        7, 46100.0, "AI", "Normal", 1, 2, 0, 0, 0,
        "DEU", 700.0, "EUR", 700.0, 100.0, 50.0, "Definite", "Reservation",
    ]
    for i, v in enumerate(row1):
        s.write(4, i, v)

    # R5 — second reservation (Option, RUS)
    row2 = [
        "", 900002, "MORE AG", "FAM DNZ", "V002", "Mr Two,Mrs Two", 46310.0, 46324.0,
        14, 46150.0, "UAI", "Normal", 1, 3, 1, 0, 0,
        "RUS", 1400.0, "EUR", 1400.0, 100.0, 33.3, "Option", "Reservation",
    ]
    for i, v in enumerate(row2):
        s.write(5, i, v)

    # R6 — empty row (skipped)
    # R7 — subtotal style row: RecId is a string ("Room") → must be skipped
    s.write(7, 1, "Room")
    s.write(7, 2, 543)  # numeric noise

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


@pytest.fixture
def minimal_xls_bytes():
    return _build_minimal_xls()


# ──────────────────────────────────────────────────────────────
#   Parser unit tests
# ──────────────────────────────────────────────────────────────


def test_parse_minimal_xls(tmp_path, minimal_xls_bytes):
    from app.utils.reservation_parser import parse_reservation_excel
    p = tmp_path / "mini.xls"
    p.write_bytes(minimal_xls_bytes)
    result = parse_reservation_excel(str(p))
    assert result.hotel_name == "TEST HOTEL"
    assert len(result.reservations) == 2, "Subtotal satırı atlanmalı, sadece 2 rez kalmalı"
    rec_ids = sorted(r.rec_id for r in result.reservations)
    assert rec_ids == [900001, 900002]
    r1 = next(r for r in result.reservations if r.rec_id == 900001)
    assert r1.agency == "TEST AG"
    assert r1.nights == 7
    assert r1.adult == 2
    assert r1.eur_total == 700.0
    assert r1.rez_status == "Definite"
    assert r1.checkin_date.year == 2026


@pytest.mark.skipif(not HAVE_REAL_XLS, reason="Gerçek XLS bulunamadı")
def test_parse_real_xls():
    from app.utils.reservation_parser import parse_reservation_excel
    r = parse_reservation_excel(REAL_XLS)
    assert r.hotel_name and "SIDE PRENSES" in r.hotel_name.upper()
    assert len(r.reservations) == 4813
    total = sum(p.eur_total for p in r.reservations)
    assert 4_591_000 < total < 4_592_500


# ──────────────────────────────────────────────────────────────
#   Endpoint tests
# ──────────────────────────────────────────────────────────────


def test_upload_creates_new(client, auth_headers, db, minimal_xls_bytes):
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    res = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_rows"] == 2
    assert data["new_rows"] == 2
    assert data["updated_rows"] == 0
    assert data["hotel_name"] == "TEST HOTEL"

    assert db.query(Reservation).filter(Reservation.rec_id.in_([900001, 900002])).count() == 2


def test_upload_upserts_existing(client, auth_headers, db, minimal_xls_bytes):
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    first = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)
    assert first.status_code == 200
    assert first.json()["new_rows"] == 2

    # Manuel olarak bir satırı değiştir — upsert üzerine yazmalı
    rec = db.query(Reservation).filter(Reservation.rec_id == 900001).first()
    assert rec is not None
    rec.agency = "MODIFIED MANUALLY"
    db.commit()

    # İkinci yükleme
    files2 = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    second = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files2)
    assert second.status_code == 200
    payload = second.json()
    assert payload["new_rows"] == 0
    assert payload["updated_rows"] == 2

    # Manuel değişiklik geri alınmış olmalı (upsert XLS'i otorite)
    rec_after = db.query(Reservation).filter(Reservation.rec_id == 900001).first()
    assert rec_after.agency == "TEST AG"


def test_upload_skips_subtotal_rows(client, auth_headers, db, minimal_xls_bytes):
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    res = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)
    assert res.status_code == 200
    # Sadece 2 gerçek rezervasyon — alt-toplam ("Room") satırı atlanmalı
    total = db.query(Reservation).count()
    assert total == 2


def test_summary_kpi_aggregates(client, auth_headers, minimal_xls_bytes):
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)

    res = client.get("/api/sales/reservations/summary", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    kpi = data["kpi"]
    assert kpi["total_rez"] == 2
    assert kpi["total_eur"] == 2100.0  # 700 + 1400
    # 7 gece x 1 oda + 14 gece x 1 oda = 21 oda-gece
    assert kpi["total_room_nights"] == 21
    # Pax: (2+0+0+0) + (3+1+0+0) = 6
    assert kpi["total_pax"] == 6
    # ADR = 2100 / 21 = 100
    assert kpi["adr"] == 100.0
    # avg_los = 21 / 2 = 10.5
    assert kpi["avg_los"] == 10.5
    assert kpi["definite_count"] == 1
    assert kpi["option_count"] == 1

    # Pazar dağılımı: DEU + RUS olmalı
    nations = {n["code"]: n for n in data["by_nation"]}
    assert "DEU" in nations and "RUS" in nations


def test_summary_year_filter(client, auth_headers, minimal_xls_bytes):
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)

    # 2027 — veri yok → kpi sıfır olmalı
    res = client.get(
        "/api/sales/reservations/summary?start_date=2027-01-01&end_date=2027-12-31",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["kpi"]["total_rez"] == 0

    # 2026 — iki rezervasyon
    res2 = client.get(
        "/api/sales/reservations/summary?start_date=2026-01-01&end_date=2026-12-31",
        headers=auth_headers,
    )
    assert res2.status_code == 200
    assert res2.json()["kpi"]["total_rez"] == 2


def test_unauthorized_blocked(client, minimal_xls_bytes):
    """Yetkisiz kullanıcı endpoint'lere erişemez."""
    res = client.get("/api/sales/reservations/summary")
    assert res.status_code == 401

    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    res2 = client.post("/api/sales/reservations/upload", files=files)
    assert res2.status_code == 401


def test_delete_upload_keeps_reservations(client, auth_headers, db, minimal_xls_bytes):
    """Yükleme silinince rezervasyon satırları korunur (upload_id NULL)."""
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    upload_res = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)
    assert upload_res.status_code == 200
    upload_id = upload_res.json()["upload_id"]

    # Silmeden önce 2 rez, 1 upload var
    assert db.query(Reservation).count() == 2
    assert db.query(ReservationUpload).count() == 1

    del_res = client.delete(f"/api/sales/reservations/uploads/{upload_id}", headers=auth_headers)
    assert del_res.status_code == 204

    # Upload silindi ama rezervasyonlar duruyor (upload_id NULL düştü)
    assert db.query(ReservationUpload).filter(ReservationUpload.id == upload_id).count() == 0
    surviving = db.query(Reservation).all()
    assert len(surviving) == 2
    assert all(r.upload_id is None for r in surviving)


def test_list_reservations_paginated_and_filtered(client, auth_headers, minimal_xls_bytes):
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)

    res = client.get("/api/sales/reservations/?page_size=10", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2

    # Ulus filtresi
    res2 = client.get("/api/sales/reservations/?nation=DEU", headers=auth_headers)
    assert res2.status_code == 200
    items = res2.json()["items"]
    assert len(items) == 1
    assert items[0]["nation"] == "DEU"


# ──────────────────────────────────────────────────────────────
#   Removal candidates + bulk-delete
# ──────────────────────────────────────────────────────────────


def _seed_orphan_reservation(db, *, rec_id: int, checkin: date, record: date) -> Reservation:
    """Test için kapsam içinde bir orphan rezervasyon oluştur."""
    rez = Reservation(
        rec_id=rec_id,
        agency="ORPHAN AG",
        room_type="STD DNZ",
        voucher=f"V{rec_id}",
        guests="Mr Orphan",
        checkin_date=checkin,
        checkout_date=checkin,
        nights=1,
        record_date=record,
        board="AI",
        rooms=1,
        adult=2,
        child_paid=0,
        child_free=0,
        baby=0,
        nation="DEU",
        net_amount=500.0,
        currency="EUR",
        eur_total=500.0,
        rez_status="Definite",
        status="Reservation",
    )
    db.add(rez)
    db.commit()
    return rez


def test_upload_returns_removal_candidates(client, auth_headers, db, minimal_xls_bytes):
    """Yüklemenin kapsamında olup dosyada bulunmayan kayıt removal_candidates olarak döner."""
    # Minimal XLS: check-in 2026-10-05 ↔ 2026-11-04, record 2025-12-12 ↔ 2026-11-24
    # Bu aralığa düşen ama dosyada olmayan bir orphan ekle
    _seed_orphan_reservation(
        db,
        rec_id=900099,
        checkin=date(2026, 10, 15),
        record=date(2026, 5, 10),
    )

    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    res = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)
    assert res.status_code == 200, res.text
    payload = res.json()

    assert "removal_candidates" in payload
    candidates = payload["removal_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["rec_id"] == 900099
    assert candidates[0]["agency"] == "ORPHAN AG"
    assert candidates[0]["eur_total"] == 500.0


def test_upload_no_candidates_when_all_present(client, auth_headers, minimal_xls_bytes):
    """Aynı dosya iki kez yüklenince ikinci yüklemede removal_candidates boş kalmalı."""
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)

    files2 = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    res = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files2)
    assert res.status_code == 200
    assert res.json()["removal_candidates"] == []


def test_upload_orphan_outside_scope_not_candidate(client, auth_headers, db, minimal_xls_bytes):
    """Kapsam dışındaki orphan aday gösterilmez (farklı tarih aralığı)."""
    # check-in 2027 → minimal XLS'in 2026 kapsamının dışında
    _seed_orphan_reservation(
        db,
        rec_id=900088,
        checkin=date(2027, 6, 1),
        record=date(2026, 5, 10),
    )

    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    res = client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)
    assert res.status_code == 200
    assert res.json()["removal_candidates"] == []


def test_bulk_delete_removes_records(client, auth_headers, db, minimal_xls_bytes):
    """bulk-delete: verilen ID listesini siler."""
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)

    ids = [r.id for r in db.query(Reservation).all()]
    assert len(ids) == 2

    res = client.post(
        "/api/sales/reservations/bulk-delete",
        headers=auth_headers,
        json={"ids": ids},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["deleted"] == 2
    assert payload["skipped"] == 0

    assert db.query(Reservation).count() == 0


def test_bulk_delete_partial_with_missing_ids(client, auth_headers, db, minimal_xls_bytes):
    """Var olmayan ID'ler skipped olarak sayılır, mevcutlar silinir."""
    files = {"file": ("test.xls", minimal_xls_bytes, "application/vnd.ms-excel")}
    client.post("/api/sales/reservations/upload", headers=auth_headers, files=files)

    existing = [r.id for r in db.query(Reservation).all()]
    assert len(existing) == 2
    # Mevcut bir ID + olmayan 2 ID
    payload = client.post(
        "/api/sales/reservations/bulk-delete",
        headers=auth_headers,
        json={"ids": [existing[0], 999999, 999998]},
    ).json()

    assert payload["deleted"] == 1
    assert payload["skipped"] == 2
    assert any("bulunamadı" in r for r in payload["skipped_reasons"])

    # Diğer rezervasyon dokunulmamış olmalı
    assert db.query(Reservation).count() == 1


def test_bulk_delete_empty_ids(client, auth_headers):
    """Boş liste 200 dönmeli, hiçbir şey silmemeli."""
    res = client.post(
        "/api/sales/reservations/bulk-delete",
        headers=auth_headers,
        json={"ids": []},
    )
    assert res.status_code == 200
    assert res.json()["deleted"] == 0


def test_bulk_delete_over_5000_rejected(client, auth_headers):
    """5000 üzeri ID isteği 400 ile reddedilir (DoS koruma)."""
    res = client.post(
        "/api/sales/reservations/bulk-delete",
        headers=auth_headers,
        json={"ids": list(range(1, 5002))},
    )
    assert res.status_code == 400
    assert "5000" in res.json()["detail"]


def test_bulk_delete_unauthorized():
    """Auth'sız erişim 401."""
    from fastapi.testclient import TestClient
    from app.main import app
    res = TestClient(app).post("/api/sales/reservations/bulk-delete", json={"ids": [1]})
    assert res.status_code == 401
