#!/usr/bin/env python3
"""Günlük disk temizliği cronu (sprenses-disk-cleanup.timer).

`disk_cleanup_service.run_cleanup()` çağırır — UI'daki "Temizle" butonuyla BİREBİR aynı kod
(ortak servis deseni: elle/otomatik temizlik arasında sapma olamaz).

Yalnız yeniden üretilebilir veriler silinir (journald fazlası, npm/pip/dnf önbelleği, eski
döndürülmüş uygulama logları, eski Claude CLI sürümleri). Müşteri dosyaları, yedekler ve
bağımlılıklar `cleanable=False` olduğundan hiçbir koşulda silinmez.

Audit log'a `admin` kullanıcısı adına yazılır — otomatik temizlikler de Audit Loglar
sayfasında görünür. DB erişilemezse temizlik yine yapılır, yalnız audit atlanır (timer düşmez).
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("disk-cleanup-cron")


def main() -> int:
    from app.services import disk_cleanup_service

    before = disk_cleanup_service.scan_disk()
    fs = before["filesystem"]
    logger.info(
        "Disk %.1f%% dolu (%.1f GB boş) — temizlenebilir: %.1f MB",
        fs["percent"],
        fs["free_bytes"] / 1024 ** 3,
        before["total_cleanable_bytes"] / 1024 ** 2,
    )

    result = disk_cleanup_service.run_cleanup()
    freed_mb = result["freed_bytes"] / 1024 ** 2
    for item in result["results"]:
        logger.info("  %-16s %8.1f MB", item["key"], item["freed_bytes"] / 1024 ** 2)
    logger.info(
        "Toplam %.1f MB serbest bırakıldı — disk şimdi %.1f%% dolu (%.1f GB boş)",
        freed_mb,
        result["filesystem"]["percent"],
        result["filesystem"]["free_bytes"] / 1024 ** 3,
    )

    # Audit — DB kapalıysa temizliği başarısız saymayız
    try:
        from app.database import SessionLocal
        from app.models.user import User
        from app.utils.audit import log_action

        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").first()
            if admin:
                log_action(
                    db, admin.id, "cleanup", "server_disk",
                    entity_id=0,
                    details="Otomatik disk temizliği: {} — {:.1f} MB serbest bırakıldı".format(
                        ", ".join(result["cleaned_keys"]) or "—", freed_mb,
                    ),
                    ip_address="cron",
                )
                db.commit()
            else:
                logger.warning("admin kullanıcısı bulunamadı — audit kaydı atlandı.")
        finally:
            db.close()
    except Exception:
        logger.warning("Audit kaydı yazılamadı (temizlik yine de yapıldı).", exc_info=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
