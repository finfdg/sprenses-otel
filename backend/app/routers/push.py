from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.schemas.push import PushSubscriptionCreate, PushSubscriptionResponse, VapidPublicKeyResponse
from app.utils.push import send_push_to_user

router = APIRouter()

# Bir kullanıcı için aktif tutulacak azami abonelik sayısı. Her tarayıcı / cihaz /
# yeniden kurulum YENİ bir endpoint üretir (endpoint bazlı upsert eskileri
# birleştirmez) → eski endpoint'ler ölü kalır ve her bildirimde boş yere push
# denenir, gönderim yavaşlar. Yeni abonelikte en yeni N tutulur, fazlası pasiflenir.
MAX_ACTIVE_SUBSCRIPTIONS_PER_USER = 10


def _prune_user_subscriptions(db: Session, user_id: int) -> None:
    """Kullanıcının en yeni N aktif aboneliğini tut, daha eskilerini pasifleştir."""
    stale = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.user_id == user_id,
            PushSubscription.is_active == True,
        )
        .order_by(PushSubscription.created_at.desc(), PushSubscription.id.desc())
        .offset(MAX_ACTIVE_SUBSCRIPTIONS_PER_USER)
        .all()
    )
    if stale:
        for s in stale:
            s.is_active = False
        db.commit()


@router.get("/vapid-key", response_model=VapidPublicKeyResponse)
def get_vapid_public_key(
    current_user: User = Depends(get_current_user),
):
    """VAPID public key'i döndür (client push subscription için gerekli)."""
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Push bildirimleri yapılandırılmamış")
    return VapidPublicKeyResponse(public_key=settings.vapid_public_key)


@router.post("/subscribe", response_model=PushSubscriptionResponse, status_code=201)
def subscribe(
    data: PushSubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Push bildirim aboneliği kaydet."""
    # Upsert: endpoint zaten varsa güncelle
    existing = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == data.endpoint)
        .first()
    )
    if existing:
        existing.user_id = current_user.id
        existing.p256dh_key = data.keys.p256dh
        existing.auth_key = data.keys.auth
        existing.user_agent = data.user_agent
        existing.is_active = True
        db.commit()
        _prune_user_subscriptions(db, current_user.id)
        db.refresh(existing)
        return existing

    sub = PushSubscription(
        user_id=current_user.id,
        endpoint=data.endpoint,
        p256dh_key=data.keys.p256dh,
        auth_key=data.keys.auth,
        user_agent=data.user_agent,
    )
    db.add(sub)
    db.commit()
    _prune_user_subscriptions(db, current_user.id)
    db.refresh(sub)
    return sub


@router.delete("/unsubscribe")
def unsubscribe(
    endpoint: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Push bildirim aboneliğini iptal et."""
    sub = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.endpoint == endpoint,
            PushSubscription.user_id == current_user.id,
        )
        .first()
    )
    if sub:
        sub.is_active = False
        db.commit()
    return {"ok": True}


@router.post("/test")
def test_push(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kendine test push bildirimi gönder (is_online kontrolü atlanır)."""
    sub_count = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.user_id == current_user.id,
            PushSubscription.is_active == True,
        )
        .count()
    )
    if sub_count == 0:
        raise HTTPException(status_code=404, detail="Aktif push aboneliğiniz yok")

    background_tasks.add_task(
        send_push_to_user,
        current_user.id,
        "Push Test",
        "Bu bir test bildirimidir. Eğer bunu görüyorsanız push çalışıyor!",
        "/dashboard/mesajlasma",
        "push-test",
    )
    return {"ok": True, "subscriptions": sub_count}
