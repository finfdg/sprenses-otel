"""Konuşma CRUD endpoint'leri."""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import Session, aliased, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.conversation import Conversation, ConversationMember
from app.models.message import Message
from app.models.user import User
from app.schemas.message import (
    ConversationCreate,
    ConversationDetailResponse,
    ConversationResponse,
    MuteUpdate,
    UnreadCountResponse,
)
from app.utils.audit import log_action
from app.utils.file_upload import UPLOAD_DIR
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

from app.routers.messages._helpers import (
    _get_group_members,
    _get_membership,
    _get_other_member_ids,
    _msg_response,
    _user_brief,
    tz_istanbul,
)

router = APIRouter()


# ─── Konuşma Listesi ──────────────────────────────────────────────────


@router.get("/conversations", response_model=List[ConversationResponse])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "view")),
):
    """Kullanıcının tüm konuşmalarını listele (private + grup)."""

    # Kullanıcının üye olduğu tüm konuşmaları al
    my_memberships = (
        db.query(ConversationMember)
        .filter(ConversationMember.user_id == current_user.id)
        .all()
    )
    if not my_memberships:
        return []

    conv_ids = [m.conversation_id for m in my_memberships]
    membership_map = {m.conversation_id: m for m in my_memberships}

    # Konuşmaları al
    convs = (
        db.query(Conversation)
        .filter(Conversation.id.in_(conv_ids))
        .order_by(desc(Conversation.updated_at))
        .all()
    )

    # Son mesajları tek sorguda al
    last_msg_subq = (
        db.query(
            Message.conversation_id,
            func.max(Message.id).label("max_id"),
        )
        .filter(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    last_messages_rows = (
        db.query(Message)
        .join(last_msg_subq, Message.id == last_msg_subq.c.max_id)
        .options(joinedload(Message.sender))
        .all()
    )
    last_msg_map = {m.conversation_id: m for m in last_messages_rows}

    # Okunmamış sayıları tek sorguda al
    # joined_at filtresi: Gruba sonradan eklenen üyeler eklenmeden önceki mesajları saymasın
    unread_rows = (
        db.query(
            Message.conversation_id,
            func.count(Message.id).label("unread"),
        )
        .join(ConversationMember, and_(
            ConversationMember.conversation_id == Message.conversation_id,
            ConversationMember.user_id == current_user.id,
        ))
        .filter(
            Message.conversation_id.in_(conv_ids),
            Message.sender_id != current_user.id,
            Message.is_deleted == False,
            Message.created_at >= ConversationMember.joined_at,
            or_(
                ConversationMember.last_read_at.is_(None),
                Message.created_at > ConversationMember.last_read_at,
            ),
        )
        .group_by(Message.conversation_id)
        .all()
    )
    unread_map = {conv_id: count for conv_id, count in unread_rows}

    # Private konuşmalar için karşı üyeleri toplu al
    private_conv_ids = [c.id for c in convs if c.type == "private"]
    other_user_map = {}
    if private_conv_ids:
        OtherMember = aliased(ConversationMember)
        other_rows = (
            db.query(OtherMember.conversation_id, User)
            .join(User, User.id == OtherMember.user_id)
            .filter(
                OtherMember.conversation_id.in_(private_conv_ids),
                OtherMember.user_id != current_user.id,
            )
            .all()
        )
        for conv_id, user_obj in other_rows:
            other_user_map[conv_id] = user_obj

    results = []
    for conv in convs:
        last_msg = last_msg_map.get(conv.id)
        my_membership = membership_map.get(conv.id)
        muted = my_membership.is_muted if my_membership else False
        if conv.type == "private":
            other_user = other_user_map.get(conv.id)
            results.append(ConversationResponse(
                id=conv.id,
                type=conv.type,
                other_user=_user_brief(other_user) if other_user else None,
                last_message=_msg_response(last_msg) if last_msg else None,
                unread_count=unread_map.get(conv.id, 0),
                is_muted=muted,
                updated_at=conv.updated_at,
            ))
        else:
            # Grup konuşması
            results.append(ConversationResponse(
                id=conv.id,
                type=conv.type,
                name=conv.name,
                last_message=_msg_response(last_msg, include_sender_name=True) if last_msg else None,
                unread_count=unread_map.get(conv.id, 0),
                is_muted=muted,
                updated_at=conv.updated_at,
            ))

    return results


# ─── Konuşma Detayı ───────────────────────────────────────────────────


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: int,
    before_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "view")),
):
    """Konuşma mesajlarını getir (cursor-based pagination).

    - before_id: Bu ID'den önceki mesajları getir (eski mesajlar için)
    - limit: Maksimum mesaj sayısı (varsayılan 50, maks 100)
    """
    try:
        membership = _get_membership(db, conversation_id, current_user.id)
    except HTTPException:
        # Üyelik bulunamadı — konuşma silinmiş olabilir.
        # Konuşma gerçekten yoksa boş tombstone response dön (eski client'lar
        # 404 döngüsüne girmesin). Konuşma varsa ama kullanıcı üye değilse 404.
        conv_exists = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv_exists:
            raise HTTPException(status_code=404, detail="Konuşma bulunamadı")
        # Konuşma tamamen silinmiş — boş response ile eski client'ların
        # hata döngüsüne girmesini engelle
        return ConversationDetailResponse(
            id=conversation_id,
            type="private",
            messages=[],
            has_more=False,
        )

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()

    limit = min(max(limit, 1), 100)

    # Mesaj sorgusu — cursor-based: son N mesajı getir (veya before_id'den önceki N mesaj)
    msg_query = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.conversation_id == conversation_id)
    )

    # Sonradan eklenen/geri dönen üyeler önceki mesajları göremez
    if membership.joined_at:
        msg_query = msg_query.filter(Message.created_at >= membership.joined_at)

    if before_id:
        msg_query = msg_query.filter(Message.id < before_id)

    # limit+1 al ki has_more hesaplayabilelim
    raw_messages = (
        msg_query
        .order_by(desc(Message.id))
        .limit(limit + 1)
        .all()
    )

    has_more = len(raw_messages) > limit
    if has_more:
        raw_messages = raw_messages[:limit]

    # Kronolojik sıraya çevir (eski → yeni)
    raw_messages.reverse()

    is_group = conv.type == "group"

    if is_group:
        members = _get_group_members(db, conversation_id)
        return ConversationDetailResponse(
            id=conv.id,
            type=conv.type,
            name=conv.name,
            members=members,
            messages=[_msg_response(m, include_sender_name=True) for m in raw_messages],
            has_more=has_more,
            created_by=conv.created_by,
        )
    else:
        other_row = (
            db.query(ConversationMember, User)
            .join(User, User.id == ConversationMember.user_id)
            .filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id != current_user.id,
            )
            .first()
        )
        if not other_row:
            raise HTTPException(status_code=404, detail="Konuşma bulunamadı")
        other_member, other_user = other_row

        return ConversationDetailResponse(
            id=conv.id,
            type=conv.type,
            other_user=_user_brief(other_user),
            messages=[_msg_response(m) for m in raw_messages],
            has_more=has_more,
            other_user_last_read_at=other_member.last_read_at,
        )


