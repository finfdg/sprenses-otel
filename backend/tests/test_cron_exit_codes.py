"""Zamanlanmış iş (cron) çıkış-kodu sözleşmesi testleri — denetim JOBS-002.

BULGU: sedna-sync, sales-sync ve exchange-rates cron'ları bir adım hata verse de
`exit 0` dönüyordu → systemd `oneshot` birimi 'başarılı' sayıyor → `OnFailure=`
alarmı (DR-003 drop-in'leri) hiç tetiklenmiyordu.

KAPANIŞ KRİTERİ: bilerek bozulmuş bir adımda `main()` sıfırdan-farklı
(EXIT_PARTIAL) döner → birim 'failed' olur → OnFailure drop-in'i alarmı tetikler.
Bu testler hem çıkış kodunu hem de OnFailure bağlantısını doğrular.

Regresyon: düzeltme geri alınırsa (main'ler tekrar `return 0` / `sys.exit(1)`
yaparsa) aşağıdaki broken-step testleri kırmızıya döner.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from cron_exit_codes import (
    EXIT_FATAL,
    EXIT_OK,
    EXIT_PARTIAL,
    exit_code_for_steps,
)


# ── Saf yardımcı: çıkış-kodu eşleme ─────────────────────────────────────
def test_exit_code_started_false_is_fatal():
    assert exit_code_for_steps(started=False, failed_steps=0) == EXIT_FATAL


def test_exit_code_failed_steps_is_partial():
    assert exit_code_for_steps(started=True, failed_steps=1) == EXIT_PARTIAL
    assert exit_code_for_steps(started=True, failed_steps=5) == EXIT_PARTIAL


def test_exit_code_all_ok_is_zero():
    assert exit_code_for_steps(started=True, failed_steps=0) == EXIT_OK


def test_exit_codes_are_distinct_and_signal_failure():
    # OK sıfır olmalı; hata kodları sıfırdan farklı VE birbirinden ayrı olmalı
    assert EXIT_OK == 0
    assert EXIT_FATAL != 0 and EXIT_PARTIAL != 0
    assert EXIT_FATAL != EXIT_PARTIAL


# ── sedna-sync cron: adım-izolasyonlu döngü ─────────────────────────────
def _sedna_step(run):
    return {"key": "cariler", "label": "TEST ADIM", "module": "finance.cariler",
            "run": run, "broadcast": None}


def _patch_sedna(steps):
    """sedna cron main()'i izole çalıştırmak için ortak yamalar."""
    import cron_sedna_sync
    from app.config import settings
    from app.routers.finance import sedna_sync as ss
    return [
        patch.object(settings, "sedna_password", "testpw"),
        patch.object(ss, "_STEPS", steps),
        patch.object(ss, "_summarize", lambda k, d: "ok"),
        patch.object(cron_sedna_sync, "_maybe_notify_aging", lambda d: None),
    ]


def test_sedna_broken_step_returns_partial(db):
    """KAPANIŞ KRİTERİ: bilerek bozulmuş adım → main() EXIT_PARTIAL döner."""
    import cron_sedna_sync

    def boom(db_, user, ip):
        raise RuntimeError("bilerek bozuldu")

    patches = _patch_sedna([_sedna_step(boom)])
    for p in patches:
        p.start()
    try:
        assert cron_sedna_sync.main() == EXIT_PARTIAL
    finally:
        for p in patches:
            p.stop()


def test_sedna_healthy_step_returns_ok(db):
    import cron_sedna_sync

    patches = _patch_sedna([_sedna_step(lambda db_, u, ip: {})])
    for p in patches:
        p.start()
    try:
        assert cron_sedna_sync.main() == EXIT_OK
    finally:
        for p in patches:
            p.stop()


