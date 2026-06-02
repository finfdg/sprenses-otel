"""Mesajlaşılabilir kullanıcı listesi ve çevrimiçi durum endpoint'leri."""

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.conversation import Conversation, ConversationMember
from app.models.user import User
from app.routers.messages._helpers import _get_messaging_role_ids
from app.schemas.message import ChatUserResponse
from app.websocket.manager import manager

router = APIRouter()


# ─── Çevrimiçi Durumu ─────────────────────────────────────────────────


@router.get("/online")
def get_online_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "view")),
):
    """Kullanıcının konuşma arkadaşlarından çevrimiçi olanları döndür."""
    # Kullanıcının üye olduğu konuşmalardaki diğer üyeleri bul
    my_conv_ids = (
        db.query(ConversationMember.conversation_id)
        .filter(ConversationMember.user_id == current_user.id)
        .subquery()
    )
    partner_rows = (
        db.query(ConversationMember.user_id)
        .filter(
            ConversationMember.conversation_id.in_(my_conv_ids.select()),
            ConversationMember.user_id != current_user.id,
        )
        .distinct()
        .all()
    )
    partner_ids = [r.user_id for r in partner_rows]

    # Sadece konuşma arkadaşlarından online olanları döndür
    online_ids = manager.get_online_user_ids_by_list(partner_ids)
    return {"online_user_ids": online_ids}


# ─── Kullanıcı Listesi ────────────────────────────────────────────────


@router.get("/users", response_model=List[ChatUserResponse])
def list_chat_users(
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "view")),
):
    """Mesaj gönderilebilecek kullanıcıları listele (sadece messaging izni olanlar)."""
    # Messaging modülüne erişimi olan rol ID'leri
    allowed_role_ids = _get_messaging_role_ids(db)

    # Benim private konuşmalarımdaki karşı üyeleri tek sorguda al
    my_private_conv_ids = (
        db.query(ConversationMember.conversation_id)
        .join(Conversation, Conversation.id == ConversationMember.conversation_id)
        .filter(
            ConversationMember.user_id == current_user.id,
            Conversation.type == "private",
        )
        .subquery()
    )
    other_members_subq = (
        db.query(
            ConversationMember.user_id,
            ConversationMember.conversation_id,
        )
        .filter(
            ConversationMember.conversation_id.in_(my_private_conv_ids.select()),
            ConversationMember.user_id != current_user.id,
        )
        .subquery()
    )

    query = (
        db.query(User, other_members_subq.c.conversation_id)
        .outerjoin(other_members_subq, User.id == other_members_subq.c.user_id)
        .options(joinedload(User.role_rel))
        .filter(User.id != current_user.id, User.is_active == True)
    )

    # Messaging izni olan rollere sahip kullanıcıları filtrele
    if allowed_role_ids:
        query = query.filter(User.role_id.in_(allowed_role_ids))

    if search:
        s_clean = search.strip()[:100]
        s_escaped = s_clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{s_escaped}%"
        query = query.filter(
            or_(
                User.first_name.ilike(pattern, escape="\\"),
                User.last_name.ilike(pattern, escape="\\"),
                User.username.ilike(pattern, escape="\\"),
            )
        )

    rows = query.order_by(User.first_name).all()

    results = []
    for user, conv_id in rows:
        results.append(ChatUserResponse(
            id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            role_name=user.role_rel.name if user.role_rel else None,
            has_existing_conversation=conv_id is not None,
            conversation_id=conv_id,
        ))

    return results
