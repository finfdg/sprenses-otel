#!/usr/bin/env python3
"""Cari + çek + düzenli-ödeme + banka-mutabakat Sedna senkron cronu (Faz 2 #18).

Merkezi Sedna senkronunun ÇEKİRDEK finans adımlarını admin kullanıcısıyla koşar:
cariler, ibans, checks, recurring_sync, bank_recon. (Satış faturaları kendi
timer'ında: sprenses-sales-sync; stok/rezervasyon Topbar butonuyla.) Systemd:
sprenses-sedna-sync.timer — 09-21 arası 2 saatte bir (sales-sync ile 1 saat faz
farklı; EC2 bellek koruması: ağır işler eşzamanlı tetiklenmez).

Tünel/Sedna kapalıysa uyarı loglar ve 0 ile çıkar (timer'ı düşürmez).
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sedna-sync-cron")

_CRON_STEP_KEYS = {"cariler", "ibans", "checks", "recurring_sync", "salary_sync", "bank_recon"}


def main() -> int:
    from fastapi import HTTPException

    from app.database import SessionLocal
    from app.models.user import User
    from app.routers.finance import sedna_sync as ss
    from app.utils.sedna_client import sedna_configured

    if not sedna_configured():
        logger.warning("Sedna yapılandırılmamış (SEDNA_PASSWORD boş) — senkron atlandı.")
        return 0

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            logger.error("admin kullanıcısı bulunamadı — senkron atlandı.")
            return 1
        for st in ss._STEPS:
            if st["key"] not in _CRON_STEP_KEYS:
                continue
            try:
                detail = st["run"](db, admin, "cron")
                logger.info("%s: %s", st["label"], ss._summarize(st["key"], detail))
                if st.get("broadcast"):
                    from app.utils.finance_broadcast import notify_finance_update_sync
                    notify_finance_update_sync(st["broadcast"], "upload")
            except HTTPException as e:
                db.rollback()
                if e.status_code == 503:
                    logger.warning("%s atlandı (tünel kapalı): %s", st["label"], e.detail)
                else:
                    logger.warning("%s başarısız (HTTP %s): %s", st["label"], e.status_code, e.detail)
            except Exception as e:  # noqa: BLE001 — adım izolasyonu
                db.rollback()
                logger.error("%s hatası: %s", st["label"], e, exc_info=True)
        _maybe_notify_aging(db)
        return 0
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
        from app.routers.finance.cash_flow.aging import compute_aging
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
