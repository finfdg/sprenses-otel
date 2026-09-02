"""Çekirdek paketi — kimlik, sağlık, WebSocket, push, bildirim, dosya sunumu ve iç uçlar.

`router` /api altına takılır (health, auth/, ws, push/, notifications/); `files_router`
(/uploads/{path}, öneksiz) ve `internal_router` (kendi /api/internal öneki) ayrıca dışa verilir.
`ws` modülü import anında presence callback'ini kaydeder — bu import BİLEREK eager'dır.
Etiketler/önekler yeniden yapılandırma öncesi main.py ile birebir aynıdır.
"""
from fastapi import APIRouter

from app.routers.core import (  # ws: import-anı yan etkisi bilinçli
    auth,
    files,
    health,
    internal,
    notifications,
    push,
    ws,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(ws.router, tags=["websocket"])
router.include_router(push.router, prefix="/push", tags=["push"])
router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])

files_router = APIRouter()
files_router.include_router(files.router, tags=["files"])

internal_router = APIRouter()
internal_router.include_router(internal.router, tags=["internal"])
