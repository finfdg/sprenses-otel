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


# ─── Toplu not listesi (Notlar sekmesi kartı) ────────────

@pytest.fixture
def two_vendors_with_notes(client, auth_headers, db):
    """İki cari + üç not (biri yapıldı) — toplu liste testleri için."""
    v1 = Vendor(hesap_kodu="320.TNOT." + uuid.uuid4().hex[:6], hesap_adi="Toplu Not Cari Bir")
    v2 = Vendor(hesap_kodu="320.TNOT." + uuid.uuid4().hex[:6], hesap_adi="Toplu Not Cari İki")
    db.add_all([v1, v2])
    db.flush()
    n1 = client.post(f"{C}/vendors/{v1.id}/notes",
                     json={"text": "852.668,84 TL havale yapılacak"}, headers=auth_headers).json()
    n2 = client.post(f"{C}/vendors/{v2.id}/notes",
                     json={"text": "mutabakat farkı için çek listesi istendi"}, headers=auth_headers).json()
    n3 = client.post(f"{C}/vendors/{v2.id}/notes",
                     json={"text": "çek vadesi telefonla teyit edildi"}, headers=auth_headers).json()
    client.patch(f"{C}/vendors/{v2.id}/notes/{n3['id']}", json={"done": True}, headers=auth_headers)
    return {"v1": v1, "v2": v2, "n1": n1, "n2": n2, "n3": n3}


