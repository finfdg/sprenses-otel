"""Cari — Sedna içe aktarma testleri (Sedna fetch mock'lanır; tünel/CI bağımsız).

Excel ile aynı upsert: vendor/tx oluşturma + payment_due + dedup (re-run → 0 yeni).
İzin + tünel-kapalı (503) + yapılandırılmamış (503) yolları.
"""
from datetime import date
from unittest.mock import patch

from sqlalchemy import text

from app.utils.sedna_client import SednaUnavailable

PREFIX = "/api/finance/cariler"
TARGET = "app.routers.finance.cariler.sedna_import"

FAKE_ROWS = [
    {"hesap_kodu": "320.99.01.0001", "hesap_adi": "TEST CARİ A", "tarih": date(2026, 1, 5),
     "evrak_no": "FT001", "islem_tipi": "Mal Alış Faturası", "fis_no": 1001,
     "aciklama": "test fatura", "borc": 0, "alacak": 1000, "pay_day": 0},
    {"hesap_kodu": "320.99.01.0001", "hesap_adi": "TEST CARİ A", "tarih": date(2026, 1, 10),
     "evrak_no": "TH001", "islem_tipi": "Kasa Tahsil Fişi", "fis_no": 1002,
     "aciklama": "odeme", "borc": 400, "alacak": 0, "pay_day": 0},
    {"hesap_kodu": "320.99.01.0002", "hesap_adi": "TEST CARİ B", "tarih": date(2026, 2, 1),
     "evrak_no": "FT002", "islem_tipi": "Mal Alış Faturası", "fis_no": 1003,
     "aciklama": "b fatura", "borc": 0, "alacak": 2500, "pay_day": 30},
]


def test_sedna_status_requires_view(client, no_perm_user_headers):
    assert client.get(f"{PREFIX}/sedna-status", headers=no_perm_user_headers).status_code == 403


def test_sedna_import_requires_use(client, viewer_user_headers):
    # viewer (yalnız view) → use gerektiren import 403 (izin dependency'si gövdeden önce)
    assert client.post(f"{PREFIX}/sedna-import", headers=viewer_user_headers).status_code == 403


def test_sedna_import_creates_and_dedups(client, auth_headers, db):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_cari_transactions", return_value=FAKE_ROWS):
        r = client.post(f"{PREFIX}/sedna-import", headers=auth_headers)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["total_transactions"] == 3
        assert j["new_transactions"] == 3
        assert j["total_vendors"] == 2

        v = db.execute(text("SELECT hesap_adi, payment_days FROM vendors WHERE hesap_kodu='320.99.01.0001'")).first()
        assert v and v[0] == "TEST CARİ A" and v[1] == 90      # pay_day 0 → varsayılan 90
        assert db.execute(text("SELECT payment_days FROM vendors WHERE hesap_kodu='320.99.01.0002'")).scalar() == 30
        # alacak hareketi payment_due_date almalı
        due = db.execute(text(
            "SELECT count(*) FROM vendor_transactions vt JOIN vendors v ON v.id=vt.vendor_id "
            "WHERE v.hesap_kodu='320.99.01.0001' AND vt.alacak>0 AND vt.payment_due_date IS NOT NULL"
        )).scalar()
        assert due == 1

        # RE-RUN → hepsi dedup (mükerrer yok)
        r2 = client.post(f"{PREFIX}/sedna-import", headers=auth_headers)
        j2 = r2.json()
        assert j2["new_transactions"] == 0 and j2["skipped_transactions"] == 3


