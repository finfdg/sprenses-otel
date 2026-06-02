import json
import logging
from typing import Optional

from pywebpush import WebPushException, webpush

from app.config import settings
from app.database import SessionLocal
from app.models.push_subscription import PushSubscription

logger = logging.getLogger("uvicorn.error")


def send_push_to_user(
    user_id: int,
    title: str,
    body: str,
    url: Optional[str] = None,
    tag: Optional[str] = None,
) -> None:
    """
    Kullanıcının tüm aktif push aboneliklerine bildirim gönder.
    BackgroundTasks'tan çağrılmak üzere tasarlanmıştır.
    """
    if not settings.vapid_private_key or not settings.vapid_public_key:
        return

    db = SessionLocal()
    try:
        subscriptions = (
            db.query(PushSubscription)
            .filter(
                PushSubscription.user_id == user_id,
                PushSubscription.is_active == True,
            )
            .all()
        )

        payload = json.dumps({
            "title": title,
            "body": body,
            "url": url or "/dashboard/mesajlasma",
            "tag": tag or "msg-%d" % user_id,
            "icon": "/icon-192.png",
            "badge": "/icon-192.png",
            "user_id": user_id,
        })

        if not subscriptions:
            logger.info("Push: user_id=%d için aktif abonelik yok", user_id)
            return

        deactivated = False
        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh_key,
                            "auth": sub.auth_key,
                        }
                    },
                    data=payload,
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims={
                        "sub": settings.vapid_mailto,
                    }
                )
                logger.info("Push gönderildi: user_id=%d, title=%s", user_id, title)
            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    # Abonelik süresi dolmuş veya geçersiz — deaktive et
                    sub.is_active = False
                    deactivated = True
                    logger.info("Push aboneliği deaktive edildi: user_id=%d, status=%d", user_id, e.response.status_code)
                else:
                    logger.warning("Push gönderimi başarısız: user_id=%d, hata=%s", user_id, e)
            except Exception as e:
                logger.warning("Push gönderimi hatası: user_id=%d, hata=%s", user_id, e)

        # Geçersiz abonelikleri toplu olarak kaydet
        if deactivated:
            db.commit()
    finally:
        db.close()
