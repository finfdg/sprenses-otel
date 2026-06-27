"""Mesajlaşma rol-erişim TTL cache'i (altyapı katmanı).

Messaging modülüne `can_view` izni olan rol ID'leri 5 dakikalık TTL ile cache'lenir.
İzin matrisi değişince (`system_service`) invalidate edilir; mesajlaşma router'ı
(`messages/_helpers`) okur. Cache state'i bilinçli olarak router'dan ayrı `utils/`'te
tutulur ki service→router import yönü oluşmasın (servis bu modülü import edebilir).
"""
import time

from sqlalchemy.orm import Session

from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission

# TTL cache: messaging rol ID'leri (5 dakika)
_messaging_role_cache_ids: set = set()
_messaging_role_cache_ts: float = 0.0
_MESSAGING_ROLE_CACHE_TTL = 300  # 5 dakika


def invalidate_messaging_role_cache() -> None:
    """Cache'i sıfırla (izin değişiminde + testlerde kullanılır)."""
    global _messaging_role_cache_ids, _messaging_role_cache_ts
    _messaging_role_cache_ids = set()
    _messaging_role_cache_ts = 0.0


def get_messaging_role_ids(db: Session) -> set:
    """Messaging modülüne erişimi olan rol ID'lerini döndür (5dk TTL cache)."""
    global _messaging_role_cache_ids, _messaging_role_cache_ts
    now = time.time()
    if now - _messaging_role_cache_ts < _MESSAGING_ROLE_CACHE_TTL:
        return _messaging_role_cache_ids

    messaging_mod = db.query(Module).filter(Module.code == "messaging").first()
    if not messaging_mod:
        _messaging_role_cache_ids = set()
        _messaging_role_cache_ts = now
        return set()
    perm_rows = db.query(RoleModulePermission.role_id).filter(
        RoleModulePermission.module_id == messaging_mod.id,
        RoleModulePermission.can_view == True,
    ).all()
    result = {r.role_id for r in perm_rows}
    _messaging_role_cache_ids = result
    _messaging_role_cache_ts = now
    return result
