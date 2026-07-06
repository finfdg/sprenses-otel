"""Bildirim oluşturma ve gönderme yardımcıları.

Tüm bildirimler 3 kanaldan iletilir:
1. DB kaydı (kalıcı, bildirim listesinde görünür)
2. WebSocket event (gerçek zamanlı, online kullanıcılar için)
3. Web Push (telefon/tarayıcı bildirimi, offline kullanıcılar için)

Opsiyonel 4. kanal: E-posta (`email=True` verilirse). SMTP yapılandırılmışsa
(bkz. utils/mail.py) bildirim ayrıca e-posta olarak da gönderilir. Push gibi arka
plan thread'inde çalışır — ana isteği bloklamaz.
"""

import logging
import threading
from html import escape
from typing import List, Optional

from sqlalchemy.orm import Session

from app.constants import WSEvent
from app.models.notification import Notification
from app.models.user import User
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


def _build_email_html(title: str, body: str, link: Optional[str]) -> str:
    """Bildirimden basit, güvenli (HTML-escape'li) e-posta gövdesi üret."""
    action = ""
    if link:
        href = link if link.startswith("http") else "https://sprenses.com" + (
            link if link.startswith("/") else "/" + link
        )
        action = (
            '<p style="margin:20px 0;">'
            '<a href="%s" style="background:#1b2b45;color:#ffffff;text-decoration:none;'
            'padding:10px 18px;border-radius:8px;display:inline-block;font-size:14px;">'
            "Görüntüle</a></p>"
        ) % escape(href, quote=True)
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;'
        'color:#1f2937;line-height:1.5;">'
        '<h2 style="font-size:18px;margin:0 0 12px;">%s</h2>'
        '<p style="font-size:14px;white-space:pre-line;margin:0;">%s</p>'
        "%s"
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 12px;">'
        '<p style="color:#6b7280;font-size:12px;margin:0;">Sprenses Otel Yönetim Sistemi</p>'
        "</div>"
    ) % (escape(title), escape(body), action)


def _build_email_payloads(
    db: Session, notifications: List[Notification], link: Optional[str]
) -> List[dict]:
    """Bildirim başına e-posta payload'ı üret (session açıkken kullanıcı e-postalarını çek).

    SMTP kapalıysa boş liste döner (hiç sorgu yapmaz).
    """
    from app.utils.mail import is_mail_enabled

    if not is_mail_enabled() or not notifications:
        return []

    user_ids = list({n.user_id for n in notifications})
    rows = db.query(User.id, User.email).filter(User.id.in_(user_ids)).all()
    email_map = {uid: em for uid, em in rows if em}

    payloads = []
    for n in notifications:
        em = email_map.get(n.user_id)
        if not em:
            continue
        payloads.append(
            {
                "email": em,
                "subject": n.title,
                "body_html": _build_email_html(n.title, n.body, link or n.link),
            }
        )
    return payloads


def _send_email_for_payloads(payloads: List[dict]) -> None:
    """Snapshot e-posta payload'larını gönder (arka plan thread'inde çalışır)."""
    from app.utils.mail import send_email

    for p in payloads:
        try:
            send_email(to=p["email"], subject=p["subject"], body_html=p["body_html"])
        except Exception as e:
            logger.debug("Bildirim e-postası gönderilemedi (%s): %s", p["email"], e)


def _send_email_background(payloads: List[dict]) -> None:
    """E-posta bildirimlerini arka plan thread'inde gönder (ana thread'i bloklamaz)."""
    if not payloads:
        return
    t = threading.Thread(
        target=_send_email_for_payloads,
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
    email: bool = False,
) -> List[Notification]:
    """DB kayıtları oluştur, commit et, WS event + push (+ opsiyonel e-posta) gönder (senkron)."""
    notifications = create_notifications(db, user_ids, type, title, body, link)
    db.commit()

    # Push payload'ları session açıkken snapshot al — thread'e ORM objesi geçme
    push_payloads = [_notification_to_push_payload(n, link) for n in notifications]
    # E-posta payload'ları da session açıkken snapshot al (kullanıcı e-postaları)
    email_payloads = _build_email_payloads(db, notifications, link) if email else []

    # WS event gönder (thread-safe)
    for n in notifications:
        try:
            manager.send_to_user_sync(n.user_id, _notification_to_ws_event(n))
        except Exception as e:
            logger.debug("Bildirim WS gönderilemedi user_id=%d: %s", n.user_id, e)

    # Push bildirim gönder (arka plan thread)
    _send_push_background(push_payloads)
    # E-posta gönder (arka plan thread; SMTP kapalıysa payloads boş → no-op)
    _send_email_background(email_payloads)

    return notifications


async def create_and_send_notifications(
    db: Session,
    user_ids: List[int],
    type: str,
    title: str,
    body: str,
    link: Optional[str] = None,
    email: bool = False,
) -> List[Notification]:
    """DB kayıtları oluştur, WS event + push (+ opsiyonel e-posta) gönder (async)."""
    notifications = create_notifications(db, user_ids, type, title, body, link)
    db.commit()

    # Push payload'ları session açıkken snapshot al — thread'e ORM objesi geçme
    push_payloads = [_notification_to_push_payload(n, link) for n in notifications]
    # E-posta payload'ları da session açıkken snapshot al (kullanıcı e-postaları)
    email_payloads = _build_email_payloads(db, notifications, link) if email else []

    # WS event gönder
    for n in notifications:
        try:
            await manager.send_to_user(n.user_id, _notification_to_ws_event(n))
        except Exception as e:
            logger.debug("Bildirim WS gönderilemedi user_id=%d: %s", n.user_id, e)

    # Push bildirim gönder (arka plan thread)
    _send_push_background(push_payloads)
    # E-posta gönder (arka plan thread; SMTP kapalıysa payloads boş → no-op)
    _send_email_background(email_payloads)

    return notifications
