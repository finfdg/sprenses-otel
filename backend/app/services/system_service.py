"""Sistem (kullanıcı/rol/modül) domain servis katmanı — CRUD + cache invalidation + oturum (HTTP'siz).

D1-2 (2026-06-22): system.users/roles/modules mutasyon mantığı tek kaynakta. Router endpoint'leri
ve onay executor handler'ları ORTAK çağırır. Kapatılan gerçek drift'ler (executor router'dan sapıyordu):
- roles update: izin değişince **cache invalidate eksikti** → onaylı izin değişimi bayat kalıyordu;
- users update: devre-dışı bırakınca **oturum kapatma (active_session_id=None) eksikti** → onaylı
  pasifleştirmede kullanıcı login kalıyordu;
- roles/modules delete: executor **SOFT** (is_active=False), router **HARD** + bağımlı-guard idi.
WS bildirimleri HTTP-bağlamı (background_tasks) gerektirdiğinden router'da kalır; service flag döndürür.
"""
from sqlalchemy.orm import Session

from app.middleware.auth import invalidate_module_cache
from app.models.module import Module
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.utils.security import hash_password


# ─── Kullanıcılar ────────────────────────────────────────


def create_user(db: Session, data: dict) -> User:
    """Kullanıcı oluştur (şifre hash'lenir). İsim/e-posta benzersizliği çağıranda kontrol edilir."""
    pwd = data.get("password")
    user = User(
        username=data.get("username", ""),
        email=data.get("email") or "",
        hashed_password=hash_password(pwd) if pwd else "",
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name", ""),
        role_id=data.get("role_id"),
        is_active=data.get("is_active", True),
    )
    db.add(user)
    return user


def apply_user_update(db: Session, user: User, update_data: dict) -> dict:
    """Kullanıcı alanlarını uygula (e-posta None→'', şifre→hash, devre-dışı→oturum kapat).
    Döner: {'disabled': bool, 'role_changed': bool} — çağıran WS (FORCE_LOGOUT / PERMISSION_CHANGED) için."""
    data = dict(update_data)
    if "email" in data and data["email"] is None:
        data["email"] = ""
    if "password" in data:
        pwd = data.pop("password")
        if pwd:
            data["hashed_password"] = hash_password(pwd)
    old_role_id = user.role_id
    old_is_active = user.is_active
    old_email = user.email
    for key, value in data.items():
        if hasattr(user, key):
            setattr(user, key, value)
    # E-posta değiştiyse teyit durumunu sıfırla (yeni adres henüz doğrulanmadı)
    if user.email != old_email:
        user.email_verified = False
        user.email_verified_at = None
    disabled = old_is_active and not user.is_active
    if disabled:
        user.active_session_id = None  # devre dışı → oturumu kapat (router ile birebir)
    return {"disabled": disabled, "role_changed": user.role_id != old_role_id}


def delete_user(db: Session, user: User) -> None:
    """Kullanıcıyı sil (HARD). Kendini-silme/404 kontrolü çağıranda."""
    db.delete(user)


# ─── Roller ──────────────────────────────────────────────


def _set_role_permissions(db: Session, role_id: int, permissions: list) -> None:
    for perm in permissions:
        db.add(RoleModulePermission(
            role_id=role_id,
            module_id=perm.get("module_id"),
            can_view=perm.get("can_view", False),
            can_use=perm.get("can_use", False),
        ))


def create_role(db: Session, data: dict) -> Role:
    """Rol + izinleri oluştur. İsim benzersizliği çağıranda kontrol edilir."""
    role = Role(name=data.get("name", ""), description=data.get("description"))
    db.add(role)
    db.flush()
    _set_role_permissions(db, role.id, data.get("permissions") or [])
    return role


def apply_role_update(db: Session, role: Role, update_data: dict) -> bool:
    """Rol alanlarını + izinleri güncelle. İzin değiştiyse RBAC + mesajlaşma cache'lerini invalidate eder
    (eski executor BUNU ATLIYORDU → onaylı izin değişimi bayat kalıyordu). Döner: permissions_changed."""
    permissions = update_data.get("permissions")  # None = dokunma
    if update_data.get("name") is not None:
        role.name = update_data["name"]
    if update_data.get("description") is not None:
        role.description = update_data["description"]
    if update_data.get("is_active") is not None:
        role.is_active = update_data["is_active"]
    permissions_changed = permissions is not None
    if permissions_changed:
        db.query(RoleModulePermission).filter(RoleModulePermission.role_id == role.id).delete()
        db.flush()
        _set_role_permissions(db, role.id, permissions)
        invalidate_module_cache()
        # mesajlaşma rol-cache'i — cache state utils'te (router'a bağlanmaz)
        from app.utils.messaging_role_cache import invalidate_messaging_role_cache
        invalidate_messaging_role_cache()
    return permissions_changed


def delete_role(db: Session, role: Role) -> None:
    """Rolü sil (HARD) — role atanmış kullanıcı varsa ValueError (router 400'e çevirir)."""
    user_count = db.query(User).filter(User.role_id == role.id).count()
    if user_count > 0:
        raise ValueError(
            f"Bu role atanmış {user_count} kullanıcı var. Önce kullanıcıların rolünü değiştirin."
        )
    db.delete(role)


# ─── Modüller ────────────────────────────────────────────


def create_module(db: Session, data: dict) -> Module:
    """Modül oluştur + modül-kodu cache'ini invalidate et."""
    module = Module(
        name=data.get("name", ""),
        code=data.get("code", ""),
        description=data.get("description"),
        parent_id=data.get("parent_id"),
        sort_order=data.get("sort_order", 0),
        icon=data.get("icon"),
        is_active=data.get("is_active", True),
    )
    db.add(module)
    invalidate_module_cache()
    return module


def apply_module_update(db: Session, module: Module, update_data: dict) -> None:
    """Modül alanlarını uygula + cache invalidate. Kod-benzersizlik / döngü kontrolü çağıranda (HTTP)."""
    for key, value in update_data.items():
        if key.startswith("_"):
            continue
        if hasattr(module, key):
            setattr(module, key, value)
    invalidate_module_cache()


def delete_module(db: Session, module: Module) -> None:
    """Modülü sil (HARD) + cache invalidate — alt modülü varsa ValueError (router 400'e çevirir)."""
    child_count = db.query(Module).filter(Module.parent_id == module.id).count()
    if child_count > 0:
        raise ValueError(
            f"Bu modülün {child_count} alt modülü var. Önce alt modülleri silin veya taşıyın."
        )
    db.delete(module)
    invalidate_module_cache()