def test_sedna_import_tunnel_down_503(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_cari_transactions", side_effect=SednaUnavailable("tünel kapalı")):
        assert client.post(f"{PREFIX}/sedna-import", headers=auth_headers).status_code == 503


def test_sedna_import_not_configured_503(client, auth_headers):
    with patch(f"{TARGET}.sedna_configured", return_value=False):
        assert client.post(f"{PREFIX}/sedna-import", headers=auth_headers).status_code == 503


def test_sedna_import_auto_sweeps_stale_rows(client, auth_headers, db):
    """Bayat-satır otomatik süpürme (2026-07-02): Sinyal A (Sedna Deleted=1) + Sinyal B
    (evrak tutar düzeltmesi) SİLİNİR; kanıtsız (elle/hard-delete, Sedna'da izi yok) satır KORUNUR."""
    from app.models.vendor import Vendor
    from app.models.vendor_transaction import VendorTransaction
    from app.models.vendor_upload import VendorUpload

    def row(evrak, borc=0, alacak=0):
        return {"hesap_kodu": "320.77.01.S001", "hesap_adi": "SÜPÜRME TEST",
                "tarih": date(2026, 5, 1), "evrak_no": evrak, "islem_tipi": None,
                "fis_no": None, "aciklama": f"ev{evrak}", "borc": borc, "alacak": alacak, "pay_day": 0}

    # Import 1: 5001=7.500, 6001=100, 7001=alacak 50
    imp1 = [row("5001", borc=7500), row("6001", borc=100), row("7001", alacak=50)]
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_cari_transactions", return_value=imp1), \
         patch(f"{TARGET}.fetch_cari_deleted_rows", return_value=[]):
        assert client.post(f"{PREFIX}/sedna-import", headers=auth_headers).status_code == 200

    v = db.query(Vendor).filter(Vendor.hesap_kodu == "320.77.01.S001").first()
    up = db.query(VendorUpload).order_by(VendorUpload.id.desc()).first()
    # Kanıtsız (elle eklenmiş) bayat satır — evrak Sedna'da HİÇ yok → süpürülmemeli
    amb = VendorTransaction(vendor_id=v.id, upload_id=up.id, date=date(2026, 5, 1),
                            evrak_no="9999", borc=999, alacak=0, bakiye=0,
                            tx_hash="manual-hash-xyz", match_number=None)
    db.add(amb); db.commit(); amb_id = amb.id

    # Import 2: 5001 tutarı 75.000'e düzeltildi (Sinyal B), 6001 SİLİNDİ (Sinyal A), 7001 aynı
    imp2 = [row("5001", borc=75000), row("7001", alacak=50)]
    deleted = [{"hesap_kodu": "320.77.01.S001", "tarih": date(2026, 5, 1),
                "evrak_no": "6001", "borc": 100, "alacak": 0}]
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_cari_transactions", return_value=imp2), \
         patch(f"{TARGET}.fetch_cari_deleted_rows", return_value=deleted):
        assert client.post(f"{PREFIX}/sedna-import", headers=auth_headers).status_code == 200

    db.expire_all()
    rows = db.query(VendorTransaction).filter(VendorTransaction.vendor_id == v.id).all()
    evraks = sorted(x.evrak_no for x in rows)
    assert evraks == ["5001", "7001", "9999"], f"eski 5001(7.500)+6001 süpürülmeli, 9999 kalmalı: {evraks}"
    assert [float(x.borc) for x in rows if x.evrak_no == "5001"][0] == 75000, "Doğru tutarlı 5001 kalmalı"
    assert any(x.id == amb_id for x in rows), "Kanıtsız (elle) satır KORUNMALI"
    assert sum(float(x.borc or 0) for x in rows) == 75000 + 999


# --- Sedna IBAN içe aktarma (dbo.Bank → vendor_bank_accounts) ---

FAKE_IBAN_ROWS = [
    {"hesap_kodu": "320.99.01.0001", "banka": "YAPIKREDİ",
     "iban": "TR13 0006 7010 0000 0049 3900 33", "unvan": "TEST CARİ A", "para_birimi": None},
    {"hesap_kodu": "320.99.01.0001", "banka": "GARANTİ",
     "iban": "TR060006200135900006297945", "unvan": "TEST CARİ A", "para_birimi": None},
    {"hesap_kodu": "320.99.01.0002", "banka": None,
     "iban": "TR120001001292910995125001", "unvan": "TEST CARİ B", "para_birimi": None},
    {"hesap_kodu": "320.99.99.9999", "banka": "X",  # caride YOK → atlanmalı
     "iban": "TR999999999999999999999999", "unvan": "YOK", "para_birimi": None},
]


def _seed_vendors(db):
    from app.models.vendor import Vendor
    for code, name in [("320.99.01.0001", "TEST CARİ A"), ("320.99.01.0002", "TEST CARİ B")]:
        db.add(Vendor(hesap_kodu=code, hesap_adi=name, payment_days=90))
    db.flush()


def test_sedna_iban_import_requires_use(client, viewer_user_headers):
    assert client.post(f"{PREFIX}/sedna-import-ibans", headers=viewer_user_headers).status_code == 403


def test_sedna_iban_import_creates_dedup_default(client, auth_headers, db):
    _seed_vendors(db)
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_vendor_ibans", return_value=FAKE_IBAN_ROWS):
        r = client.post(f"{PREFIX}/sedna-import-ibans", headers=auth_headers)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["total_fetched"] == 4
        assert j["new_ibans"] == 3
        assert j["vendors_matched"] == 2
        assert j["skipped_no_vendor"] == 1          # carisiz satır atlandı

        # cari A: 2 IBAN, biri varsayılan, IBAN normalize (boşluksuz)
        rows = db.execute(text(
            "SELECT vba.iban, vba.bank_name, vba.is_default FROM vendor_bank_accounts vba "
            "JOIN vendors v ON v.id=vba.vendor_id WHERE v.hesap_kodu='320.99.01.0001' "
            "ORDER BY vba.is_default DESC, vba.sort_order"
        )).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "TR130006701000000049390033" and rows[0][2] is True   # ilk = varsayılan, normalize
        assert rows[1][2] is False                                                  # 2.si varsayılan değil
        assert {x[1] for x in rows} == {"YAPIKREDİ", "GARANTİ"}

        # RE-RUN → mükerrer yok
        j2 = client.post(f"{PREFIX}/sedna-import-ibans", headers=auth_headers).json()
        assert j2["new_ibans"] == 0 and j2["skipped_existing"] == 3


def test_sedna_iban_import_fills_empty_bank_name(client, auth_headers, db):
    from app.models.vendor import Vendor
    from app.models.vendor_bank_account import VendorBankAccount
    v = Vendor(hesap_kodu="320.99.01.0001", hesap_adi="TEST CARİ A", payment_days=90)
    db.add(v)
    db.flush()
    # banka adı BOŞ mevcut IBAN (örn. elle eklenmiş)
    db.add(VendorBankAccount(vendor_id=v.id, bank_name=None,
                             iban="TR130006701000000049390033", is_default=True, sort_order=0))
    db.flush()
    with patch(f"{TARGET}.sedna_configured", return_value=True), \
         patch(f"{TARGET}.fetch_vendor_ibans", return_value=FAKE_IBAN_ROWS[:1]):  # aynı IBAN, banka=YAPIKREDİ
        j = client.post(f"{PREFIX}/sedna-import-ibans", headers=auth_headers).json()
        assert j["new_ibans"] == 0 and j["updated"] == 1
        assert db.execute(text(
            "SELECT bank_name FROM vendor_bank_accounts WHERE iban='TR130006701000000049390033'"
        )).scalar() == "YAPIKREDİ"
