"""Internal API endpoint'leri — yalnızca sunucu içi kullanım (cron, script)."""

import logging
import secrets

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.constants import WSEvent
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal")


@router.post("/broadcast-finance-update")
async def broadcast_finance_update(
    request: Request,
    module: str = "exchange_rates",
    action: str = "update",
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
):
    """Tüm bağlı WebSocket client'larına finance_updated event'i gönder.

    Güvenlik: Yalnızca localhost (127.0.0.1 / ::1) + INTERNAL_SECRET header ile erişilebilir.
    """
    # Localhost kısıtı — dış ağdan erişim engellenir
    client_ip = request.client.host if request.client else ""
    if client_ip not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Yetkisiz erişim")

    if not secrets.compare_digest(x_internal_secret, settings.internal_secret):
        raise HTTPException(status_code=403, detail="Yetkisiz erişim")

    online_count = len(manager.get_online_user_ids())

    if online_count > 0:
        await manager.send_to_all({
            "type": WSEvent.FINANCE_UPDATED,
            "module": module,
            "action": action,
        })
        logger.info("[internal] finance_updated broadcast: module=%s action=%s online=%d", module, action, online_count)
    else:
        logger.info("[internal] finance_updated broadcast atlandı: kimse online değil")

    return {"ok": True, "online_users": online_count}
