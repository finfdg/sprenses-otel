"""Cariler yeniden tasarımı (2026-07-23) — analitik görünümler + liste/detay genişletmeleri.

- GET /cariler/monthly-balances  → Aylık Bakiye (FIFO Kalan / Dönem Sonu) sekmesi
- GET /cariler/yearly-turnover   → Yıllık Ciro sekmesi (devir hariç, aylık dağılım)
- GET /cariler/vendors?sort_by=overdue → "Gecikmiş" sıralaması + satır overdue alanları
- GET /cariler/vendors?banned_only=true → Yasaklı çipi filtresi
- GET /cariler/vendors/summary   → overdue_total / nonzero_count / overdue_vendor_count
- GET /cariler/vendors/{id}?sort_by=... → işlem tablosu kolon sıralaması + fifo_remaining
"""
import uuid
from datetime import date, timedelta

import pytest

from app.models.vendor import STATUS_PAYMENT_BANNED, Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload

C = "/api/finance/cariler"


@pytest.fixture
def upload(db):
    u = VendorUpload(file_name="a.xlsx", file_url="/tmp/a.xlsx", uploaded_by=1,
                     total_vendors=1, total_transactions=0, new_transactions=0,
                     skipped_transactions=0)
    db.add(u)
    db.flush()
    return u


def _mk_vendor(db, name):
    v = Vendor(hesap_kodu="320.ANL." + uuid.uuid4().hex[:6], hesap_adi=name)
    db.add(v)
    db.flush()
    return v


def _mk_tx(db, vendor, upload, d, borc=0, alacak=0, due=None, match=None, ttype=None):
    tx = VendorTransaction(
        vendor_id=vendor.id, upload_id=upload.id, date=d, borc=borc, alacak=alacak,
        payment_due_date=due, match_number=match, transaction_type=ttype,
        bakiye=0, tx_hash=uuid.uuid4().hex,
    )
    db.add(tx)
    db.flush()
    return tx


# ─── Aylık Bakiye ────────────────────────────────────────

