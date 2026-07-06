"""Bildirim endpoint'leri — liste, okunmamış sayısı, okundu işaretleme."""


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from typing import Optional

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationMarkRead, NotificationResponse, TestEmailRequest
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


@router.get("/test-email/recipients")
def list_test_email_recipients(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.server", "use")),
):
    """Deneme e-postası gönderilebilecek alıcılar — aktif kullanıcılar (ad + e-posta).
    Deneme özelliğine özel hafif liste; ada göre sıralı."""
    users = (
        db.query(User)
        .filter(
            User.is_active == True,  # noqa: E712
            User.email.isnot(None),
            User.email != "",
        )
        .order_by(User.first_name, User.last_name)
        .all()
    )
    return [{"id": u.id, "name": u.full_name, "email": u.email} for u in users]


@router.post("/test-email")
def send_test_email(
    data: Optional[TestEmailRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.server", "use")),
):
    """SMTP yapılandırmasını doğrula — deneme e-postası gönderir (senkron; gerçek
    sonucu döner). Sunucu (system.server) 'use' izni gerekir.

    - `user_id` verilirse → o kullanıcının tanımlı e-posta adresine gönderir
      (o adresin gerçekten teslim aldığını da test eder).
    - `user_id` verilmezse → sistem kutusuna (SMTP kullanıcısı = bilgi@sprenses.com)
      gönderir (her zaman var olan güvenli öz-test)."""
    if not is_mail_enabled():
        raise HTTPException(
            status_code=503,
            detail="E-posta (SMTP) yapılandırılmamış — .env dosyasında SMTP_PASSWORD tanımlayın",
        )

    user_id = data.user_id if data else None
    if user_id is not None:
        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        if not target.email:
            raise HTTPException(
                status_code=400,
                detail="Bu kullanıcının tanımlı bir e-posta adresi yok",
            )
        recipient = target.email
    else:
        # Kullanıcı hesap e-postası gerçek bir posta kutusu olmayabilir (ör.
        # admin@sprenses.com → 550 Recipient rejected) → varsayılan güvenli alıcı
        # her zaman var olan sistem kutusudur.
        recipient = settings.smtp_user

    ok = send_email(
        to=recipient,
        subject="Sprenses Otel — Deneme E-postası",
        body_html=(
            '<div style="font-family:Arial,Helvetica,sans-serif;color:#1f2937;">'
            '<h2 style="font-size:18px;">Deneme e-postası</h2>'
            "<p>Bu e-posta, Sprenses Otel Yönetim Sistemi SMTP yapılandırmasının "
            "çalıştığını doğrulamak için gönderildi. Bu mesajı aldıysanız giden "
            "e-posta bildirimleri hazır demektir.</p>"
            '<p style="color:#6b7280;font-size:12px;">Test eden: %s (%s)</p>'
            "</div>"
        ) % (current_user.full_name, current_user.email),
        body_text="Bu, Sprenses Otel SMTP yapılandırma deneme e-postasıdır.",
    )
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="E-posta gönderilemedi — alıcı adresi geçersiz olabilir ya da SMTP ayarlarını kontrol edin (sunucu loglarına bakın)",
        )
    return {"success": True, "sent_to": recipient}


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
