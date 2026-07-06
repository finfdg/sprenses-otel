"""Sistem kullanıcı yönetimi — CRUD, şifre sıfırlama, aktif/pasif."""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.constants import WSEvent
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.role import Role
from app.models.user import User
from app.schemas.user import PasswordReset, UserCreate, UserResponse, UserUpdate
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.mail import is_mail_enabled, send_email_background
from app.utils.response_builders import build_user_response, build_user_responses_batch
from app.utils.security import create_email_verification_token, hash_password
from app.services import system_service
from app.utils.sql_search import like_pattern
from app.websocket.manager import manager
from app.utils.pagination import page_meta

router = APIRouter()


def _send_verification_email(user: User) -> None:
    """Kullanıcının tanımlı e-posta adresine teyit bağlantılı e-posta gönder (arka plan)."""
    token = create_email_verification_token(user.id, user.email)
    link = "%s/eposta-teyit?token=%s" % (settings.public_base_url.rstrip("/"), token)
    body_html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#1f2937;max-width:560px;">'
        '<h2 style="font-size:18px;">E-posta adresinizi doğrulayın</h2>'
        "<p>Merhaba %s,</p>"
        "<p>Sprenses Otel Yönetim Sistemi'nde hesabınıza tanımlı bu e-posta adresini "
        "doğrulamak için aşağıdaki butona tıklayın. Bağlantı 48 saat geçerlidir.</p>"
        '<p style="margin:20px 0;">'
        '<a href="%s" style="background:#1b2b45;color:#ffffff;text-decoration:none;'
        'padding:10px 18px;border-radius:8px;display:inline-block;font-size:14px;">'
        "E-postamı doğrula</a></p>"
        '<p style="color:#6b7280;font-size:12px;">Bu isteği siz yapmadıysanız bu e-postayı '
        "yok sayabilirsiniz.</p>"
        "</div>"
    ) % (user.full_name, link)
    send_email_background(
        to=user.email,
        subject="Sprenses Otel — E-posta Doğrulama",
        body_html=body_html,
        body_text="E-posta adresinizi doğrulamak için: %s" % link,
    )


@router.get("/")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.users", "view")),
):
    query = db.query(User).options(joinedload(User.role_rel))

    if search:
        from sqlalchemy import or_
        pattern = like_pattern(search)
        query = query.filter(or_(
            User.first_name.ilike(pattern, escape="\\"),
            User.last_name.ilike(pattern, escape="\\"),
            User.username.ilike(pattern, escape="\\"),
        ))

    total = query.count()
    users = query.order_by(User.first_name).offset((page - 1) * page_size).limit(page_size).all()

    return page_meta(build_user_responses_batch(users, db), total, page, page_size)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.users", "view")),
):
    user = db.query(User).options(joinedload(User.role_rel)).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return build_user_response(user, db)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.users", "use")),
):
    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kayıtlı")
    if data.email:
        existing_email = db.query(User).filter(User.email == data.email).first()
        if existing_email:
            raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı")
    # Verify role exists
    role = db.query(Role).filter(Role.id == data.role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol bulunamadı")

    approval_resp = check_approval(db, "system.users", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    user = system_service.create_user(db, data.model_dump())
    db.flush()

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "create", "user", entity_id=user.id, ip_address=client_ip)
    db.commit()

    user = db.query(User).options(joinedload(User.role_rel)).filter(User.id == user.id).first()
    return build_user_response(user, db)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.users", "use")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    approval_resp = check_approval(db, "system.users", user_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp

    update_data = data.model_dump(exclude_unset=True)

    # email None gelirse boş string'e çevir (DB NOT NULL kısıtlaması)
    if "email" in update_data and update_data["email"] is None:
        update_data["email"] = ""

    # Check username uniqueness
    if "username" in update_data and update_data["username"] != user.username:
        existing = db.query(User).filter(User.username == update_data["username"]).first()
        if existing:
            raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kayıtlı")
    # Check email uniqueness
    if "email" in update_data and update_data["email"] and update_data["email"] != user.email:
        existing = db.query(User).filter(User.email == update_data["email"]).first()
        if existing:
            raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı")
    _flags = system_service.apply_user_update(db, user, update_data)

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "update", "user", entity_id=user_id, ip_address=client_ip)
    db.commit()

    # Devre dışı bırakma veya rol değişikliği bildirimlerini gönder
    if _flags["disabled"]:
        background_tasks.add_task(
            manager.send_to_user,
            user_id,
            {"type": WSEvent.FORCE_LOGOUT, "reason": "account_disabled"},
        )
    elif _flags["role_changed"]:
        background_tasks.add_task(
            manager.send_to_user,
            user_id,
            {"type": WSEvent.PERMISSION_CHANGED, "reason": "role_changed"},
        )

    user = db.query(User).options(joinedload(User.role_rel)).filter(User.id == user.id).first()
    return build_user_response(user, db)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.users", "use")),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Kendinizi silemezsiniz!")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    approval_resp = check_approval(db, "system.users", user_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    system_service.delete_user(db, user)
    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "delete", "user", entity_id=user_id, ip_address=client_ip)
    db.commit()


@router.post("/{user_id}/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    user_id: int,
    data: PasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.users", "use")),
):
    """Admin tarafından kullanıcı şifresini sıfırla.

    ONAY İSTİSNASI (2026-07-01 kararı): Bu POST mutasyonu bilinçli olarak `check_approval`'dan
    GEÇMEZ — şifre sıfırlama, kilitli/ele geçirilmiş hesaba acil müdahale operasyonudur; onay
    beklemek güvenlik müdahalesini geciktirir. İşlem `log_action` (audit) ile izlenir.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    user.hashed_password = hash_password(data.new_password)
    user.active_session_id = None  # Eski oturumu sonlandır

    # Kullanıcı online ise oturum sonlandı bildirimi gönder
    await manager.send_to_user(user_id, {
        "type": WSEvent.SESSION_EXPIRED,
        "reason": "Şifreniz sıfırlandığı için oturumunuz sonlandırıldı",
    })

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "reset_password", "user", entity_id=user_id, ip_address=client_ip)
    db.commit()

    return {"detail": "Şifre başarıyla sıfırlandı"}


@router.post("/{user_id}/send-verification", status_code=status.HTTP_200_OK)
def send_verification(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.users", "use")),
):
    """Kullanıcının tanımlı e-posta adresine teyit (doğrulama) e-postası gönder.

    ONAY İSTİSNASI: Entity CRUD mutasyonu değil, operasyonel bir doğrulama işlemidir
    (reset-password gibi) → `check_approval`'dan geçmez; `log_action` ile izlenir.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if not user.email:
        raise HTTPException(status_code=400, detail="Bu kullanıcının tanımlı bir e-posta adresi yok")
    if not is_mail_enabled():
        raise HTTPException(
            status_code=503,
            detail="E-posta (SMTP) yapılandırılmamış — .env dosyasında SMTP_PASSWORD tanımlayın",
        )

    _send_verification_email(user)

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "send_verification", "user", entity_id=user_id, ip_address=client_ip)
    db.commit()

    return {"detail": "Teyit e-postası gönderildi", "email": user.email}