def test_monthly_balances_fifo_mode(client, auth_headers, db, upload):
    """FIFO Kalan: ödemeler en eski faturadan düşülür; tamamen kapanan cari listelenmez."""
    today = date.today()
    m1 = today.replace(day=1)

    v = _mk_vendor(db, "Aylık FIFO Cari")
    # Bu ayın faturaları: 10000 (erken vade) + 8000 (geç vade)
    _mk_tx(db, v, upload, m1, alacak=10000, due=today + timedelta(days=10))
    _mk_tx(db, v, upload, m1 + timedelta(days=1), alacak=8000, due=today + timedelta(days=20))
    # Ödeme 12000 → FIFO: ilk fatura tam + ikincinin 2000'i kapanır → kalan 6000
    _mk_tx(db, v, upload, m1 + timedelta(days=1), borc=12000)

    # Tamamen kapanan cari — listede GÖRÜNMEZ
    v2 = _mk_vendor(db, "Kapanmış Cari")
    _mk_tx(db, v2, upload, m1, alacak=5000, due=today + timedelta(days=5))
    _mk_tx(db, v2, upload, m1 + timedelta(days=1), borc=5000)
    db.commit()

    r = client.get(f"{C}/monthly-balances?year={today.year}&month={today.month}&mode=fifo",
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode"] == "fifo"
    by_vid = {i["vendor_id"]: i for i in data["items"]}
    assert v.id in by_vid
    row = by_vid[v.id]
    assert row["invoiced"] == 18000.0
    assert row["closed"] == 12000.0
    assert row["remaining"] == 6000.0
    assert v2.id not in by_vid  # kalan yok → gizli
    assert data["totals"]["remaining"] == 6000.0


def test_monthly_balances_period_mode_and_hide_zero(client, auth_headers, db, upload):
    """Dönem Sonu: ay sonuna kadarki tüm borç/alacak; hide_zero sıfır bakiyeyi gizler."""
    today = date.today()
    m1 = today.replace(day=1)

    v = _mk_vendor(db, "Dönem Cari")
    _mk_tx(db, v, upload, m1, alacak=18000)
    _mk_tx(db, v, upload, m1 + timedelta(days=1), borc=12000)

    vz = _mk_vendor(db, "Sıfır Bakiye Cari")
    _mk_tx(db, vz, upload, m1, alacak=5000)
    _mk_tx(db, vz, upload, m1 + timedelta(days=1), borc=5000)
    db.commit()

    base = f"{C}/monthly-balances?year={today.year}&month={today.month}&mode=period"
    r = client.get(base + "&hide_zero=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    by_vid = {i["vendor_id"]: i for i in r.json()["items"]}
    assert by_vid[v.id]["balance"] == -6000.0
    assert by_vid[v.id]["total_borc"] == 12000.0
    assert by_vid[v.id]["total_alacak"] == 18000.0
    assert vz.id not in by_vid

    r2 = client.get(base + "&hide_zero=false", headers=auth_headers)
    by_vid2 = {i["vendor_id"]: i for i in r2.json()["items"]}
    assert vz.id in by_vid2 and by_vid2[vz.id]["balance"] == 0.0


# ─── Yıllık Ciro ─────────────────────────────────────────

def test_yearly_turnover_excludes_devir(client, auth_headers, db, upload):
    year = date.today().year
    v = _mk_vendor(db, "Ciro Cari")
    # Devir kayıtları — ciroya GİRMEZ (match=-1 veya tip devir/açılış)
    _mk_tx(db, v, upload, date(year, 1, 2), alacak=100000, match=-1, ttype="Devir Fişi")
    _mk_tx(db, v, upload, date(year, 1, 3), alacak=50000, ttype="Açılış Fişi")
    # Gerçek faturalar
    _mk_tx(db, v, upload, date(year, 1, 10), alacak=4000, ttype="Mal Alış Faturası")
    _mk_tx(db, v, upload, date(year, 2, 5), alacak=6000, ttype="Mal Alış Faturası")
    _mk_tx(db, v, upload, date(year, 2, 20), alacak=2000, ttype="Hizmet Alış Faturası")
    db.commit()

    r = client.get(f"{C}/yearly-turnover?year={year}", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    by_vid = {i["vendor_id"]: i for i in data["items"]}
    row = by_vid[v.id]
    assert row["turnover"] == 12000.0
    assert row["invoice_count"] == 3
    assert row["monthly"][0] == 4000.0   # Ocak
    assert row["monthly"][1] == 8000.0   # Şubat
    assert sum(row["monthly"]) == 12000.0
    assert data["total_turnover"] == 12000.0


# ─── İzinler ─────────────────────────────────────────────

def test_analytics_permissions(client, viewer_user_headers, auth_headers):
    today = date.today()
    mb = f"{C}/monthly-balances?year={today.year}&month={today.month}"
    yt = f"{C}/yearly-turnover?year={today.year}"
    # Auth yok → 401 (client'ta önceki login cookie'si kalır — temizle)
    client.cookies.clear()
    assert client.get(mb).status_code == 401
    assert client.get(yt).status_code == 401
    # Salt-okuma GET → view yeterli
    assert client.get(mb, headers=viewer_user_headers).status_code == 200
    assert client.get(yt, headers=viewer_user_headers).status_code == 200


# ─── Cari listesi: gecikmiş sıralaması + yasaklı filtresi ─

def test_vendor_list_overdue_sort_and_fields(client, auth_headers, db, upload):
    today = date.today()
    va = _mk_vendor(db, "Gecikmişli Cari")
    _mk_tx(db, va, upload, today - timedelta(days=40), alacak=5000, due=today - timedelta(days=10))
    # Ödeme yok → net borç 5000, tamamı gecikmiş
    vb = _mk_vendor(db, "Temiz Cari")
    _mk_tx(db, vb, upload, today, alacak=3000, due=today + timedelta(days=30))
    db.commit()

    r = client.get(f"{C}/vendors?sort_by=overdue&sort_dir=desc&page_size=100",
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    ids = [i["id"] for i in items]
    assert ids.index(va.id) < ids.index(vb.id)
    by_vid = {i["id"]: i for i in items}
    assert by_vid[va.id]["overdue"] == 5000.0
    assert by_vid[va.id]["overdue_count"] == 1
    assert by_vid[vb.id]["overdue"] == 0.0


def test_vendor_list_banned_only(client, auth_headers, db, upload):
    vn = _mk_vendor(db, "Normal Cari")
    vb = _mk_vendor(db, "Yasaklı Cari")
    vb.status = STATUS_PAYMENT_BANNED
    db.commit()

    r = client.get(f"{C}/vendors?banned_only=true&page_size=100", headers=auth_headers)
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert vb.id in ids and vn.id not in ids


def test_vendor_list_invalid_sort_rejected(client, auth_headers):
    assert client.get(f"{C}/vendors?sort_by=id", headers=auth_headers).status_code == 422


# ─── Özet: yeni alanlar ──────────────────────────────────

def test_summary_new_fields(client, auth_headers, db, upload):
    today = date.today()
    v = _mk_vendor(db, "Özet Cari")
    _mk_tx(db, v, upload, today - timedelta(days=40), alacak=6000, due=today - timedelta(days=10))
    db.commit()

    s = client.get(f"{C}/vendors/summary", headers=auth_headers).json()
    assert s["overdue_total"] == 6000.0
    assert s["overdue_invoice_count"] == 1
    assert s["overdue_vendor_count"] == 1
    assert s["nonzero_count"] == 1
    assert s["banned_count"] == 0


# ─── Cari detay: kolon sıralaması + fifo_remaining ───────

def test_detail_sort_and_fifo_remaining(client, auth_headers, db, upload):
    today = date.today()
    v = _mk_vendor(db, "Detay Sıralama Cari")
    _mk_tx(db, v, upload, today - timedelta(days=20), alacak=10000, due=today + timedelta(days=10))
    _mk_tx(db, v, upload, today - timedelta(days=10), alacak=8000, due=today + timedelta(days=20))
    _mk_tx(db, v, upload, today - timedelta(days=5), borc=12000)
    db.commit()

    # alacak DESC → 10000 ilk satır
    r = client.get(f"{C}/vendors/{v.id}?sort_by=alacak&sort_dir=desc", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()["transactions"]["items"]
    assert items[0]["alacak"] == 10000.0

    # fifo_remaining: FIFO 12000 ödemeyle ilk fatura kapanır, ikinciden 6000 kalır
    by_alacak = {i["alacak"]: i for i in items if i["alacak"] > 0}
    assert by_alacak[10000.0]["fifo_remaining"] == 0.0
    assert by_alacak[8000.0]["fifo_remaining"] == 6000.0
    # Ödeme satırında fifo_remaining None
    pay_rows = [i for i in items if i["borc"] > 0]
    assert pay_rows and pay_rows[0]["fifo_remaining"] is None

    # Varsayılan sıralama korunur (tarih DESC) — regresyon
    r2 = client.get(f"{C}/vendors/{v.id}", headers=auth_headers)
    d2 = r2.json()["transactions"]["items"]
    assert d2[0]["date"] >= d2[-1]["date"]

    # Geçersiz sort_by → 422
    assert client.get(f"{C}/vendors/{v.id}?sort_by=hacked",
                      headers=auth_headers).status_code == 422
