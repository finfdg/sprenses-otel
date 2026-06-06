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
