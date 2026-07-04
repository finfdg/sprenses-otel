"""Cari notları + iletişim bilgileri + özet kart metrikleri testleri.

Cariler yeniden tasarımı (2026-07-04, "Sprenses Tasarımlar"):
- Notlar CRUD (ekle/listele/güncelle/yapıldı/sil) — onaydan muaf, use + audit + broadcast
- Firma iletişim güncelleme (yetkili/telefon/e-posta)
- Cari detay özet kartları: vadesi geçmiş + son ödeme
"""
import uuid
from datetime import date, timedelta

import pytest

from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload

C = "/api/finance/cariler"


@pytest.fixture
def vendor(db):
    v = Vendor(hesap_kodu="320.NOTE." + uuid.uuid4().hex[:6], hesap_adi="Not Test Cari")
    db.add(v)
    db.flush()
    return v.id


# ─── Notlar CRUD ─────────────────────────────────────────

def test_note_create_list_update_toggle_delete(client, auth_headers, vendor):
    # başlangıçta boş
    r0 = client.get(f"{C}/vendors/{vendor}/notes", headers=auth_headers)
    assert r0.status_code == 200 and r0.json() == []

    # ekle
    r = client.post(f"{C}/vendors/{vendor}/notes",
                    json={"text": "Ödeme sözü alındı 12 Temmuz"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    note = r.json()
    assert note["text"] == "Ödeme sözü alındı 12 Temmuz"
    assert note["done"] is False
    assert note["author_name"]  # snapshot dolu

    # listede görünür
    lst = client.get(f"{C}/vendors/{vendor}/notes", headers=auth_headers).json()
    assert len(lst) == 1 and lst[0]["id"] == note["id"]

    # metin güncelle
    u = client.patch(f"{C}/vendors/{vendor}/notes/{note['id']}",
                     json={"text": "Güncellendi"}, headers=auth_headers)
    assert u.status_code == 200 and u.json()["text"] == "Güncellendi"

    # yapıldı işaretle
    t = client.patch(f"{C}/vendors/{vendor}/notes/{note['id']}",
                     json={"done": True}, headers=auth_headers)
    assert t.status_code == 200 and t.json()["done"] is True

    # sil
    d = client.delete(f"{C}/vendors/{vendor}/notes/{note['id']}", headers=auth_headers)
    assert d.status_code == 200 and d.json()["ok"] is True
    assert client.get(f"{C}/vendors/{vendor}/notes", headers=auth_headers).json() == []


def test_note_newest_first(client, auth_headers, vendor):
    ids = []
    for txt in ["ilk", "ikinci", "üçüncü"]:
        ids.append(client.post(f"{C}/vendors/{vendor}/notes", json={"text": txt},
                               headers=auth_headers).json()["id"])
    lst = client.get(f"{C}/vendors/{vendor}/notes", headers=auth_headers).json()
    # en yeni en üstte
    assert lst[0]["id"] == ids[-1]


def test_note_empty_text_rejected(client, auth_headers, vendor):
    assert client.post(f"{C}/vendors/{vendor}/notes", json={"text": "   "},
                       headers=auth_headers).status_code == 400


def test_note_vendor_404(client, auth_headers):
    assert client.get(f"{C}/vendors/999999/notes", headers=auth_headers).status_code == 404
    assert client.post(f"{C}/vendors/999999/notes", json={"text": "x"},
                       headers=auth_headers).status_code == 404


def test_note_missing_404(client, auth_headers, vendor):
    assert client.patch(f"{C}/vendors/{vendor}/notes/999999", json={"done": True},
                        headers=auth_headers).status_code == 404
    assert client.delete(f"{C}/vendors/{vendor}/notes/999999",
                         headers=auth_headers).status_code == 404


def test_note_requires_use(client, viewer_user_headers, vendor):
    # görüntüleme serbest
    assert client.get(f"{C}/vendors/{vendor}/notes", headers=viewer_user_headers).status_code == 200
    # yazma yasak (use gerekli)
    assert client.post(f"{C}/vendors/{vendor}/notes", json={"text": "x"},
                       headers=viewer_user_headers).status_code == 403


# ─── İletişim bilgileri ──────────────────────────────────

def test_contact_update_and_reflected_in_detail(client, auth_headers, vendor):
    r = client.patch(f"{C}/vendors/{vendor}/contact",
                     json={"contact_person": "Ahmet Yılmaz", "phone": "0212 555 41 20",
                           "email": "muhasebe@test.com"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["contact_person"] == "Ahmet Yılmaz"

    detail = client.get(f"{C}/vendors/{vendor}", headers=auth_headers).json()["vendor"]
    assert detail["contact_person"] == "Ahmet Yılmaz"
    assert detail["phone"] == "0212 555 41 20"
    assert detail["email"] == "muhasebe@test.com"

    # boş string → None (temizleme)
    client.patch(f"{C}/vendors/{vendor}/contact", json={"phone": ""}, headers=auth_headers)
    detail2 = client.get(f"{C}/vendors/{vendor}", headers=auth_headers).json()["vendor"]
    assert detail2["phone"] is None
    assert detail2["contact_person"] == "Ahmet Yılmaz"  # dokunulmayan alan korunur


def test_contact_requires_use(client, viewer_user_headers, vendor):
    assert client.patch(f"{C}/vendors/{vendor}/contact", json={"phone": "1"},
                        headers=viewer_user_headers).status_code == 403


# ─── Özet kart metrikleri (overdue + son ödeme) ──────────

def test_detail_summary_metrics(client, auth_headers, db):
    upload = VendorUpload(file_name="s.xlsx", file_url="/tmp/s.xlsx", uploaded_by=1,
                          total_vendors=1, total_transactions=0, new_transactions=0,
                          skipped_transactions=0)
    db.add(upload)
    db.flush()
    v = Vendor(hesap_kodu="320.SUM." + uuid.uuid4().hex[:6], hesap_adi="Özet Cari")
    db.add(v)
    db.flush()

    today = date.today()
    past = today - timedelta(days=10)
    future = today + timedelta(days=30)

    def mk(d, borc, alacak, due=None, match=None, tag=""):
        db.add(VendorTransaction(
            vendor_id=v.id, upload_id=upload.id, date=d, borc=borc, alacak=alacak,
            payment_due_date=due, match_number=match, bakiye=0,
            tx_hash=uuid.uuid4().hex, description=tag,
        ))

    # vadesi geçmiş eşleşmemiş fatura → overdue'ya girer
    mk(past, 0, 18600, due=past)
    # vadesi gelecekte → overdue DEĞİL
    mk(today, 0, 5000, due=future)
    # vadesi geçmiş ama eşleşmiş (ödenmiş) → overdue DEĞİL
    mk(past, 0, 2000, due=past, match=55)
    # ödeme (borç) kayıtları → son ödeme en yenisi
    mk(today - timedelta(days=20), 8500, 0)
    mk(today - timedelta(days=2), 12000, 0)
    db.commit()

    detail = client.get(f"{C}/vendors/{v.id}", headers=auth_headers).json()["vendor"]
    assert detail["overdue"] == 18600.0
    assert detail["overdue_count"] == 1
    assert detail["last_payment_amount"] == 12000.0
    assert detail["last_payment_date"] == (today - timedelta(days=2)).isoformat()


# ─── Liste overdue_only filtresi (master-detail "Vadesi Geçmiş" çipi) ─────

def test_list_overdue_only_filter(client, auth_headers, db):
    upload = VendorUpload(file_name="s.xlsx", file_url="/tmp/s.xlsx", uploaded_by=1,
                          total_vendors=1, total_transactions=0, new_transactions=0,
                          skipped_transactions=0)
    db.add(upload)
    db.flush()
    today = date.today()
    past = today - timedelta(days=5)
    future = today + timedelta(days=30)
    tag = uuid.uuid4().hex[:6]

    # A: vadesi geçmiş eşleşmemiş fatura → overdue listesinde OLMALI
    va = Vendor(hesap_kodu=f"320.OA.{tag}", hesap_adi="Overdue Cari")
    db.add(va); db.flush()
    db.add(VendorTransaction(vendor_id=va.id, upload_id=upload.id, date=past,
                             borc=0, alacak=9000, payment_due_date=past,
                             match_number=None, bakiye=0, tx_hash=uuid.uuid4().hex))
    # B: yalnız gelecekte vadeli fatura → overdue listesinde OLMAMALI
    vb = Vendor(hesap_kodu=f"320.OB.{tag}", hesap_adi="Guncel Cari")
    db.add(vb); db.flush()
    db.add(VendorTransaction(vendor_id=vb.id, upload_id=upload.id, date=today,
                             borc=0, alacak=5000, payment_due_date=future,
                             match_number=None, bakiye=0, tx_hash=uuid.uuid4().hex))
    db.commit()

    r = client.get("/api/finance/cariler/vendors?overdue_only=true&page_size=500", headers=auth_headers)
    assert r.status_code == 200
    codes = {it["hesap_kodu"] for it in r.json()["items"]}
    assert f"320.OA.{tag}" in codes
    assert f"320.OB.{tag}" not in codes
