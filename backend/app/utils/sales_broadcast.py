"""Satış modülü WS broadcast yardımcısı.

Otel rezervasyon vb. satış işlemlerinde tüm bağlı kullanıcılara
'sales_updated' event'i gönderir. Frontend bu event'i dinleyerek
ilgili sayfaları otomatik yeniler.

Debounce mekanizması: Aynı istek döngüsünde (background_tasks) aynı modülden
birden fazla broadcast çağrısı gelirse yalnızca tekini gönderir.
Toplu Excel yüklemelerinde (500 satır = 500 broadcast yerine 1 broadcast) bunu önler.
"""
import asyncio
import logging
from typing import Set

from fastapi import BackgroundTasks

from app.constants import WSEvent
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

# Mevcut arka plan görev döngüsünde bekleyen modüller (debounce takibi)
_pending_modules: Set[str] = set()
_debounce_lock = asyncio.Lock()


async def _debounced_send(module: str, action: str) -> None:
    """500ms bekle, sonra gönder. Bu sürede aynı modülden gelen diğer çağrılar iptal edilir."""
    await asyncio.sleep(0.5)
    async with _debounce_lock:
        if module not in _pending_modules:
            return  # Başkası gönderdi, atla
        _pending_modules.discard(module)

    try:
        await manager.send_to_all({
            "type": WSEvent.SALES_UPDATED,
            "module": module,
            "action": action,
        })
    except Exception as e:
        logger.error("sales_broadcast hatası module=%s: %s", module, e)


def broadcast_sales_update(
    background_tasks: BackgroundTasks,
    module: str,
    action: str = "update",
) -> None:
    """Tüm bağlı kullanıcılara satış güncelleme event'i gönder.

    Debounce: Aynı modülden 500ms içinde gelen birden fazla çağrı tek event'e indirilir.

    Args:
        background_tasks: FastAPI BackgroundTasks
        module: Güncellenen modül (hotel_reservation)
        action: İşlem türü (upload, delete, update)
    """
    _pending_modules.add(module)
    background_tasks.add_task(_debounced_send, module, action)
