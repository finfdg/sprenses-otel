"""Bildirim endpoint'leri — liste, okunmamış sayısı, okundu işaretleme."""


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationMarkRead, NotificationResponse
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
