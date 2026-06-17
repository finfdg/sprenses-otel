import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.database import SessionLocal
from app.middleware.auth import COOKIE_NAME
from app.models.conversation import ConversationMember
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.utils.security import decode_access_token
from app.websocket.manager import manager

# Typing event rate limiting: kullanıcı başına en az 500ms aralık
_typing_timestamps: Dict[int, float] = {}
TYPING_MIN_INTERVAL = 0.5
_TYPING_CLEANUP_THRESHOLD = 500  # Bu eşiği aşınca temizlik yap

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── DB yardımcıları (senkron — to_thread ile çağrılır) ─────────────


def _sync_get_conversation_partners(user_id: int) -> List[int]:
    """Kullanıcının konuşma yaptığı tüm kişilerin ID'lerini getir."""
    db = SessionLocal()
    try:
        my_conv_ids = (
            db.query(ConversationMember.conversation_id)
            .filter(ConversationMember.user_id == user_id)
            .subquery()
        )
        rows = (
            db.query(ConversationMember.user_id)
            .filter(
                ConversationMember.conversation_id.in_(my_conv_ids.select()),
                ConversationMember.user_id != user_id,
            )
            .distinct()
            .all()
        )
        return [r.user_id for r in rows]
    finally:
        db.close()


def _sync_verify_user_active(user_id: int) -> bool:
    """Kullanıcının aktif olup olmadığını kontrol et."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        return user is not None
    finally:
        db.close()


def _sync_verify_user_session(user_id: int, session_id: Optional[str]) -> bool:
    """Kullanıcının aktif oturum kimliğini doğrula (HTTP get_current_user ile birebir).

    active_session_id None ise kullanıcı çıkış yapmış demektir → reddedilir.
    (Eskiden WS yolu None'ı 'kabul et' sayıyordu; HTTP yolu reddediyordu — bu tutarsızlık
    çıkış yapmış bir kullanıcının süresi dolmamış JWT'siyle WS'e yeniden bağlanmasına izin
    veriyordu. Artık iki yol da aynı.)
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            return False
        if user.active_session_id is None or session_id != user.active_session_id:
            return False
        return True
    finally:
        db.close()


def _sync_is_conversation_member(conversation_id: int, user_id: int) -> bool:
    """Kullanıcının konuşmaya üye olup olmadığını kontrol et."""
    db = SessionLocal()
    try:
        exists = (
            db.query(ConversationMember.id)
            .filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
            .first()
        )
        return exists is not None
    finally:
        db.close()


def _sync_get_conversation_member_ids(conversation_id: int, exclude_user_id: int) -> List[int]:
    """Konuşmadaki diğer üyelerin ID'lerini veritabanından al."""
    db = SessionLocal()
    try:
        rows = (
            db.query(ConversationMember.user_id)
            .filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id != exclude_user_id,
            )
            .all()
        )
        return [r.user_id for r in rows]
    finally:
        db.close()


def _sync_has_messaging_permission(user_id: int) -> bool:
    """Kullanıcının messaging modülüne can_use izni olup olmadığını kontrol et."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user or not user.role_id:
            return False
        messaging_mod = db.query(Module).filter(Module.code == "messaging").first()
        if not messaging_mod:
            return False
        perm = (
            db.query(RoleModulePermission)
            .filter(
                RoleModulePermission.role_id == user.role_id,
                RoleModulePermission.module_id == messaging_mod.id,
                RoleModulePermission.can_use == True,
            )
            .first()
        )
        return perm is not None
    finally:
        db.close()


# ─── Online durum broadcast callback ─────────────────────────────────


def _sync_update_last_online(user_id: int) -> None:
    """Kullanıcı offline olduğunda last_online_at güncelle."""
    db = SessionLocal()
    try:
        from datetime import datetime

        import pytz
        tz = pytz.timezone("Europe/Istanbul")
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.last_online_at = datetime.now(tz)
            db.commit()
    except Exception as e:
        logger.debug("last_online_at güncelleme hatası user_id=%d: %s", user_id, e)
        db.rollback()
    finally:
        db.close()


def _sync_get_online_users_info(user_ids: list) -> list:
    """Online kullanıcıların id ve adlarını getir."""
    if not user_ids:
        return []
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        return [{"id": u.id, "name": u.full_name} for u in users]
    finally:
        db.close()


def _sync_get_user_name(user_id: int) -> str:
    """Kullanıcı adını getir."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        return user.full_name if user else ""
    finally:
        db.close()


