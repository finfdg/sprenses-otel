"""Sistem kullanıcı yönetimi — CRUD, şifre sıfırlama, aktif/pasif."""

import math
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.role import Role
from app.models.user import User
from app.schemas.user import PasswordReset, UserCreate, UserResponse, UserUpdate
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.response_builders import build_user_response, build_user_responses_batch
from app.utils.security import hash_password
from app.utils.sql_search import like_pattern
from app.websocket.manager import manager

router = APIRouter()


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

    return {
        "items": build_user_responses_batch(users, db),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


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

    user = User(
        username=data.username,
        email=data.email or "",
        hashed_password=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        role_id=data.role_id,
        is_active=data.is_active,
    )
    db.add(user)
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

    # Değişiklikleri takip et
    old_role_id = user.role_id
    old_is_active = user.is_active

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
    if "password" in update_data:
        pwd = update_data.pop("password")
        if pwd:
            update_data["hashed_password"] = hash_password(pwd)
    for key, value in update_data.items():
        setattr(user, key, value)

    # Kullanıcı devre dışı bırakıldıysa → oturumu da kapat (tek commit)
    if old_is_active and not user.is_active:
        user.active_session_id = None

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "update", "user", entity_id=user_id, ip_address=client_ip)
    db.commit()

    # Devre dışı bırakma veya rol değişikliği bildirimlerini gönder
    if old_is_active and not user.is_active:
        background_tasks.add_task(
            manager.send_to_user,
            user_id,
            {"type": "force_logout", "reason": "account_disabled"},
        )
    elif user.role_id != old_role_id:
        background_tasks.add_task(
            manager.send_to_user,
            user_id,
            {"type": "permission_changed", "reason": "role_changed"},
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

    db.delete(user)
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
    """Admin tarafından kullanıcı şifresini sıfırla."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    user.hashed_password = hash_password(data.new_password)
    user.active_session_id = None  # Eski oturumu sonlandır

    # Kullanıcı online ise oturum sonlandı bildirimi gönder
    await manager.send_to_user(user_id, {
        "type": "session_expired",
        "reason": "Şifreniz sıfırlandığı için oturumunuz sonlandırıldı",
    })

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "reset_password", "user", entity_id=user_id, ip_address=client_ip)
    db.commit()

    return {"detail": "Şifre başarıyla sıfırlandı"}
