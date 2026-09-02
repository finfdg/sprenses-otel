"""Kimlik doğrulama endpoint'leri — giriş, kayıt, şifre değiştirme, çıkış, e-posta teyidi."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from jose import JWTError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.constants import WSEvent
from app.database import get_db
from app.middleware.auth import COOKIE_NAME, get_current_user
from app.middleware.rate_limit import get_client_ip, login_limiter
from app.models.user import User
from app.schemas.user import EmailVerifyRequest, PasswordChange, TokenResponse, UserLogin, UserResponse
from app.utils.audit import log_action
from app.utils.response_builders import build_user_response
from app.utils.security import (
    create_access_token,
    decode_email_verification_token,
    generate_session_id,
    hash_password,
    tz_istanbul,
    verify_password,
)
from app.websocket.manager import manager


def _set_auth_cookie(response: Response, token: str) -> None:
    """JWT token'ı HttpOnly cookie olarak ayarla."""
    # Production'da secure=True; test ortamında (HTTP) cookie geri gönderilmesi için secure=False
    is_secure = settings.cors_origins.startswith("https")
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    client_ip = get_client_ip(request)
    login_limiter.check(client_ip)

    user = (
        db.query(User)
        .options(joinedload(User.role_rel))
        .filter(User.username == data.username)
        .first()
    )
    if not user or not verify_password(data.password, user.hashed_password):
        logger.warning("Başarısız giriş denemesi: kullanıcı=%s ip=%s", data.username, client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı adı veya şifre hatalı")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hesabınız devre dışı bırakılmış")

    # Eski oturumu sonlandır (varsa)
    if user.active_session_id:
        await manager.send_to_user(user.id, {
            "type": WSEvent.SESSION_EXPIRED,
            "reason": "Başka bir cihazdan giriş yapıldı",
        })
        log_action(
            db, user.id, "session_invalidated", "auth",
            details="Yeni giriş nedeniyle eski oturum sonlandırıldı",
            ip_address=client_ip,
        )

    # Yeni oturum kimliği oluştur
    new_session_id = generate_session_id()
    user.active_session_id = new_session_id

    token = create_access_token({"sub": str(user.id)}, session_id=new_session_id)
    user_resp = build_user_response(user, db)

    log_action(db, user.id, "login", "auth", ip_address=client_ip)
    db.commit()

    # HttpOnly cookie ile token set et
    _set_auth_cookie(response, token)

    # Token yalnızca HttpOnly cookie ile gönderilir, body'de döndürülmez
    return TokenResponse(user=user_resp)


# NOT: Public self-service kayıt (/register) GÜVENLİK NEDENİYLE KALDIRILDI (2026-06-19).
# Bu bir iç (B2B) yönetim panelidir; internete açık kayıt, herkesin "Personel" rolüyle
# kimlik doğrulanmış oturum alıp otel verisine (doluluk/rezervasyon vb.) yetkisiz okuma
# yapmasına izin veriyordu. Kullanıcılar yalnızca admin tarafından
# `POST /api/system/users/` (system.users:use izni) ile oluşturulur.


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_user_response(current_user, db)


@router.post("/change-password")
def change_password(
    data: PasswordChange,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kullanıcının kendi şifresini değiştirmesi."""
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mevcut şifre hatalı")
    if not data.new_password or len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 8 karakter olmalıdır")
    current_user.hashed_password = hash_password(data.new_password)

    # Yeni oturum kimliği — eski token'lar geçersiz olur
    new_session_id = generate_session_id()
    current_user.active_session_id = new_session_id
    new_token = create_access_token({"sub": str(current_user.id)}, session_id=new_session_id)
    _set_auth_cookie(response, new_token)

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "change_password", "auth", ip_address=client_ip)
    db.commit()

    # Token yalnızca HttpOnly cookie ile gönderilir
    return {"detail": "Şifre başarıyla değiştirildi"}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Çıkış yap — HttpOnly cookie'yi temizle ve oturumu sonlandır."""
    current_user.active_session_id = None
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )
    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "logout", "auth", ip_address=client_ip)
    db.commit()
    return {"detail": "Başarıyla çıkış yapıldı"}


@router.post("/verify-email")
def verify_email(data: EmailVerifyRequest, request: Request, db: Session = Depends(get_db)):
    """E-posta teyit bağlantısını doğrula — PUBLIC (giriş gerektirmez).

    Token imzalıdır ve içindeki e-posta, kullanıcının O ANKİ e-postasıyla eşleşmelidir
    (token üretildikten sonra e-posta değiştiyse bağlantı geçersizdir). Zaten doğrulanmışsa
    idempotent olarak başarı döner.
    """
    try:
        payload = decode_email_verification_token(data.token)
    except JWTError:
        raise HTTPException(status_code=400, detail="Bağlantı geçersiz veya süresi dolmuş")

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        raise HTTPException(status_code=400, detail="Bağlantı geçersiz")
    # Token üretildiğinden bu yana e-posta değişmişse bağlantı artık geçerli değil
    if not user.email or user.email != payload.get("email"):
        raise HTTPException(status_code=400, detail="Bu bağlantı artık geçerli değil (e-posta değişmiş)")

    if not user.email_verified:
        user.email_verified = True
        user.email_verified_at = datetime.now(tz_istanbul)
        verified_at = user.email_verified_at
        client_ip = get_client_ip(request)
        log_action(db, user.id, "verify_email", "user", entity_id=user.id, ip_address=client_ip)
        db.commit()

        # Kullanıcı listesini açık tutan yöneticilere anlık bildir (WS — polling yerine)
        try:
            manager.send_to_all_sync({
                "type": WSEvent.USER_EMAIL_VERIFIED,
                "user_id": user.id,
                "email_verified": True,
                "email_verified_at": str(verified_at) if verified_at else None,
            })
        except Exception as e:
            logger.debug("E-posta teyit WS broadcast hatası user_id=%d: %s", user.id, e)

    return {"detail": "E-posta adresiniz doğrulandı", "email": user.email}
