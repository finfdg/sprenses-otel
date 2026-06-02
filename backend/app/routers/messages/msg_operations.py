"""Mesaj gönderme, düzenleme, silme ve arama endpoint'leri."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip, message_limiter, search_limiter, upload_limiter
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.routers.messages._helpers import (
    _broadcast_to_conversation,
    _build_new_message_event,
    _get_membership,
    _get_muted_user_ids,
    _get_other_member_ids,
    _msg_response,
    _restore_missing_members,
    tz_istanbul,
)
from app.schemas.message import MessageCreate, MessageEdit, MessageResponse
from app.utils.audit import log_action
from app.utils.file_upload import save_upload
from app.utils.push import send_push_to_user
from app.websocket.manager import manager

router = APIRouter()


# ─── Mesaj Gönder ─────────────────────────────────────────────────────


@router.post("/conversations/{conversation_id}", response_model=MessageResponse, status_code=201)
def send_message(
    conversation_id: int,
    data: MessageCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Konuşmaya mesaj gönder."""
    message_limiter.check(f"msg-user-{current_user.id}")

    membership = _get_membership(db, conversation_id, current_user.id)

    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()

    msg = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=data.content.strip(),
    )
    db.add(msg)

    conv.updated_at = datetime.now(tz_istanbul)
    membership.last_read_at = datetime.now(tz_istanbul)

    # Konuşmayı silmiş üyelerin üyeliğini geri yükle
    _restore_missing_members(db, conversation_id, current_user.id)

    # Diğer üyeleri bul
    other_member_ids = _get_other_member_ids(db, conversation_id, current_user.id)

    db.flush()
    log_action(db, current_user.id, "create", "message", msg.id,
               f"Mesaj gönderildi (konuşma: {conversation_id})",
               get_client_ip(request))
    db.commit()
    db.refresh(msg)

    # WS event oluştur
    ws_event = _build_new_message_event(msg, current_user, conversation_id)

    # Tüm diğer üyelere WS broadcast
    if other_member_ids:
        background_tasks.add_task(manager.send_to_users, other_member_ids, ws_event)

    # Push bildirim: çevrimdışı, arka planda ve sessiz olmayan üyelere
    muted_user_ids = _get_muted_user_ids(db, conversation_id, other_member_ids)

    push_title = f"{current_user.first_name} {current_user.last_name}"
    if conv.type == "group" and conv.name:
        push_title = f"{push_title} ({conv.name})"
    push_body = data.content.strip()[:100]

    for uid in other_member_ids:
        if (not manager.is_online(uid) or manager.is_background(uid)) and uid not in muted_user_ids:
            background_tasks.add_task(
                send_push_to_user,
                uid,
                push_title,
                push_body,
                "/dashboard/mesajlasma",
                f"conv-{conversation_id}",
            )

    return _msg_response(msg)


# ─── Dosya Yükleme ────────────────────────────────────────────────────


