#!/usr/bin/env python3
"""Cari + çek + düzenli-ödeme + rezervasyon + banka-mutabakat Sedna senkron cronu (Faz 2 #18).

Merkezi Sedna senkronunun ÇEKİRDEK finans adımlarını admin kullanıcısıyla koşar:
cariler, ibans, checks, recurring_sync, salary_sync, reservations, bank_recon.
(Satış faturaları kendi timer'ında: sprenses-sales-sync; stok Topbar butonuyla.)
Systemd: sprenses-sedna-sync.timer — 09-21 arası 2 saatte bir (sales-sync ile 1 saat
faz farklı; EC2 bellek koruması: ağır işler eşzamanlı tetiklenmez).

REZERVASYON ADIMI (2026-08-17, kullanıcı kararı): Panel'deki "Beklenen ciro tahsilatı"
projeksiyonu `reservations` tablosundan OKUMA-ANINDA türetilir
(`contract_projection_service`) → tablo bayatsa yeni rezervasyon/iptaller projeksiyona
yansımaz. Adım eskiden yalnız Topbar butonuyla koşuyordu (elle, günde 0-2 kez) ve
projeksiyon günlerce eski kalabiliyordu. Bedeli: her turda ~10.000 satır Sedna sorgusu
+ pencere aynalaması (cari yıl+); ölçülen yük kabul edildi. Stok adımı BİLEREK dışarıda
kalmaya devam eder (nakit projeksiyonunu beslemez, elle tetiklenir).

Tünel/Sedna kapalıysa (HTTP 503) uyarı loglar ve 0 ile çıkar (timer'ı düşürmez).
Ancak bir adım GERÇEKTEN hata verirse çıkış kodu 2 (EXIT_PARTIAL) olur → systemd
birimi 'failed' → OnFailure alarmı tetiklenir (denetim JOBS-002). Çıkış-kodu
sözleşmesi: cron_exit_codes.py.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sedna-sync-cron")

_CRON_STEP_KEYS = {"cariler", "ibans", "checks", "recurring_sync", "salary_sync",
                   "reservations", "bank_recon"}


def main() -> int:
    from fastapi import HTTPException

    from app.database import SessionLocal
    from app.integrations.sedna_client import sedna_configured
    from app.models.user import User
    from app.routers.finance import sedna_sync as ss
    from cron_exit_codes import EXIT_OK, exit_code_for_steps

    if not sedna_configured():
        logger.warning("Sedna yapılandırılmamış (SEDNA_PASSWORD boş) — senkron atlandı.")
        return EXIT_OK

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            logger.error("admin kullanıcısı bulunamadı — senkron atlandı.")
            return exit_code_for_steps(started=False, failed_steps=0)
        failed = 0  # tünel-kapalı (HTTP 503) dışı adım hataları — JOBS-002 çıkış kodu
        for st in ss._STEPS:
            if st["key"] not in _CRON_STEP_KEYS:
                continue
            try:
                detail = st["run"](db, admin, "cron")
                logger.info("%s: %s", st["label"], ss._summarize(st["key"], detail))
                if st.get("broadcast"):
                    from app.realtime.finance_broadcast import notify_finance_update_sync
                    notify_finance_update_sync(st["broadcast"], "upload")
            except HTTPException as e:
                db.rollback()
                if e.status_code == 503:
                    # Tünel kapalı — iyi huylu, timer'ı düşürme (exit 0)
                    logger.warning("%s atlandı (tünel kapalı): %s", st["label"], e.detail)
                else:
                    logger.warning("%s başarısız (HTTP %s): %s", st["label"], e.status_code, e.detail)
                    failed += 1
            except Exception as e:  # noqa: BLE001 — adım izolasyonu
                db.rollback()
                logger.error("%s hatası: %s", st["label"], e, exc_info=True)
                failed += 1
        _maybe_notify_aging(db)
        if failed:
            logger.error("Sedna senkronu: %d adım başarısız — birim 'failed' işaretleniyor.", failed)
        return exit_code_for_steps(started=True, failed_steps=failed)
    finally:
        db.close()


def _maybe_notify_aging(db) -> None:
    """Günün İLK koşusunda (09:15) yaşlanan eşleşmemişler özetini bildir (Faz 3 #21).

    2 saatte bir koşan timer'da her tur bildirmek gürültü olur — yalnız sabah turu.
    """
    from datetime import datetime

    import pytz

    now = datetime.now(pytz.timezone("Europe/Istanbul"))
    if now.hour != 9:
        return
    try:
        from app.services.aging_service import compute_aging
        from app.services.sedna_recon_service import _notify_viewers

        aging = compute_aging(db, days=7, item_limit=1)
        stale = aging["stale_forecasts"]["total_count"]
        ub = aging["unmatched_bank"]["count"]
        if stale or ub:
            _notify_viewers(
                db, "Yaşlanan eşleşmemişler",
                f"7 günden eski: {stale} açık tahmin · {ub} etiketsiz banka hareketi — "
                "Nakit Akım › Yaşlananlar raporundan inceleyin")
    except Exception as e:  # bildirim cron'u düşürmesin
        logger.error("Yaşlanma bildirimi başarısız: %s", e)


if __name__ == "__main__":
    sys.exit(main())
