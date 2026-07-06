"""Bildirim endpoint'leri — liste, okunmamış sayısı, okundu işaretleme."""


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationMarkRead, NotificationResponse
from app.utils.mail import is_mail_enabled, send_email
from app.utils.pagination import page_meta

router = APIRouter()


@router.get("/")
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kullanıcının bildirimlerini listele (en yeniden eskiye)."""
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id
    ).order_by(desc(Notification.created_at))

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    return page_meta([NotificationResponse.model_validate(n).model_dump() for n in items], total, page, page_size)


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Okunmamış bildirim sayısını döndür."""
    count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    ).scalar()
    return {"count": count or 0}


@router.patch("/read")
def mark_read(
    data: NotificationMarkRead,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bildirimleri okundu olarak işaretle. notification_ids boşsa tümünü işaretle."""
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    )
    if data.notification_ids:
        query = query.filter(Notification.id.in_(data.notification_ids))

    updated = query.update({"is_read": True}, synchronize_session=False)
    db.commit()

    # Güncel okunmamış sayıyı döndür
    new_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,
    ).scalar()

    return {"detail": f"{updated} bildirim okundu olarak işaretlendi", "unread_count": new_count or 0}


@router.post("/test-email")
def send_test_email(
    current_user: User = Depends(require_permission("system.users", "use")),
):
    """SMTP yapılandırmasını doğrula — giriş yapan yöneticinin kendi e-postasına
    deneme e-postası gönderir (senkron; gerçek sonucu döner). Yalnız system.users
    'use' izni olan kullanıcılar erişebilir."""
    if not is_mail_enabled():
        raise HTTPException(
            status_code=503,
            detail="E-posta (SMTP) yapılandırılmamış — .env dosyasında SMTP_PASSWORD tanımlayın",
        )
    ok = send_email(
        to=current_user.email,
        subject="Sprenses Otel — Deneme E-postası",
        body_html=(
            '<div style="font-family:Arial,Helvetica,sans-serif;color:#1f2937;">'
            '<h2 style="font-size:18px;">Deneme e-postası</h2>'
            "<p>Bu e-posta, Sprenses Otel Yönetim Sistemi SMTP yapılandırmasının "
            "çalıştığını doğrulamak için gönderildi. Bu mesajı aldıysanız giden "
            "e-posta bildirimleri hazır demektir.</p>"
            '<p style="color:#6b7280;font-size:12px;">Gönderen: %s</p>'
            "</div>"
        ) % settings.smtp_user,
        body_text="Bu, Sprenses Otel SMTP yapılandırma deneme e-postasıdır.",
    )
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="E-posta gönderilemedi — SMTP sunucu/port/şifre ayarlarını kontrol edin (sunucu loglarına bakın)",
        )
    return {"success": True, "sent_to": current_user.email}


@router.delete("/all")
def delete_all_notifications(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
        """Kullanıcının tüm bildirimlerini sil."""
        deleted = db.query(Notification).filter(
                    Notification.user_id == current_user.id,
        ).delete(synchronize_session=False)
        db.commit()
        return {"detail": f"{deleted} bildirim silindi"}


@router.delete("/{notification_id}")
def delete_notification(
        notification_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
        """Tek bir bildirimi sil."""
        notification = db.query(Notification).filter(
                    Notification.id == notification_id,
                    Notification.user_id == current_user.id,
        ).first()

        if not notification:
                raise HTTPException(status_code=404, detail="Bildirim bulunamadı")

        db.delete(notification)
        db.commit()
        return {"detail": "Bildirim silindi"}
