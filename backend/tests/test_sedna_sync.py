"""Merkezi Sedna senkronizasyonu (orchestrator) testleri.

Tüm fetch'ler mock'lanır (tünel/CI bağımsız). settings.sedna_password patch'lenerek
sedna_configured() True yapılır. Adım-bazlı izin + izolasyon doğrulanır.

Faz 2 #18 (2026-07-12): POST /sync-all artık ARKA PLANDA koşar ve hemen
{started, total, steps} döner — adım-sonuç doğrulamaları senkron çekirdek
`run_sync_all_steps`'i DOĞRUDAN çağırır (davranış çekirdekte birebir korunuyor);
endpoint testi yalnız yanıt şekli + 403/503 doğrular.
"""
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text

from app.config import settings
from app.models.role import Role
from app.models.user import User
from app.routers.finance import sedna_sync
from app.routers.finance.sedna_sync import run_sync_all_steps
from app.utils.security import hash_password

PREFIX = "/api/finance/sedna"
CARI = "app.routers.finance.cariler.sedna_import"
CHK = "app.routers.finance.check_import"

ALL_STEP_KEYS = {"cariler", "ibans", "checks", "sales_invoices",
                 "recurring_sync", "stock", "reservations", "bank_recon"}

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


def _admin(db):
    admin = db.query(User).filter(User.username == "admin").first()
    assert admin is not None
    return admin


def _no_perm_user(db):
    """Hiçbir modül izni olmayan kullanıcı nesnesi (login gerekmez — çekirdek doğrudan çağrılır)."""
    role = Role(name=f"syncnoperm_{uuid4().hex[:8]}", description="izinsiz", is_active=True)
    db.add(role)
    db.flush()
    user = User(
        username=f"syncnp_{uuid4().hex[:8]}", email=f"snp{uuid4().hex[:8]}@test.local",
        first_name="Sync", last_name="İzinsiz",
        hashed_password=hash_password("Test1234!"), role_id=role.id, is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def test_status_requires_auth(client):
    assert client.get(f"{PREFIX}/status").status_code == 401


def test_status_admin_all_allowed(client, auth_headers):
    with patch.object(settings, "sedna_password", "testpw"):
        r = client.get(f"{PREFIX}/status", headers=auth_headers)
        assert r.status_code == 200
        j = r.json()
        assert j["configured"] is True and j["any_allowed"] is True
        assert {s["key"] for s in j["steps"]} == ALL_STEP_KEYS
        assert all(s["allowed"] for s in j["steps"])  # admin hepsini yapabilir


def test_sync_all_not_configured_503(client, auth_headers):
    with patch.object(settings, "sedna_password", ""):
        assert client.post(f"{PREFIX}/sync-all", headers=auth_headers).status_code == 503


def test_sync_all_endpoint_returns_started_shape(client, auth_headers):
    """POST /sync-all artık hemen döner: {started, total, steps} (arka plan işi nötrlenir —
    gerçek adımlar test DB'sine kendi SessionLocal'iyle yazmasın)."""
    with patch.object(settings, "sedna_password", "testpw"), \
         patch.object(sedna_sync, "_run_sync_all_job", lambda uid, ip: None):
        r = client.post(f"{PREFIX}/sync-all", headers=auth_headers)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["started"] is True
        assert j["total"] == len(ALL_STEP_KEYS)
        assert {s["key"] for s in j["steps"]} == ALL_STEP_KEYS
        assert all(set(s.keys()) == {"key", "label"} for s in j["steps"])


def test_sync_all_endpoint_403_when_no_step_permitted(client, viewer_user_headers):
    """Yalnız view izni olan kullanıcı → hiçbir 'use' adımı yok → 403."""
    with patch.object(settings, "sedna_password", "testpw"), \
         patch.object(sedna_sync, "_run_sync_all_job", lambda uid, ip: None):
        r = client.post(f"{PREFIX}/sync-all", headers=viewer_user_headers)
        assert r.status_code == 403


def test_run_sync_all_steps_runs_all(db):
    """Senkron çekirdek tüm izinli adımları sırayla koşar (eski endpoint davranışı
    birebir çekirdekte — aynı patch'ler, aynı DB etkisi doğrulaması)."""
    with patch.object(settings, "sedna_password", "testpw"), \
         patch(f"{CARI}.fetch_cari_transactions", return_value=FAKE_CARI), \
         patch(f"{CARI}.fetch_vendor_ibans", return_value=FAKE_IBAN), \
         patch(f"{CHK}.fetch_issued_checks", return_value=FAKE_CHECK), \
         patch("app.routers.finance.sales_invoices.fetch_sales_invoices",
               return_value={"invoices": [], "collections": []}), \
         patch("app.services.stock_service.fetch_stock_depots", return_value=[]), \
         patch("app.services.stock_service.fetch_stock_products", return_value=[]), \
         patch("app.services.stock_service.fetch_stock_movements", return_value=[]), \
         patch("app.services.reservation_service.fetch_reservations", return_value=[]), \
         patch("app.utils.sedna_client.fetch_bank_ledger_rows", return_value=[]), \
         patch("app.utils.sedna_client.fetch_bank_ledger_max_dates", return_value={}):
        j = run_sync_all_steps(db, _admin(db), "test")

        assert j["ok_count"] == 8 and j["total"] == 8
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
        assert by["bank_recon"]["ok"]       # banka ↔ Sedna mutabakat taraması
        assert "hesap" in by["bank_recon"]["summary"]

        # DB etkisi: cari + IBAN + çek oluştu (sıralı çalıştı → IBAN cariye bağlandı)
        vid = db.execute(text("SELECT id FROM vendors WHERE hesap_kodu='320.88.01.0001'")).scalar()
        assert vid is not None
        assert db.execute(text("SELECT count(*) FROM vendor_bank_accounts WHERE vendor_id=:v"), {"v": vid}).scalar() == 1
        assert db.execute(text("SELECT count(*) FROM checks WHERE check_no='SYNCHK1'")).scalar() == 1


def test_run_sync_all_steps_skips_unpermitted(db):
    """İzinsiz kullanıcı → tüm 'use' adımları atlanır (Yetki yok), hiçbir run çağrılmaz."""
    with patch.object(settings, "sedna_password", "testpw"), \
         patch(f"{CARI}.fetch_cari_transactions", return_value=FAKE_CARI), \
         patch(f"{CARI}.fetch_vendor_ibans", return_value=FAKE_IBAN), \
         patch(f"{CHK}.fetch_issued_checks", return_value=FAKE_CHECK):
        j = run_sync_all_steps(db, _no_perm_user(db), "test")
        assert j["ok_count"] == 0
        assert all(s["skipped"] and s["summary"] == "Yetki yok" for s in j["steps"])
