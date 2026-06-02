import asyncio
import json
import logging
from typing import Callable, Dict, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Aktif WebSocket bağlantılarını user_id bazında yönetir."""

    def __init__(self):
        # user_id -> WebSocket bağlantı listesi (birden fazla sekme destekli)
        self._connections: Dict[int, List[WebSocket]] = {}
        # Arka plandaki (görünürlüğü hidden) bağlantılar
        self._background_connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        # Online durum değişikliğinde çağrılacak callback
        self._on_status_change: Optional[Callable] = None
        # Ana event loop referansı (ilk WS bağlantısında yakalanır)
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_status_change_callback(self, callback: Callable) -> None:
        """Online/offline durum değişikliğinde çağrılacak async callback ayarla."""
        self._on_status_change = callback

    def _safe_ensure_future(self, coro) -> None:
        """asyncio.ensure_future ile güvenli hata yakalama."""
        task = asyncio.ensure_future(coro)
        task.add_done_callback(self._handle_task_exception)

    @staticmethod
    def _handle_task_exception(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Arka plan görevi hatası: %s", exc)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        # Ana event loop referansını yakala
        if self._main_loop is None:
            self._main_loop = asyncio.get_event_loop()
        async with self._lock:
            was_offline = user_id not in self._connections or not self._connections[user_id]
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(websocket)
        # İlk bağlantı — kullanıcı online oldu
        if was_offline and self._on_status_change:
            self._safe_ensure_future(self._on_status_change(user_id, True))

    async def connect_raw(self, user_id: int, websocket: WebSocket) -> None:
        """Zaten accept edilmiş WebSocket'i ekle (auth mesajı sonrası)."""
        if self._main_loop is None:
            self._main_loop = asyncio.get_event_loop()
        async with self._lock:
            was_offline = user_id not in self._connections or not self._connections[user_id]
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(websocket)
        if was_offline and self._on_status_change:
            self._safe_ensure_future(self._on_status_change(user_id, True))

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if user_id in self._connections:
                try:
                    self._connections[user_id].remove(websocket)
                except ValueError:
                    pass
                if not self._connections[user_id]:
                    del self._connections[user_id]
            # Arka plan takibini temizle
            if user_id in self._background_connections:
                self._background_connections[user_id].discard(websocket)
                if not self._background_connections[user_id]:
                    del self._background_connections[user_id]
            is_now_offline = user_id not in self._connections
        # Son bağlantı da koptu — kullanıcı offline oldu
        if is_now_offline and self._on_status_change:
            self._safe_ensure_future(self._on_status_change(user_id, False))

    async def set_visibility(self, user_id: int, websocket: WebSocket, visible: bool) -> None:
        """Belirli bir bağlantının görünürlük durumunu güncelle."""
        async with self._lock:
            if not visible:
                if user_id not in self._background_connections:
                    self._background_connections[user_id] = set()
                self._background_connections[user_id].add(websocket)
            else:
                if user_id in self._background_connections:
                    self._background_connections[user_id].discard(websocket)
                    if not self._background_connections[user_id]:
                        del self._background_connections[user_id]

    def is_background(self, user_id: int) -> bool:
        """Kullanıcının TÜM bağlantıları arka planda mı kontrol et."""
        if user_id not in self._connections or not self._connections[user_id]:
            return False  # Çevrimdışı — arka plan değil
        active = set(self._connections[user_id])
        bg = self._background_connections.get(user_id, set())
        return active.issubset(bg)

    def is_online(self, user_id: int) -> bool:
        return user_id in self._connections and len(self._connections[user_id]) > 0

    def get_online_user_ids(self) -> Set[int]:
        return set(self._connections.keys())

    async def send_to_user(self, user_id: int, event: dict) -> None:
        """Belirli bir kullanıcının tüm bağlantılarına JSON event gönder."""
        if user_id not in self._connections:
            return
        message = json.dumps(event, default=str)
        dead_connections = []
        for ws in self._connections.get(user_id, []):
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning("WebSocket gönderim hatası user_id=%d: %s", user_id, e)
                dead_connections.append(ws)
        # Ölü bağlantıları temizle
        for ws in dead_connections:
            await self.disconnect(user_id, ws)

    async def send_to_users(self, user_ids: List[int], event: dict) -> None:
        """Birden fazla kullanıcıya paralel event gönder."""
        if not user_ids:
            return
        await asyncio.gather(
            *(self.send_to_user(uid, event) for uid in user_ids),
            return_exceptions=True,
        )

    async def send_to_all(self, event: dict) -> None:
        """Tüm bağlı kullanıcılara event gönder."""
        for uid in list(self._connections.keys()):
            await self.send_to_user(uid, event)

    def get_online_user_ids_by_list(self, user_ids: List[int]) -> List[int]:
        """Verilen kullanıcı listesinden online olanları döndür."""
        return [uid for uid in user_ids if uid in self._connections and len(self._connections[uid]) > 0]

    def send_to_user_sync(self, user_id: int, event: dict) -> None:
        """Belirli kullanıcıya event gönder (thread-safe, sync context)."""
        if user_id not in self._connections or not self._main_loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.send_to_user(user_id, event),
                self._main_loop,
            )
        except Exception as e:
            logger.debug("Sync WS kullanıcı gönderim hatası uid=%d: %s", user_id, e)

    def send_to_all_sync(self, event: dict) -> None:
        """Tüm bağlı kullanıcılara event gönder (thread-safe, sync context'ten çağrılır).

        FastAPI sync endpoint'ler ayrı thread'de çalışır. Bu metod
        ana event loop'a thread-safe şekilde coroutine ekler.
        """
        if not self._connections or not self._main_loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.send_to_all(event),
                self._main_loop,
            )
        except Exception as e:
            logger.debug("Sync WS broadcast hatası: %s", e)


# Singleton instance
manager = ConnectionManager()