async def _on_user_status_change(user_id: int, is_online: bool) -> None:
    """Kullanıcı online/offline olduğunda TÜM bağlı kullanıcılara bildir."""
    try:
        user_name = await asyncio.to_thread(_sync_get_user_name, user_id)
        event = {
            "type": "user_status",
            "user_id": user_id,
            "is_online": is_online,
            "user_name": user_name,
        }
        await manager.send_to_all(event)

        # Offline olduğunda last_online_at güncelle
        if not is_online:
            await asyncio.to_thread(_sync_update_last_online, user_id)
    except Exception as e:
        logger.debug("Online durum broadcast hatası user_id=%d: %s", user_id, e)


# Callback'i manager'a kaydet
manager.set_status_change_callback(_on_user_status_change)


# ─── Auth yardımcıları ────────────────────────────────────────────────


def authenticate_ws_token(token: str) -> Optional[tuple]:
    """JWT token doğrula ve (user_id, session_id) döndür. Geçersizse None döner."""
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if sub is None:
            return None
        session_id = payload.get("session_id")
        return (int(sub), session_id)
    except (JWTError, ValueError):
        return None


# ─── WebSocket endpoint ───────────────────────────────────────────────


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint. Kimlik doğrulama:
    1. Önce HttpOnly cookie'den token okunur (upgrade request ile gönderilir)
    2. Cookie yoksa bağlantı sonrası auth mesajı ile fallback yapılır

    Bağlantı sonrası sunucu event'leri client'a gönderir.
    Client typing gibi event'leri sunucuya gönderebilir.
    """
    user_id: Optional[int] = None

    await websocket.accept()

    # 1. Önce cookie'den auth dene (HttpOnly cookie upgrade request'te gönderilir)
    auth_result: Optional[tuple] = None
    cookie_token = websocket.cookies.get(COOKIE_NAME)
    if cookie_token:
        auth_result = authenticate_ws_token(cookie_token)

    # 2. Cookie yoksa veya geçersizse, auth mesajı bekle (fallback)
    if auth_result is None:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            event = json.loads(raw)
            if event.get("type") != "auth" or not event.get("token"):
                await websocket.close(code=4001, reason="Auth mesajı gerekli")
                return
            auth_result = authenticate_ws_token(event["token"])
            if auth_result is None:
                await websocket.close(code=4001, reason="Geçersiz token")
                return
        except asyncio.TimeoutError:
            await websocket.close(code=4001, reason="Auth zaman aşımı")
            return
        except (json.JSONDecodeError, Exception) as e:
            logger.debug("WebSocket auth hatası: %s", e)
            await websocket.close(code=4001, reason="Auth hatası")
            return

    user_id, session_id = auth_result

    # Oturum kimliği doğrulaması
    try:
        is_valid_session = await asyncio.to_thread(_sync_verify_user_session, user_id, session_id)
        if not is_valid_session:
            try:
                await websocket.send_text(json.dumps({
                    "type": "session_expired",
                    "reason": "Oturumunuz başka bir cihazdan sonlandırıldı",
                }))
            except Exception:
                pass
            await websocket.close(code=4002, reason="Oturum sonlandırıldı")
            return
    except Exception as e:
        logger.debug("WebSocket session doğrulama hatası: %s", e)
        await websocket.close(code=4001, reason="Auth hatası")
        return

    # Auth mesajı ile bağlanıldı — websocket zaten accepted
    await manager.connect_raw(user_id, websocket)

    # Bağlantı onayı gönder — tüm online kullanıcı listesi dahil
    try:
        all_online_ids = list(manager.get_online_user_ids())
        # Online kullanıcı adlarını getir
        online_users_info = await asyncio.to_thread(_sync_get_online_users_info, all_online_ids)
        await websocket.send_text(json.dumps({
            "type": "connected",
            "user_id": user_id,
            "online_user_ids": all_online_ids,
            "online_users": online_users_info,
        }))
    except Exception as e:
        logger.debug("WebSocket bağlantı onayı gönderilemedi: %s", e)
        await manager.disconnect(user_id, websocket)
        return

    # Client'tan gelen mesajları dinle
    try:
        while True:
            data = await websocket.receive_text()
            try:
                event = json.loads(data)
                await handle_client_event(user_id, event, websocket)
            except json.JSONDecodeError as e:
                logger.debug("WebSocket geçersiz JSON: %s", e)
    except WebSocketDisconnect:
        logger.debug("WebSocket bağlantısı kesildi: user_id=%d", user_id)
    except Exception as e:
        logger.debug("WebSocket hatası: user_id=%d, hata=%s", user_id, e)
    finally:
        await manager.disconnect(user_id, websocket)


# ─── Client event handler ─────────────────────────────────────────────


async def handle_client_event(user_id: int, event: dict, websocket: Optional[WebSocket] = None) -> None:
    """
    Client'tan sunucuya gelen event'leri işle.
    Typing göstergesi: private (target_user_id) ve grup (conversation_id) destekli.
    """
    event_type = event.get("type")

    if event_type == "typing":
        # Messaging izin kontrolü — rolü değişen kullanıcılar WS üzerinden işlem yapamamalı
        has_perm = await asyncio.to_thread(_sync_has_messaging_permission, user_id)
        if not has_perm:
            return

        conversation_id = event.get("conversation_id")
        target_user_id = event.get("target_user_id")
        is_typing = event.get("is_typing", True)

        # conversation_id zorunlu ve geçerli olmalı
        if not conversation_id or not isinstance(conversation_id, int):
            return

        # Typing rate limiting — çok sık typing event'i engelle
        now = time.time()
        if now - _typing_timestamps.get(user_id, 0.0) < TYPING_MIN_INTERVAL:
            return
        _typing_timestamps[user_id] = now

        # Bellek sızıntısını önle — eski girişleri periyodik temizle
        if len(_typing_timestamps) > _TYPING_CLEANUP_THRESHOLD:
            stale = [k for k, v in _typing_timestamps.items() if now - v > 60]
            for k in stale:
                del _typing_timestamps[k]

        # Üyelik kontrolü — kullanıcı bu konuşmaya üye mi? (async)
        is_member = await asyncio.to_thread(_sync_is_conversation_member, conversation_id, user_id)
        if not is_member:
            return

        typing_event = {
            "type": "typing",
            "conversation_id": conversation_id,
            "user_id": user_id,
            "is_typing": is_typing,
        }

        if target_user_id:
            # Private konuşma: hedef kullanıcının da bu konuşmada olduğunu doğrula
            if not isinstance(target_user_id, int):
                return
            target_is_member = await asyncio.to_thread(
                _sync_is_conversation_member, conversation_id, target_user_id
            )
            if not target_is_member:
                return
            await manager.send_to_user(target_user_id, typing_event)
        else:
            # Grup konuşma: tüm üyelere gönder
            member_ids = await asyncio.to_thread(
                _sync_get_conversation_member_ids, conversation_id, user_id
            )
            if member_ids:
                await manager.send_to_users(member_ids, typing_event)

    elif event_type == "visibility":
        # Sayfa görünürlük durumu — arka plan push bildirimi için
        visible = event.get("visible")
        if isinstance(visible, bool) and websocket is not None:
            await manager.set_visibility(user_id, websocket, visible)

    elif event_type == "ping":
        # Client keepalive — yanıt gerekmez
        pass
