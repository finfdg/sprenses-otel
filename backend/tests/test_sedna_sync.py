"""Merkezi Sedna senkronizasyonu (orchestrator) testleri.

Tüm fetch'ler mock'lanır (tünel/CI bağımsız). settings.sedna_password patch'lenerek
sedna_configured() True yapılır. Adım-bazlı izin + izolasyon doğrulanır.
"""
from datetime import date
from unittest.mock import patch

from sqlalchemy import text

from app.config import settings

PREFIX = "/api/finance/sedna"
CARI = "app.routers.finance.cariler.sedna_import"
CHK = "app.routers.finance.check_import"

FAKE_CARI = [
    {"hesap_kodu": "320.88.01.0001", "hesap_adi": "SYNC CARİ A", "tarih": date(2026, 1, 5),
     "evrak_no": "FT900", "islem_tipi": "Mal Alış Faturası", "fis_no": 9001,
     "aciklama": "x", "borc": 0, "alacak": 5000, "pay_day": 0},
]
FAKE_IBAN = [
    {"hesap_kodu": "320.88.01.0001", "banka": "YAPIKREDİ",
     "iban": "TR880006701000000099887766", "unvan": "SYNC CARİ A", "para_birimi": None},
]
FAKE_CHECK = [
    {"vendor_code": "320.88.01.0001", "vendor_name": "SYNC CARİ A", "check_no": "SYNCHK1",
     "bank": "YAPIKREDİ", "city": None, "due_date": date(2026, 9, 1),
     "amount_tl": 5000, "currency": "TL", "amount_currency": 5000, "max_pos": 100},
]


def test_status_requires_auth(client):
    assert client.get(f"{PREFIX}/status").status_code == 401


def test_status_admin_all_allowed(client, auth_headers):
    with patch.object(settings, "sedna_password", "testpw"):
        r = client.get(f"{PREFIX}/status", headers=auth_headers)
        assert r.status_code == 200
        j = r.json()
        assert j["configured"] is True and j["any_allowed"] is True
        assert {s["key"] for s in j["steps"]} == {"cariler", "ibans", "checks", "sales_invoices",
                                                   "recurring_sync", "stock", "reservations"}
        assert all(s["allowed"] for s in j["steps"])  # admin hepsini yapabilir


def test_sync_all_not_configured_503(client, auth_headers):
    with patch.object(settings, "sedna_password", ""):
        assert client.post(f"{PREFIX}/sync-all", headers=auth_headers).status_code == 503


def test_sync_all_runs_all_steps(client, auth_headers, db):
    with patch.object(settings, "sedna_password", "testpw"), \
         patch(f"{CARI}.fetch_cari_transactions", return_value=FAKE_CARI), \
         patch(f"{CARI}.fetch_vendor_ibans", return_value=FAKE_IBAN), \
         patch(f"{CHK}.fetch_issued_checks", return_value=FAKE_CHECK), \
         patch("app.routers.finance.sales_invoices.fetch_sales_invoices",
               return_value={"invoices": [], "collections": []}), \
         patch("app.services.stock_service.fetch_stock_depots", return_value=[]), \
         patch("app.services.stock_service.fetch_stock_products", return_value=[]), \
         patch("app.services.stock_service.fetch_stock_movements", return_value=[]), \
         patch("app.services.reservation_service.fetch_reservations", return_value=[]):
        r = client.post(f"{PREFIX}/sync-all", headers=auth_headers)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok_count"] == 7 and j["total"] == 7
        by = {s["key"]: s for s in j["steps"]}
        assert by["cariler"]["ok"] and by["ibans"]["ok"] and by["checks"]["ok"] and by["sales_invoices"]["ok"]
        assert by["recurring_sync"]["ok"]  # cari adımından sonra türetilen senkron
        assert by["stock"]["ok"]            # stok içe aktarma adımı
        assert by["reservations"]["ok"]     # önbüro rezervasyon içe aktarma adımı
        assert "hareket" in by["cariler"]["summary"]
        assert "IBAN" in by["ibans"]["summary"]
        assert "çek" in by["checks"]["summary"]
        assert "fatura" in by["sales_invoices"]["summary"]
        assert "senkron" in by["recurring_sync"]["summary"]
        assert "depo" in by["stock"]["summary"]
        assert "yeni" in by["reservations"]["summary"]

        # DB etkisi: cari + IBAN + çek oluştu (sıralı çalıştı → IBAN cariye bağlandı)
        vid = db.execute(text("SELECT id FROM vendors WHERE hesap_kodu='320.88.01.0001'")).scalar()
        assert vid is not None
        assert db.execute(text("SELECT count(*) FROM vendor_bank_accounts WHERE vendor_id=:v"), {"v": vid}).scalar() == 1
        assert db.execute(text("SELECT count(*) FROM checks WHERE check_no='SYNCHK1'")).scalar() == 1


def test_sync_all_skips_unpermitted(client, viewer_user_headers):
    """Yalnız view izni olan kullanıcı → tüm 'use' adımları atlanır (Yetki yok)."""
    with patch.object(settings, "sedna_password", "testpw"), \
         patch(f"{CARI}.fetch_cari_transactions", return_value=FAKE_CARI), \
         patch(f"{CARI}.fetch_vendor_ibans", return_value=FAKE_IBAN), \
         patch(f"{CHK}.fetch_issued_checks", return_value=FAKE_CHECK):
        r = client.post(f"{PREFIX}/sync-all", headers=viewer_user_headers)
        assert r.status_code == 200
        j = r.json()
        assert j["ok_count"] == 0
        assert all(s["skipped"] and s["summary"] == "Yetki yok" for s in j["steps"])
