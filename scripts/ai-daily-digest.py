#!/usr/bin/env python3
"""Günlük özet bildirimi — sabahları finans-görme yetkili kullanıcılara "Günün Özeti".

systemd timer (sprenses-ai-digest.timer) her sabah 08:00 (Europe/Istanbul) çalıştırır.
İçerik: önümüzdeki 7 günde yaklaşan ödemeler (finance_events). Bildirim in-app + WS +
push olarak gönderilir (create_and_send_notifications_sync). Kayda değer bir şey yoksa
(hiç yaklaşan ödeme yoksa) gürültü olmasın diye bildirim GÖNDERİLMEZ.

Çalıştırma: backend venv python ile. app.config .env'i mutlak yoldan okur → cwd bağımsız.
"""
import logging
import os
import sys

# backend'i import yoluna ekle (script scripts/ altında)
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, _BACKEND)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ai-daily-digest")


def _fmt(n: float) -> str:
    """Türkçe binlik ayırıcı (nokta) ile tam sayı biçimi."""
    return f"{n:,.0f}".replace(",", ".")


def main() -> int:
    from app.database import SessionLocal
    from app.middleware.auth import user_can
    from app.models.user import User
    from app.services import ai_service
    from app.utils.notification import create_and_send_notifications_sync

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        targets = [u for u in users if user_can(db, u, "finance.cash_flow", "view")]
        if not targets:
            logger.info("Finans-görme yetkili kullanıcı yok — bildirim gönderilmedi.")
            return 0

        # Özeti temsili (yetkili) kullanıcı üzerinden derle; ödeme bölümünü al
        digest = ai_service.compute_digest(db, targets[0], gun=7)
        odeme = next((b for b in digest["bolumler"] if "ödemeler" in b["baslik"]), None)
        if not odeme or odeme["adet"] == 0:
            logger.info("Yaklaşan ödeme yok — bildirim gönderilmedi.")
            return 0

        para = ", ".join(f"{_fmt(p['toplam'])} {p['para_birimi']}" for p in odeme["para_bazli"])
        body = f"Önümüzdeki 7 günde {odeme['adet']} kalem ödeme: {para}. Detay için Asistan'a sorun."

        create_and_send_notifications_sync(
            db,
            [u.id for u in targets],
            type="ai_digest",
            title="Günün Özeti 📋",
            body=body,
            link="/dashboard/asistan",
        )
        db.commit()
        logger.info("Günün özeti %d kullanıcıya gönderildi: %s", len(targets), body)
        return 0
    except Exception:
        db.rollback()
        logger.exception("Günün özeti gönderilemedi")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
