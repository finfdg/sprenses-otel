"""Mesajlaşma modülü paylaşılan yardımcı fonksiyonlar."""

from datetime import datetime
from typing import List

import pytz
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import WSEvent
from app.models.conversation import Conversation, ConversationMember
from app.models.message import Message
from app.models.user import User
from app.schemas.message import GroupMemberBrief, MessageResponse, UserBrief
from app.websocket.manager import manager

tz_istanbul = pytz.timezone(settings.timezone)


def _user_brief(user: User) -> UserBrief:
    return UserBrief(
        id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )


def _member_brief(member: ConversationMember, user: User) -> GroupMemberBrief:
    return GroupMemberBrief(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        is_admin=member.is_admin,
    )


def _msg_response(msg: Message, include_sender_name: bool = False) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        content="Bu mesaj silindi" if msg.is_deleted else msg.content,
        message_type=msg.message_type,
        created_at=msg.created_at,
        is_edited=msg.is_edited,
        edited_at=msg.edited_at,
        is_deleted=msg.is_deleted,
        file_url=None if msg.is_deleted else msg.file_url,
        file_name=None if msg.is_deleted else msg.file_name,
        file_size=None if msg.is_deleted else msg.file_size,
        file_type=None if msg.is_deleted else msg.file_type,
        sender_name=(
            f"{msg.sender.first_name} {msg.sender.last_name}"
            if include_sender_name and msg.sender else None
        ),
    )


def _get_membership(db: Session, conversation_id: int, user_id: int) -> ConversationMember:
    """Kullanıcının konuşma üyeliğini getir, yoksa 404."""
    membership = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Konuşma bulunamadı")
    return membership


def _get_other_member_ids(db: Session, conversation_id: int, exclude_user_id: int) -> List[int]:
    """Konuşmadaki diğer üyelerin ID'lerini getir."""
    rows = (
        db.query(ConversationMember.user_id)
        .filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id != exclude_user_id,
        )
        .all()
    )
    return [r.user_id for r in rows]


def _restore_missing_members(db: Session, conversation_id: int, sender_id: int) -> None:
    """Private konuşmada silinen üyelikleri geri yükle.

    Bir kullanıcı konuşmayı sildiğinde ConversationMember satırı kaldırılır.
    Diğer kullanıcı mesaj gönderdiğinde, silinen kullanıcının üyeliği
    otomatik olarak yeniden oluşturulur ki mesaj ona da iletilsin.
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or conv.type != "private":
        return

    # Private konuşmanın iki kullanıcısını bul
    expected_user_ids = {conv.private_user_low, conv.private_user_high}
    if not expected_user_ids or None in expected_user_ids:
        return

    # Mevcut üyeleri kontrol et
    current_member_ids = {
        r.user_id for r in
        db.query(ConversationMember.user_id)
        .filter(ConversationMember.conversation_id == conversation_id)
        .all()
    }

    # Eksik üyeleri geri ekle
    missing_ids = expected_user_ids - current_member_ids
    for uid in missing_ids:
        db.add(ConversationMember(
            conversation_id=conversation_id,
            user_id=uid,
        ))

    if missing_ids:
        db.flush()


def _get_muted_user_ids(db: Session, conversation_id: int, user_ids: List[int]) -> set:
    """Konuşmayı susturmuş üyelerin ID'lerini döndür."""
    if not user_ids:
        return set()
    rows = db.query(ConversationMember.user_id).filter(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.user_id.in_(user_ids),
        ConversationMember.is_muted == True,
    ).all()
    return {r.user_id for r in rows}


# Messaging rol-erişim TTL cache'i artık altyapı katmanında (utils) —
# service→router import yönü oluşmaması için. Geriye uyum için re-export edilir.
from app.utils.messaging_role_cache import (  # noqa: E402
    get_messaging_role_ids as _get_messaging_role_ids,
)
from app.utils.messaging_role_cache import (  # noqa: E402
    invalidate_messaging_role_cache as _invalidate_messaging_role_cache,
)


def _broadcast_to_conversation(
    background_tasks: BackgroundTasks,
    db: Session,
    conversation_id: int,
    sender_id: int,
    event: dict,
):
    """Konuşmadaki tüm üyelere (gönderen hariç) WS event gönder."""
    member_ids = _get_other_member_ids(db, conversation_id, sender_id)
    if member_ids:
        background_tasks.add_task(manager.send_to_users, member_ids, event)


def _create_system_message(db: Session, conversation_id: int, sender_id: int, content: str) -> Message:
    """Sistem mesajı oluştur."""
    msg = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        content=content,
        message_type="system",
    )
    db.add(msg)
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.updated_at = datetime.now(tz_istanbul)
    return msg


def _build_new_message_event(msg: Message, sender: User, conversation_id: int) -> dict:
    """Yeni mesaj WS event'i oluştur (send_message ve upload_file ortak)."""
    return {
        "type": WSEvent.NEW_MESSAGE,
        "conversation_id": conversation_id,
        "message": {
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "sender_id": msg.sender_id,
            "content": msg.content,
            "message_type": msg.message_type,
            "created_at": str(msg.created_at),
            "is_edited": msg.is_edited,
            "edited_at": str(msg.edited_at) if msg.edited_at else None,
            "is_deleted": msg.is_deleted,
            "file_url": msg.file_url,
            "file_name": msg.file_name,
            "file_size": msg.file_size,
            "file_type": msg.file_type,
            "sender_name": f"{sender.first_name} {sender.last_name}",
        },
        "sender": {
            "id": sender.id,
            "first_name": sender.first_name,
            "last_name": sender.last_name,
            "username": sender.username,
        }
    }


def _get_group_members(db: Session, conversation_id: int) -> List[GroupMemberBrief]:
    """Grup üyelerini getir."""
    rows = (
        db.query(ConversationMember, User)
        .join(User, User.id == ConversationMember.user_id)
        .filter(ConversationMember.conversation_id == conversation_id)
        .order_by(User.first_name)
        .all()
    )
    return [_member_brief(m, u) for m, u in rows]
