"""Ortak response builder fonksiyonları — N+1 sorgusu olmadan."""

from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session, joinedload

from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.schemas.role import PermissionResponse
from app.schemas.user import ModulePermission, RoleBrief, UserResponse


def _build_permissions_for_role(role_id: int, perms: list) -> List[ModulePermission]:
    """Verilen izin listesinden ModulePermission listesi oluştur."""
    return [
        ModulePermission(
            module_code=p.module.code,
            module_name=p.module.name,
            can_view=p.can_view,
            can_use=p.can_use,
        )
        for p in perms
        if p.module is not None
    ]


def _user_to_response(user: User, permissions: List[ModulePermission]) -> UserResponse:
    """User nesnesini UserResponse'a dönüştür."""
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role_id=user.role_id,
        role=RoleBrief(id=user.role_rel.id, name=user.role_rel.name) if user.role_rel else None,
        is_active=user.is_active,
        created_at=user.created_at,
        last_online_at=user.last_online_at,
        permissions=permissions,
    )


def build_user_response(user: User, db: Session) -> UserResponse:
    """Kullanıcı yanıtı oluştur (tek sorguda izinler dahil)."""
    perms = (
        db.query(RoleModulePermission)
        .options(joinedload(RoleModulePermission.module))
        .filter(RoleModulePermission.role_id == user.role_id)
        .all()
    )
    permissions = _build_permissions_for_role(user.role_id, perms)
    return _user_to_response(user, permissions)


def build_user_responses_batch(users: List[User], db: Session) -> List[UserResponse]:
    """Birden fazla kullanıcı yanıtını toplu oluştur — N+1 sorgusu yok.

    Tüm kullanıcıların rol izinlerini tek sorguda çeker, ardından
    her kullanıcıya kendi rol izinlerini atar.
    """
    if not users:
        return []

    role_ids = list({u.role_id for u in users})
    all_perms = (
        db.query(RoleModulePermission)
        .options(joinedload(RoleModulePermission.module))
        .filter(RoleModulePermission.role_id.in_(role_ids))
        .all()
    )

    # Rol bazında izinleri grupla
    perms_by_role: Dict[int, list] = defaultdict(list)
    for p in all_perms:
        perms_by_role[p.role_id].append(p)

    return [
        _user_to_response(u, _build_permissions_for_role(u.role_id, perms_by_role.get(u.role_id, [])))
        for u in users
    ]


def _build_perm_responses(perms: list) -> List[PermissionResponse]:
    """RoleModulePermission listesini PermissionResponse listesine dönüştür."""
    return [
        PermissionResponse(
            module_id=p.module_id,
            module_code=p.module.code,
            module_name=p.module.name,
            can_view=p.can_view,
            can_use=p.can_use,
        )
        for p in perms
        if p.module is not None
    ]


def _role_to_dict(role, permissions: List[PermissionResponse]) -> dict:
    """Role nesnesini dict'e dönüştür."""
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "is_active": role.is_active,
        "created_at": role.created_at,
        "permissions": permissions,
    }


def build_role_response(role, db: Session) -> dict:
    """Rol yanıtı oluştur (tek sorguda izinler dahil)."""
    perms = (
        db.query(RoleModulePermission)
        .options(joinedload(RoleModulePermission.module))
        .filter(RoleModulePermission.role_id == role.id)
        .all()
    )
    return _role_to_dict(role, _build_perm_responses(perms))


def build_role_responses_batch(roles: list, db: Session) -> List[dict]:
    """Birden fazla rol yanıtını toplu oluştur — N+1 sorgusu yok."""
    if not roles:
        return []

    role_ids = [r.id for r in roles]
    all_perms = (
        db.query(RoleModulePermission)
        .options(joinedload(RoleModulePermission.module))
        .filter(RoleModulePermission.role_id.in_(role_ids))
        .all()
    )

    perms_by_role: Dict[int, list] = defaultdict(list)
    for p in all_perms:
        perms_by_role[p.role_id].append(p)

    return [
        _role_to_dict(r, _build_perm_responses(perms_by_role.get(r.id, [])))
        for r in roles
    ]
