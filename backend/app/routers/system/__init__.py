"""Sistem paketi — system.* RBAC modülünün router'ları (/api/system altında).

users · roles · modules · server · backup · docs · denetim · audit_logs · error_logs.
Önek ve OpenAPI etiketleri 2026-09-02 yeniden yapılandırmasından ÖNCEKİ main.py kablolamasıyla
birebir aynıdır (tests/test_route_manifest.py bunu dondurur). Onay akışı (`app.routers.approval`)
kardeş paket olarak /api/system/approval'da kalır.
"""
from fastapi import APIRouter

from app.routers.system import audit_logs, backup, denetim, docs, error_logs, modules, roles, server, users

router = APIRouter()
router.include_router(users.router, prefix="/users", tags=["system-users"])
router.include_router(roles.router, prefix="/roles", tags=["system-roles"])
router.include_router(modules.router, prefix="/modules", tags=["system-modules"])
router.include_router(server.router, tags=["system-server"])
router.include_router(backup.router, tags=["system-backup"])
router.include_router(docs.router, prefix="/docs", tags=["system-docs"])
router.include_router(denetim.router, prefix="/denetim", tags=["system-denetim"])
router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit"])
router.include_router(error_logs.router, prefix="/error-logs", tags=["error-logs"])
