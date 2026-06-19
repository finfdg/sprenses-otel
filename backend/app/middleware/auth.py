import threading
from typing import Dict, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.utils.security import decode_access_token

# auto_error=False: Cookie varsa Bearer header zorunlu olmasın
security = HTTPBearer(auto_error=False)

# ── Modül kodu → id cache (nadiren değişir) ─────────────────
_module_code_cache: Dict[str, int] = {}
_module_cache_lock = threading.Lock()


def _get_module_id(db: Session, module_code: str) -> Optional[int]:
    """Modül kodundan ID'yi döndür — cache ile."""
    if module_code in _module_code_cache:
        return _module_code_cache[module_code]

    # is_active filtresi: pasif (ör. onayla soft-delete) modül izin vermemeli. Yalnız aktif
    # modüller cache'lenir; soft-delete sonrası handler invalidate_module_cache() çağırır.
    module = (
        db.query(Module.id)
        .filter(Module.code == module_code, Module.is_active.is_(True))
        .first()
    )
    if module:
        with _module_cache_lock:
            _module_code_cache[module_code] = module.id
        return module.id
    return None


def invalidate_module_cache():
    """Modül cache'ini temizle — modül CRUD işlemlerinde çağır."""
    with _module_cache_lock:
        _module_code_cache.clear()

COOKIE_NAME = "access_token"


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token: Optional[str] = None

    # 1. Önce Bearer header'dan token'ı al
    if credentials:
        token = credentials.credentials

    # 2. Header yoksa HttpOnly cookie'den al
    if not token:
        token = request.cookies.get(COOKIE_NAME)

    # NOT: Query-param token fallback'i (?token=JWT) GÜVENLİK NEDENİYLE KALDIRILDI
    # (2026-06-19). Tam yetkili JWT, URL üzerinden nginx access log'una, tarayıcı
    # geçmişine ve Referer başlığına sızıyordu. Frontend artık PDF'leri cookie ile
    # (credentials: 'include' → fetchRaw/blob indirme) çekiyor; query-param token
    # hiçbir yerde kullanılmıyordu (ölü + riskli kod).

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kimlik doğrulama gerekli")

    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token")
        user_id = int(sub)
        token_session_id = payload.get("session_id")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token")

    user = (
        db.query(User)
        .options(joinedload(User.role_rel))
        .filter(User.id == user_id)
        .first()
    )
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı bulunamadı")

    # Rol pasifleştirilmişse (ör. onayla soft-delete) erişim kaldırılır. Eskiden izin kontrolü
    # Role.is_active'e bakmadığından, "silinmiş" rolün kullanıcıları tüm izinleri kullanmaya
    # devam ediyordu (güvenlik açığı). role_rel zaten joinedload ile yüklü — ek sorgu yok.
    if user.role_rel is not None and not user.role_rel.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Rolünüz pasifleştirilmiş, erişiminiz kaldırıldı",
        )

    # Tek oturum kontrolü: JWT'deki session_id, DB'deki active_session_id ile eşleşmeli
    # active_session_id None ise kullanıcı çıkış yapmış demektir — erişim reddedilmeli
    if user.active_session_id is None or token_session_id != user.active_session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturumunuz sonlandırılmış, lütfen tekrar giriş yapın",
        )

    return user


def require_permission(module_code: str, action: str = "view"):
    """
    Factory that returns a dependency checking if the current user's role
    has the specified permission on the given module.

    Modül kodu → ID dönüşümü cache'lenir (JOIN yerine basit filtre).
    """
    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        module_id = _get_module_id(db, module_code)
        if module_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işlem için yetkiniz yok",
            )

        permission = (
            db.query(RoleModulePermission)
            .filter(
                RoleModulePermission.role_id == current_user.role_id,
                RoleModulePermission.module_id == module_id,
            )
            .first()
        )

        if not permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işlem için yetkiniz yok",
            )

        action_map = {
            "view": permission.can_view,
            "use": permission.can_use,
        }

        if not action_map.get(action, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işlem için yetkiniz yok",
            )

        return current_user

    return dependency


def user_can(db: Session, user: User, module_code: str, action: str = "view") -> bool:
    """Programatik izin kontrolü — require_permission'ın dependency olmayan sürümü.

    Birden çok modülün iznini tek istekte kontrol etmek gerektiğinde kullanılır
    (ör. merkezi Sedna sync, izni olan adımları çalıştırır)."""
    module_id = _get_module_id(db, module_code)
    if module_id is None:
        return False
    permission = (
        db.query(RoleModulePermission)
        .filter(
            RoleModulePermission.role_id == user.role_id,
            RoleModulePermission.module_id == module_id,
        )
        .first()
    )
    if not permission:
        return False
    return bool(permission.can_use if action == "use" else permission.can_view)