# ─── Private Konuşma ──────────────────────────────────────────────────


@router.post("/conversations", response_model=ConversationDetailResponse, status_code=201)
def create_conversation(
    data: ConversationCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Yeni private konuşma başlat veya mevcut olanı döndür."""
    if data.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Kendinizle konuşma başlatamazsınız")

    target_user = db.query(User).filter(User.id == data.user_id, User.is_active == True).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    # Unique pair: (low, high) — private konuşma araması
    low_id = min(current_user.id, data.user_id)
    high_id = max(current_user.id, data.user_id)

    # Mevcut private konuşma var mı kontrol et (unique constraint ile korunan)
    existing_conv = (
        db.query(Conversation)
        .filter(
            Conversation.private_user_low == low_id,
            Conversation.private_user_high == high_id,
        )
        .first()
    )

    if existing_conv:
        my_membership = (
            db.query(ConversationMember)
            .filter(
                ConversationMember.conversation_id == existing_conv.id,
                ConversationMember.user_id == current_user.id,
            )
            .first()
        )
        other_membership = (
            db.query(ConversationMember)
            .filter(
                ConversationMember.conversation_id == existing_conv.id,
                ConversationMember.user_id == data.user_id,
            )
            .first()
        )

        # Kullanıcı konuşmayı silmişse (üyelik kaldırılmış), tekrar ekle
        if not my_membership:
            my_membership = ConversationMember(
                conversation_id=existing_conv.id,
                user_id=current_user.id,
            )
            db.add(my_membership)
            db.flush()

        # Diğer kullanıcı da çıkmışsa tekrar ekle
        if not other_membership:
            other_membership = ConversationMember(
                conversation_id=existing_conv.id,
                user_id=data.user_id,
            )
            db.add(other_membership)
            db.flush()

        msg_query = (
            db.query(Message)
            .filter(Message.conversation_id == existing_conv.id)
        )
        # Konuşmayı silip geri eklenen kullanıcı eski mesajları görmesin
        if my_membership.joined_at:
            msg_query = msg_query.filter(Message.created_at >= my_membership.joined_at)
        conv_messages = msg_query.order_by(Message.created_at).all()

        db.commit()
        return ConversationDetailResponse(
            id=existing_conv.id,
            type=existing_conv.type,
            other_user=_user_brief(target_user),
            messages=[_msg_response(m) for m in conv_messages],
            other_user_last_read_at=other_membership.last_read_at if other_membership else None,
        )

    # Yeni konuşma oluştur — unique constraint race condition'ı önler
    conv = Conversation(
        type="private",
        private_user_low=low_id,
        private_user_high=high_id,
    )
    db.add(conv)
    db.flush()

    db.add(ConversationMember(conversation_id=conv.id, user_id=current_user.id))
    db.add(ConversationMember(conversation_id=conv.id, user_id=data.user_id))

    conv_messages = []
    msg_content = data.message.strip() if data.message else None
    if msg_content:
        msg = Message(
            conversation_id=conv.id,
            sender_id=current_user.id,
            content=msg_content,
        )
        db.add(msg)
        db.flush()
        conv.updated_at = datetime.now(tz_istanbul)
        conv_messages = [_msg_response(msg)]

    log_action(db, current_user.id, "create", "conversation", conv.id,
               f"Private konuşma başlatıldı (hedef: {target_user.username})",
               get_client_ip(request))

    try:
        db.commit()
    except Exception:
        db.rollback()
        # Race condition: unique constraint ihlali — mevcut konuşmayı döndür
        existing_conv2 = (
            db.query(Conversation)
            .filter(
                Conversation.private_user_low == low_id,
                Conversation.private_user_high == high_id,
            )
            .first()
        )
        if existing_conv2:
            dup_msgs = (
                db.query(Message)
                .filter(Message.conversation_id == existing_conv2.id)
                .order_by(Message.created_at)
                .all()
            )
            other_membership2 = (
                db.query(ConversationMember)
                .filter(
                    ConversationMember.conversation_id == existing_conv2.id,
                    ConversationMember.user_id == data.user_id,
                )
                .first()
            )
            return ConversationDetailResponse(
                id=existing_conv2.id,
                type=existing_conv2.type,
                other_user=_user_brief(target_user),
                messages=[_msg_response(m) for m in dup_msgs],
                other_user_last_read_at=other_membership2.last_read_at if other_membership2 else None,
            )
        raise HTTPException(status_code=500, detail="Konuşma oluşturulurken bir hata oluştu")

    db.refresh(conv)

    # WebSocket ile hedef kullanıcıya yeni konuşma bildirimi
    background_tasks.add_task(manager.send_to_user, data.user_id, {
        "type": "new_conversation",
        "conversation_id": conv.id,
        "initiator": {
            "id": current_user.id,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "username": current_user.username,
        }
    })

    return ConversationDetailResponse(
        id=conv.id,
        type=conv.type,
        other_user=_user_brief(target_user),
        messages=conv_messages,
        other_user_last_read_at=None,
    )


# ─── Konuşma Sessize Alma ─────────────────────────────────────────────


@router.patch("/conversations/{conversation_id}/mute")
def toggle_mute(
    conversation_id: int,
    data: MuteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Konuşmayı sessize al veya sesli yap."""
    membership = _get_membership(db, conversation_id, current_user.id)
    membership.is_muted = data.is_muted
    db.commit()
    return {"is_muted": membership.is_muted}


# ─── Konuşma Silme ────────────────────────────────────────────────────


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Konuşmayı kullanıcının listesinden sil (sadece benden sil).

    Kullanıcının üyeliğini sessizce kaldırır. Diğer üyeler konuşmayı
    görmeye devam eder. Tüm üyeler ayrılmışsa konuşma tamamen temizlenir.
    """
    membership = _get_membership(db, conversation_id, current_user.id)
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Konuşma bulunamadı")

    db.delete(membership)
    db.flush()

    # Konuşmada başka üye kaldı mı kontrol et
    remaining = (
        db.query(ConversationMember)
        .filter(ConversationMember.conversation_id == conversation_id)
        .count()
    )

    if remaining == 0:
        # Kimse kalmadı — yüklenen dosyaları temizle
        file_rows = (
            db.query(Message.file_url)
            .filter(
                Message.conversation_id == conversation_id,
                Message.file_url.isnot(None),
            )
            .all()
        )
        for (file_url,) in file_rows:
            try:
                # file_url format: /uploads/2026/02/uuid.ext
                rel_path = file_url.lstrip("/").replace("uploads/", "", 1)
                file_path = UPLOAD_DIR / rel_path
                if file_path.exists():
                    file_path.unlink()
            except OSError as e:
                logger.warning("Dosya silinemedi %s: %s", file_url, e)

        # Konuşmayı ve mesajları tamamen temizle
        db.query(Message).filter(
            Message.conversation_id == conversation_id
        ).delete(synchronize_session=False)
        db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).delete(synchronize_session=False)

    log_action(db, current_user.id, "delete", "conversation", conversation_id,
               f"Konuşma silindi (tür: {conv.type})",
               get_client_ip(request))
    db.commit()

    return {"detail": "Konuşma silindi"}


# ─── Okundu İşaretleme ────────────────────────────────────────────────


@router.patch("/conversations/{conversation_id}/read")
def mark_as_read(
    conversation_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "view")),
):
    """Konuşmayı okundu olarak işaretle."""
    membership = _get_membership(db, conversation_id, current_user.id)

    membership.last_read_at = datetime.now(tz_istanbul)
    db.commit()

    # Diğer üyelere okundu bilgisi gönder
    other_member_ids = _get_other_member_ids(db, conversation_id, current_user.id)
    if other_member_ids:
        background_tasks.add_task(manager.send_to_users, other_member_ids, {
            "type": "read_status",
            "conversation_id": conversation_id,
            "user_id": current_user.id,
            "last_read_at": str(membership.last_read_at),
        })

    return {"ok": True}


# ─── Okunmamış Sayısı ─────────────────────────────────────────────────


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "view")),
):
    """Toplam okunmamış mesaj sayısını döndür (tek sorgu)."""
    # joined_at filtresi: Gruba sonradan eklenen üyeler eklenmeden önceki mesajları saymasın
    total = (
        db.query(func.count(Message.id))
        .join(ConversationMember, and_(
            ConversationMember.conversation_id == Message.conversation_id,
            ConversationMember.user_id == current_user.id,
        ))
        .filter(
            Message.sender_id != current_user.id,
            Message.is_deleted == False,
            Message.created_at >= ConversationMember.joined_at,
            or_(
                ConversationMember.last_read_at.is_(None),
                Message.created_at > ConversationMember.last_read_at,
            ),
        )
        .scalar()
    ) or 0

    return UnreadCountResponse(total_unread=total)
