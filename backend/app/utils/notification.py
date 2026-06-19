"""Bildirim oluşturma ve gönderme yardımcıları.

Tüm bildirimler 3 kanaldan iletilir:
1. DB kaydı (kalıcı, bildirim listesinde görünür)
2. WebSocket event (gerçek zamanlı, online kullanıcılar için)
3. Web Push (telefon/tarayıcı bildirimi, offline kullanıcılar için)
"""

import logging
import threading
from typing import List, Optional

from sqlalchemy.orm import Session

from app.constants import WSEvent
from app.models.notification import Notification
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


def create_notifications(
    db: Session,
    user_ids: List[int],
    type: str,
    title: str,
    body: str,
    link: Optional[str] = None,
) -> List[Notification]:
    """Birden fazla kullanıcı için bildirim kayıtları oluştur."""
    notifications = []
    for uid in user_ids:
        n = Notification(
            user_id=uid,
            type=type,
            title=title,
            body=body,
            link=link,
        )
        db.add(n)
        notifications.append(n)
    db.flush()
    return notifications


def _notification_to_ws_event(n: Notification) -> dict:
    """Notification kaydını WS event dict'ine dönüştür."""
    return {
        "type": WSEvent.NOTIFICATION,
        "notification": {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "body": n.body,
            "link": n.link,
            "is_read": False,
            "created_at": str(n.created_at) if n.created_at else None,
        },
    }


def _notification_to_push_payload(n: Notification, link: Optional[str]) -> dict:
    """ORM Notification'dan thread-safe push payload (plain dict) üret.

    Thread'e ORM objesi geçirmek detached instance / session-closed hatasına yol açar.
    Bu yüzden push gönderiminden önce session açıkken snapshot alınır.
    """
    return {
        "user_id": n.user_id,
        "title": n.title,
        "body": n.body,
        "url": link or n.link or "/dashboard",
        "tag": "notif-%d" % n.id,
    }


def _send_push_for_payloads(payloads: List[dict]) -> None:
    """Snapshot payload listesini push olarak gönder (arka plan thread'inde çalışır).

    Online olmayan kullanıcılara push gönderir. Online kullanıcılar zaten
    WS ile bildirim alır, ancak telefonda push bildirimi de görsünler diye
    tüm kullanıcılara gönderilir.
    """
    from app.utils.push import send_push_to_user

    for p in payloads:
        try:
            send_push_to_user(**p)
        except Exception as e:
            logger.debug("Push gönderilemedi user_id=%d: %s", p["user_id"], e)


def _send_push_background(payloads: List[dict]) -> None:
    """Push bildirimlerini arka plan thread'inde gönder (ana thread'i bloklamaz)."""
    t = threading.Thread(
        target=_send_push_for_payloads,
        args=(payloads,),
        daemon=True,
    )
    t.start()


def create_and_send_notifications_sync(
    db: Session,
    user_ids: List[int],
    type: str,
    title: str,
    body: str,
    link: Optional[str] = None,
) -> List[Notification]:
    """DB kayıtları oluştur, commit et, WS event + push gönder (senkron)."""
    notifications = create_notifications(db, user_ids, type, title, body, link)
    db.commit()

    # Push payload'ları session açıkken snapshot al — thread'e ORM objesi geçme
    push_payloads = [_notification_to_push_payload(n, link) for n in notifications]

    # WS event gönder (thread-safe)
    for n in notifications:
        try:
            manager.send_to_user_sync(n.user_id, _notification_to_ws_event(n))
        except Exception as e:
            logger.debug("Bildirim WS gönderilemedi user_id=%d: %s", n.user_id, e)

    # Push bildirim gönder (arka plan thread)
    _send_push_background(push_payloads)

    return notifications


async def create_and_send_notifications(
    db: Session,
    user_ids: List[int],
    type: str,
    title: str,
    body: str,
    link: Optional[str] = None,
) -> List[Notification]:
    """DB kayıtları oluştur, WS event + push gönder (async)."""
    notifications = create_notifications(db, user_ids, type, title, body, link)
    db.commit()

    # Push payload'ları session açıkken snapshot al — thread'e ORM objesi geçme
    push_payloads = [_notification_to_push_payload(n, link) for n in notifications]

    # WS event gönder
    for n in notifications:
        try:
            await manager.send_to_user(n.user_id, _notification_to_ws_event(n))
        except Exception as e:
            logger.debug("Bildirim WS gönderilemedi user_id=%d: %s", n.user_id, e)

    # Push bildirim gönder (arka plan thread)
    _send_push_background(push_payloads)

    return notifications