def test_all_notes_list_with_vendor_info(client, auth_headers, two_vendors_with_notes):
    d = two_vendors_with_notes
    r = client.get(f"{C}/notes", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # standart sayfalama metası + open_total
    assert {"items", "total", "page", "page_size", "pages", "open_total"} <= set(body.keys())
    ids = [i["id"] for i in body["items"]]
    assert d["n1"]["id"] in ids and d["n2"]["id"] in ids and d["n3"]["id"] in ids
    # firma bilgisi satırda
    item1 = next(i for i in body["items"] if i["id"] == d["n1"]["id"])
    assert item1["vendor_name"] == "Toplu Not Cari Bir"
    assert item1["vendor_code"] == d["v1"].hesap_kodu
    # en yeni en üstte (n3, n2'den sonra eklendi)
    assert ids.index(d["n3"]["id"]) < ids.index(d["n1"]["id"])
    # open_total yapılmış notu saymaz
    assert body["open_total"] >= 2


def test_all_notes_done_filter(client, auth_headers, two_vendors_with_notes):
    d = two_vendors_with_notes
    open_ids = [i["id"] for i in
                client.get(f"{C}/notes?done=false", headers=auth_headers).json()["items"]]
    assert d["n1"]["id"] in open_ids and d["n2"]["id"] in open_ids
    assert d["n3"]["id"] not in open_ids
    done_ids = [i["id"] for i in
                client.get(f"{C}/notes?done=true", headers=auth_headers).json()["items"]]
    assert d["n3"]["id"] in done_ids and d["n1"]["id"] not in done_ids


def test_all_notes_search_text_and_vendor(client, auth_headers, two_vendors_with_notes):
    d = two_vendors_with_notes
    # not metninde arama
    hits = [i["id"] for i in
            client.get(f"{C}/notes?search=havale", headers=auth_headers).json()["items"]]
    assert d["n1"]["id"] in hits and d["n2"]["id"] not in hits
    # firma adında arama — o carinin tüm notları döner
    hits2 = [i["id"] for i in
             client.get(f"{C}/notes?search=Cari İki", headers=auth_headers).json()["items"]]
    assert d["n2"]["id"] in hits2 and d["n3"]["id"] in hits2 and d["n1"]["id"] not in hits2
    # cari kodunda arama
    hits3 = [i["id"] for i in
             client.get(f"{C}/notes?search={d['v1'].hesap_kodu}", headers=auth_headers).json()["items"]]
    assert hits3 == [d["n1"]["id"]]


def test_all_notes_pagination(client, auth_headers, two_vendors_with_notes):
    r = client.get(f"{C}/notes?page=1&page_size=2", headers=auth_headers).json()
    assert len(r["items"]) == 2 and r["page_size"] == 2
    assert r["pages"] >= 2 and r["total"] >= 3


def test_all_notes_view_permission(client, viewer_user_headers, two_vendors_with_notes):
    # salt-okuma GET — view yeterli
    assert client.get(f"{C}/notes", headers=viewer_user_headers).status_code == 200
    # auth'suz erişim yasak (login fixture'ının cookie'si temizlenir)
    client.cookies.clear()
    assert client.get(f"{C}/notes").status_code == 401


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
    """Vadesi Geçmiş = NET (FIFO) ödenmemiş+gecikmiş tutar — brüt fatura toplamı DEĞİL.

    Ödemeler en eski faturalardan düşülür (FIFO); geriye kalan gecikmiş kısım raporlanır.
    """
    upload = VendorUpload(file_name="s.xlsx", file_url="/tmp/s.xlsx", uploaded_by=1,
                          total_vendors=1, total_transactions=0, new_transactions=0,
                          skipped_transactions=0)
    db.add(upload)
    db.flush()
    v = Vendor(hesap_kodu="320.SUM." + uuid.uuid4().hex[:6], hesap_adi="Özet Cari")
    db.add(v)
    db.flush()

    today = date.today()

    def mk(d, borc, alacak, due=None, match=None, tag=""):
        db.add(VendorTransaction(
            vendor_id=v.id, upload_id=upload.id, date=d, borc=borc, alacak=alacak,
            payment_due_date=due, match_number=match, bakiye=0,
            tx_hash=uuid.uuid4().hex, description=tag,
        ))

    # Faturalar (alacak): A ve B vadesi geçmiş, C gelecekte
    mk(today - timedelta(days=25), 0, 10000, due=today - timedelta(days=20))  # A
    mk(today - timedelta(days=10), 0, 8000, due=today - timedelta(days=5))    # B
    mk(today, 0, 5000, due=today + timedelta(days=30))                        # C (gelecek)
    # Ödemeler (borç) toplam 12000 → net borç = 23000 - 12000 = 11000
    mk(today - timedelta(days=25), 3000, 0)
    mk(today - timedelta(days=2), 9000, 0)  # son ödeme
    db.commit()

    # FIFO: 12000 ödeme en eskiyi (A=10000) tam, B'nin 2000'ini kapatır →
    #   kalan ödenmemiş: B=6000 (vadesi geçmiş) + C=5000 (gelecek).
    #   Vadesi geçmiş NET = 6000 (brüt olsa 10000+8000 = 18000 olurdu).
    detail = client.get(f"{C}/vendors/{v.id}", headers=auth_headers).json()["vendor"]
    assert detail["overdue"] == 6000.0
    assert detail["overdue_count"] == 1
    assert detail["last_payment_amount"] == 9000.0
    assert detail["last_payment_date"] == (today - timedelta(days=2)).isoformat()


def test_overdue_is_net_capped_by_balance(client, auth_headers, db):
    """Regresyon: çok sayıda geçmiş-vadeli fatura + ödemeler → overdue NET bakiyeyle sınırlı.

    Kullanıcı bulgusu (2026-07-06): eski brüt hesap net bakiyeden kat kat büyük çıkıyordu
    (ör. brüt 300K'ya karşı gerçek net borç 50K). Overdue artık net borcu aşamaz.
    """
    upload = VendorUpload(file_name="s.xlsx", file_url="/tmp/s.xlsx", uploaded_by=1,
                          total_vendors=1, total_transactions=0, new_transactions=0,
                          skipped_transactions=0)
    db.add(upload)
    db.flush()
    v = Vendor(hesap_kodu="320.CAP." + uuid.uuid4().hex[:6], hesap_adi="Kapak Cari")
    db.add(v)
    db.flush()
    today = date.today()

    def mk(d, borc, alacak, due=None):
        db.add(VendorTransaction(
            vendor_id=v.id, upload_id=upload.id, date=d, borc=borc, alacak=alacak,
            payment_due_date=due, match_number=None, bakiye=0, tx_hash=uuid.uuid4().hex,
        ))

    # 3 geçmiş-vadeli fatura × 100000 = 300000 brüt; ödemeler 250000 → net borç 50000
    mk(today - timedelta(days=40), 0, 100000, due=today - timedelta(days=30))
    mk(today - timedelta(days=30), 0, 100000, due=today - timedelta(days=20))
    mk(today - timedelta(days=20), 0, 100000, due=today - timedelta(days=10))
    mk(today - timedelta(days=15), 250000, 0)
    db.commit()

    detail = client.get(f"{C}/vendors/{v.id}", headers=auth_headers).json()["vendor"]
    assert detail["bakiye"] == -50000.0
    assert detail["overdue"] == 50000.0  # brüt 300000 DEĞİL — net borçla sınırlı
    assert detail["overdue_count"] == 1


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
    # C: vadesi geçmiş fatura ama ödemeyle tam kapanmış (net 0) → overdue'da OLMAMALI (net FIFO)
    vc = Vendor(hesap_kodu=f"320.OC.{tag}", hesap_adi="Odenmis Cari")
    db.add(vc); db.flush()
    db.add(VendorTransaction(vendor_id=vc.id, upload_id=upload.id, date=past,
                             borc=0, alacak=7000, payment_due_date=past,
                             match_number=None, bakiye=0, tx_hash=uuid.uuid4().hex))
    db.add(VendorTransaction(vendor_id=vc.id, upload_id=upload.id, date=past,
                             borc=7000, alacak=0, payment_due_date=None,
                             match_number=None, bakiye=0, tx_hash=uuid.uuid4().hex))
    db.commit()

    r = client.get("/api/finance/cariler/vendors?overdue_only=true&page_size=500", headers=auth_headers)
    assert r.status_code == 200
    codes = {it["hesap_kodu"] for it in r.json()["items"]}
    assert f"320.OA.{tag}" in codes
    assert f"320.OB.{tag}" not in codes
    assert f"320.OC.{tag}" not in codes
