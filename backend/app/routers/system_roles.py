"""Sistem rol yönetimi — CRUD ve izin matrisi."""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.constants import WSEvent
from app.database import get_db
from app.middleware.auth import invalidate_module_cache, require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.routers.messages._helpers import _invalidate_messaging_role_cache
from app.schemas.role import RoleCreate, RoleResponse, RoleUpdate
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.response_builders import build_role_response, build_role_responses_batch
from app.websocket.manager import manager

router = APIRouter()


@router.get("/", response_model=List[RoleResponse])
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.roles", "view")),
):
    roles = db.query(Role).order_by(Role.name).all()
    return build_role_responses_batch(roles, db)


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.roles", "view")),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol bulunamadı")
    return build_role_response(role, db)


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(
    data: RoleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.roles", "use")),
):
    existing = db.query(Role).filter(Role.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Bu rol adı zaten mevcut!")

    approval_resp = check_approval(db, "system.roles", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    role = Role(name=data.name, description=data.description)
    db.add(role)
    db.flush()

    # Add permissions
    for perm in data.permissions:
        rmp = RoleModulePermission(
            role_id=role.id,
            module_id=perm.module_id,
            can_view=perm.can_view,
            can_use=perm.can_use,
        )
        db.add(rmp)

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "create", "role", entity_id=role.id, ip_address=client_ip)
    db.commit()
    db.refresh(role)
    return build_role_response(role, db)


@router.patch("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    data: RoleUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.roles", "use")),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol bulunamadı")

    approval_resp = check_approval(db, "system.roles", role_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp

    # İsim değişiyorsa benzersizlik kontrolü
    if data.name is not None and data.name != role.name:
        existing = db.query(Role).filter(Role.name == data.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="Bu rol adı zaten mevcut!")
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.is_active is not None:
        role.is_active = data.is_active

    permissions_changed = False

    # Replace permissions if provided
    if data.permissions is not None:
        permissions_changed = True
        db.query(RoleModulePermission).filter(
            RoleModulePermission.role_id == role.id
        ).delete()
        for perm in data.permissions:
            rmp = RoleModulePermission(
                role_id=role.id,
                module_id=perm.module_id,
                can_view=perm.can_view,
                can_use=perm.can_use,
            )
            db.add(rmp)

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "update", "role", entity_id=role_id, ip_address=client_ip)
    db.commit()
    db.refresh(role)

    # İzinler değiştiyse: backend cache'lerini invalidate et + online kullanıcılara bildir
    if permissions_changed:
        # Backend cache'leri sıfırla — yoksa /api/messages/users 5 dk eski izinle çalışır,
        # require_permission da modül cache'inde eski değerleri tutar.
        _invalidate_messaging_role_cache()
        invalidate_module_cache()

        affected_user_ids = [
            u.id for u in db.query(User.id).filter(User.role_id == role_id).all()
        ]
        online_ids = manager.get_online_user_ids_by_list(affected_user_ids)
        if online_ids:
            background_tasks.add_task(
                manager.send_to_users,
                online_ids,
                {"type": WSEvent.PERMISSION_CHANGED, "reason": "role_updated"},
            )

    return build_role_response(role, db)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.roles", "use")),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol bulunamadı")

    approval_resp = check_approval(db, "system.roles", role_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    # Check if users are assigned to this role
    user_count = db.query(User).filter(User.role_id == role_id).count()
    if user_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Bu role atanmış {user_count} kullanıcı var. Önce kullanıcıların rolünü değiştirin."
        )
    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "delete", "role", entity_id=role_id, ip_address=client_ip)
    db.delete(role)
    db.commit()