@router.post("/conversations/{conversation_id}/upload", response_model=MessageResponse, status_code=201)
async def upload_file(
    conversation_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Konuşmaya dosya/görsel gönder."""
    upload_limiter.check(f"upload-user-{current_user.id}")

    membership = _get_membership(db, conversation_id, current_user.id)

    # Dosyayı kaydet
    upload_result = await save_upload(file)

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()

    msg = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=caption.strip() if caption and caption.strip() else upload_result["file_name"],
        message_type=upload_result["message_type"],
        file_url=upload_result["file_url"],
        file_name=upload_result["file_name"],
        file_size=upload_result["file_size"],
        file_type=upload_result["file_type"],
    )
    db.add(msg)

    conv.updated_at = datetime.now(tz_istanbul)
    membership.last_read_at = datetime.now(tz_istanbul)

    # Konuşmayı silmiş üyelerin üyeliğini geri yükle
    _restore_missing_members(db, conversation_id, current_user.id)

    other_member_ids = _get_other_member_ids(db, conversation_id, current_user.id)

    db.flush()
    log_action(db, current_user.id, "create", "message", msg.id,
               f"Dosya yüklendi: {upload_result['file_name']} (konuşma: {conversation_id})",
               get_client_ip(request))
    db.commit()
    db.refresh(msg)

    # WS event
    ws_event = _build_new_message_event(msg, current_user, conversation_id)

    if other_member_ids:
        background_tasks.add_task(manager.send_to_users, other_member_ids, ws_event)

    # Push bildirim: çevrimdışı, arka planda ve sessiz olmayan üyelere
    muted_user_ids = _get_muted_user_ids(db, conversation_id, other_member_ids)

    push_title = f"{current_user.first_name} {current_user.last_name}"
    if conv.type == "group" and conv.name:
        push_title = f"{push_title} ({conv.name})"
    push_body = "📎 Dosya gönderdi" if msg.message_type == "file" else "📷 Fotoğraf gönderdi" if msg.message_type == "image" else "🎬 Video gönderdi"

    for uid in other_member_ids:
        if (not manager.is_online(uid) or manager.is_background(uid)) and uid not in muted_user_ids:
            background_tasks.add_task(
                send_push_to_user,
                uid,
                push_title,
                push_body,
                "/dashboard/mesajlasma",
                f"conv-{conversation_id}",
            )

    return _msg_response(msg)


# ─── Mesaj Düzenle / Sil ──────────────────────────────────────────────


@router.patch("/conversations/{conversation_id}/messages/{message_id}", response_model=MessageResponse)
def edit_message(
    conversation_id: int,
    message_id: int,
    data: MessageEdit,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Mesajı düzenle (sadece kendi mesajı)."""
    _get_membership(db, conversation_id, current_user.id)

    msg = (
        db.query(Message)
        .filter(Message.id == message_id, Message.conversation_id == conversation_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sadece kendi mesajınızı düzenleyebilirsiniz")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Silinmiş mesaj düzenlenemez")
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")

    msg.content = data.content.strip()
    msg.is_edited = True
    msg.edited_at = datetime.now(tz_istanbul)

    log_action(db, current_user.id, "update", "message", message_id,
               f"Mesaj düzenlendi (konuşma: {conversation_id})",
               get_client_ip(request))
    db.commit()
    db.refresh(msg)

    # WS broadcast
    _broadcast_to_conversation(background_tasks, db, conversation_id, current_user.id, {
        "type": "message_edited",
        "conversation_id": conversation_id,
        "message_id": message_id,
        "content": msg.content,
        "edited_at": str(msg.edited_at),
    })

    return _msg_response(msg)


@router.delete("/conversations/{conversation_id}/messages/{message_id}", response_model=MessageResponse)
def delete_message(
    conversation_id: int,
    message_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Mesajı sil — soft delete (sadece kendi mesajı)."""
    _get_membership(db, conversation_id, current_user.id)

    msg = (
        db.query(Message)
        .filter(Message.id == message_id, Message.conversation_id == conversation_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sadece kendi mesajınızı silebilirsiniz")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Mesaj zaten silinmiş")

    msg.is_deleted = True

    log_action(db, current_user.id, "delete", "message", message_id,
               f"Mesaj silindi (konuşma: {conversation_id})",
               get_client_ip(request))
    db.commit()
    db.refresh(msg)

    # WS broadcast
    _broadcast_to_conversation(background_tasks, db, conversation_id, current_user.id, {
        "type": "message_deleted",
        "conversation_id": conversation_id,
        "message_id": message_id,
    })

    return _msg_response(msg)


# ─── Mesaj Arama ──────────────────────────────────────────────────────


@router.get("/conversations/{conversation_id}/search")
def search_messages(
    conversation_id: int,
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "view")),
):
    """Konuşma içinde mesaj ara."""
    search_limiter.check(f"search-user-{current_user.id}")

    membership = _get_membership(db, conversation_id, current_user.id)

    if not q or not q.strip():
        return []

    # Uzunluk sınırı ve SQL LIKE wildcard escape
    q_clean = q.strip()[:200]
    q_escaped = q_clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{q_escaped}%"
    search_query = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(
            Message.conversation_id == conversation_id,
            Message.is_deleted == False,
            Message.message_type == "text",
            Message.content.ilike(pattern, escape="\\"),
        )
    )

    # Sonradan eklenen/geri dönen üyeler önceki mesajları arayamaz
    if membership.joined_at:
        search_query = search_query.filter(Message.created_at >= membership.joined_at)

    results = (
        search_query
        .order_by(desc(Message.created_at))
        .limit(50)
        .all()
    )

    return [_msg_response(m, include_sender_name=True) for m in results]