def test_sedna_tunnel_closed_503_is_benign(db):
    """Tünel kapalı (HTTP 503) beklenen durum — timer'ı düşürmez (exit 0)."""
    import cron_sedna_sync

    def closed(db_, u, ip):
        raise HTTPException(status_code=503, detail="tünel kapalı")

    patches = _patch_sedna([_sedna_step(closed)])
    for p in patches:
        p.start()
    try:
        assert cron_sedna_sync.main() == EXIT_OK
    finally:
        for p in patches:
            p.stop()


def test_sedna_not_configured_returns_ok(db):
    import cron_sedna_sync
    from app.config import settings

    with patch.object(settings, "sedna_password", ""):
        assert cron_sedna_sync.main() == EXIT_OK


# ── sales-sync cron: tek adım ───────────────────────────────────────────
def test_sales_broken_step_returns_partial(db):
    """KAPANIŞ KRİTERİ: import beklenmeyen hata verirse → EXIT_PARTIAL."""
    import cron_sync_sales_invoices
    from app.routers.finance import sales_invoices as si

    def boom(db_, admin, ip):
        raise RuntimeError("bilerek bozuldu")

    with patch.object(si, "run_sales_invoice_import", boom):
        assert cron_sync_sales_invoices.main() == EXIT_PARTIAL


def test_sales_other_http_error_returns_partial(db):
    """503 dışı HTTP hatası GERÇEK başarısızlık → EXIT_PARTIAL (eskiden yanlışça 0'dı)."""
    import cron_sync_sales_invoices
    from app.routers.finance import sales_invoices as si

    def err(db_, admin, ip):
        raise HTTPException(status_code=500, detail="sunucu hatası")

    with patch.object(si, "run_sales_invoice_import", err):
        assert cron_sync_sales_invoices.main() == EXIT_PARTIAL


def test_sales_tunnel_closed_503_is_benign(db):
    import cron_sync_sales_invoices
    from app.routers.finance import sales_invoices as si

    def closed(db_, admin, ip):
        raise HTTPException(status_code=503, detail="tünel kapalı")

    with patch.object(si, "run_sales_invoice_import", closed):
        assert cron_sync_sales_invoices.main() == EXIT_OK


def test_sales_success_returns_ok(db):
    import cron_sync_sales_invoices
    from app.routers.finance import sales_invoices as si

    def ok(db_, admin, ip):
        return {"invoices_new": 0, "collections_new": 0, "advance_accounts": 0}

    with patch.object(si, "run_sales_invoice_import", ok):
        assert cron_sync_sales_invoices.main() == EXIT_OK


# ── exchange-rates cron ─────────────────────────────────────────────────
def test_exchange_fetch_error_returns_partial(db):
    """KAPANIŞ KRİTERİ: TCMB çekimi çökerse → EXIT_PARTIAL (eskiden sys.exit(1))."""
    import cron_fetch_exchange_rates as cx

    def boom(*a, **k):
        raise RuntimeError("TCMB bozuldu")

    with patch.object(sys, "argv", ["cron_fetch_exchange_rates.py"]), \
         patch.object(cx, "fetch_date_range", boom), \
         patch.object(cx, "fetch_rates_for_date_sync", boom), \
         patch.object(cx, "fetch_hourly_rates_sync", boom), \
         patch.object(cx, "fetch_today_rates_sync", boom):
        assert cx.main() == EXIT_PARTIAL


# ── OnFailure alarm bağlantısı (drop-in'ler) ────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DROPINS = _REPO_ROOT / "scripts" / "systemd" / "dropins"


@pytest.mark.parametrize("unit", [
    "sprenses-sedna-sync",
    "sprenses-sales-sync",
    "sprenses-exchange-rates",
])
def test_onfailure_dropin_wires_alarm(unit):
    """Non-zero çıkış kodu ancak OnFailure bağlıysa alarma dönüşür — drop-in şart."""
    conf = _DROPINS / f"{unit}-onfailure.conf"
    assert conf.exists(), f"{conf} yok — OnFailure alarmı bağlanmamış"
    assert "OnFailure=sprenses-alert@" in conf.read_text(encoding="utf-8")
