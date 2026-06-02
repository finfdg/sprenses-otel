"""Grup konuşma yönetimi endpoint'leri."""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.conversation import Conversation, ConversationMember
from app.models.message import Message
from app.models.user import User
from app.routers.messages._helpers import (
    _broadcast_to_conversation,
    _create_system_message,
    _get_group_members,
    _get_membership,
    _get_messaging_role_ids,
    _get_other_member_ids,
    _msg_response,
    tz_istanbul,
)
from app.schemas.message import (
    ConversationDetailResponse,
    GroupAdminUpdate,
    GroupCreate,
    GroupMemberAdd,
    GroupNameUpdate,
)
from app.utils.audit import log_action
from app.websocket.manager import manager

router = APIRouter()


# ─── Grup Oluşturma ──────────────────────────────────────────────────


@router.post("/conversations/group", response_model=ConversationDetailResponse, status_code=201)
def create_group(
    data: GroupCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Yeni grup konuşması oluştur."""
    if not data.name or not data.name.strip():
        raise HTTPException(status_code=400, detail="Grup adı zorunludur")

    if len(data.member_ids) < 1:
        raise HTTPException(status_code=400, detail="En az 1 üye seçmelisiniz")

    # Kendini listeden çıkar (otomatik eklenecek)
    member_ids = [uid for uid in set(data.member_ids) if uid != current_user.id]
    if not member_ids:
        raise HTTPException(status_code=400, detail="En az 1 başka üye seçmelisiniz")

    # Üyelerin var ve aktif olduğunu kontrol et
    valid_users = db.query(User).filter(User.id.in_(member_ids), User.is_active == True).all()
    valid_ids = {u.id for u in valid_users}
    invalid_ids = set(member_ids) - valid_ids
    if invalid_ids:
        raise HTTPException(status_code=400, detail="Bazı kullanıcılar bulunamadı")

    # Konuşma oluştur
    conv = Conversation(
        type="group",
        name=data.name.strip(),
        created_by=current_user.id,
    )
    db.add(conv)
    db.flush()

    # Oluşturanı admin olarak ekle
    db.add(ConversationMember(
        conversation_id=conv.id,
        user_id=current_user.id,
        is_admin=True,
    ))

    # Diğer üyeleri ekle
    for uid in member_ids:
        db.add(ConversationMember(
            conversation_id=conv.id,
            user_id=uid,
        ))

    # Sistem mesajı
    sys_msg = _create_system_message(
        db, conv.id, current_user.id,
        f"{current_user.first_name} {current_user.last_name} grubu oluşturdu"
    )
    db.flush()

    conv_messages = [_msg_response(sys_msg)]

    # İlk mesaj varsa ekle
    if data.message and data.message.strip():
        msg = Message(
            conversation_id=conv.id,
            sender_id=current_user.id,
            content=data.message.strip(),
        )
        db.add(msg)
        db.flush()
        conv.updated_at = datetime.now(tz_istanbul)
        conv_messages.append(_msg_response(msg))

    log_action(db, current_user.id, "create", "group_conversation", conv.id,
               f"Grup oluşturuldu: {conv.name} ({len(member_ids)} üye)",
               get_client_ip(request))
    db.commit()
    db.refresh(conv)

    # WS bildirimi tüm üyelere
    for uid in member_ids:
        background_tasks.add_task(manager.send_to_user, uid, {
            "type": "new_conversation",
            "conversation_id": conv.id,
            "group_name": conv.name,
            "initiator": {
                "id": current_user.id,
                "first_name": current_user.first_name,
                "last_name": current_user.last_name,
                "username": current_user.username,
            }
        })

    members = _get_group_members(db, conv.id)

    return ConversationDetailResponse(
        id=conv.id,
        type=conv.type,
        name=conv.name,
        members=members,
        messages=conv_messages,
        created_by=conv.created_by,
    )


# ─── Üye Ekleme ──────────────────────────────────────────────────────


@router.post("/conversations/{conversation_id}/members")
def add_group_members(
    conversation_id: int,
    data: GroupMemberAdd,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Gruba üye ekle (sadece admin)."""
    membership = _get_membership(db, conversation_id, current_user.id)
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or conv.type != "group":
        raise HTTPException(status_code=400, detail="Bu işlem sadece grup konuşmalar için geçerlidir")
    if not membership.is_admin:
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici olmalısınız")

    # Mevcut üyeleri al
    existing_ids = {
        m.user_id for m in
        db.query(ConversationMember.user_id)
        .filter(ConversationMember.conversation_id == conversation_id)
        .all()
    }

    new_ids = [uid for uid in set(data.user_ids) if uid not in existing_ids]
    if not new_ids:
        raise HTTPException(status_code=400, detail="Seçilen kullanıcılar zaten grupta")

    # Kullanıcıları doğrula
    valid_users = db.query(User).filter(User.id.in_(new_ids), User.is_active == True).all()
    valid_map = {u.id: u for u in valid_users}

    # Messaging izni olan rolleri bul
    msg_role_ids = _get_messaging_role_ids(db)

    added_names = []
    rejected_names = []
    for uid in new_ids:
        user_obj = valid_map.get(uid)
        if not user_obj:
            continue
        # Messaging izni kontrolü
        if msg_role_ids and user_obj.role_id not in msg_role_ids:
            rejected_names.append(f"{user_obj.first_name} {user_obj.last_name}")
            continue
        db.add(ConversationMember(conversation_id=conversation_id, user_id=uid))
        added_names.append(f"{user_obj.first_name} {user_obj.last_name}")

    if not added_names:
        if rejected_names:
            raise HTTPException(
                status_code=400,
                detail=f"Şu kullanıcıların mesajlaşma izni yok: {', '.join(rejected_names)}"
            )
        raise HTTPException(status_code=400, detail="Eklenecek geçerli kullanıcı bulunamadı")

    # Sistem mesajları
    for name in added_names:
        _create_system_message(
            db, conversation_id, current_user.id,
            f"{current_user.first_name} {current_user.last_name}, {name} kullanıcısını gruba ekledi"
        )

    log_action(db, current_user.id, "update", "group_member", conversation_id,
               f"Gruba üye eklendi: {', '.join(added_names)}",
               get_client_ip(request))
    db.commit()

    # WS bildirimi: tüm üyelere (yeni dahil)
    all_member_ids = _get_other_member_ids(db, conversation_id, current_user.id)
    if all_member_ids:
        background_tasks.add_task(manager.send_to_users, all_member_ids, {
            "type": "group_member_added",
            "conversation_id": conversation_id,
            "added_by": current_user.id,
        })

    result = {"detail": "Üyeler eklendi", "members": _get_group_members(db, conversation_id)}
    if rejected_names:
        result["rejected"] = rejected_names
        result["detail"] = f"Üyeler eklendi. Mesajlaşma izni olmayan kullanıcılar atlandı: {', '.join(rejected_names)}"
    return result


# ─── Üye Çıkarma ─────────────────────────────────────────────────────


@router.delete("/conversations/{conversation_id}/members/{user_id}")
def remove_group_member(
    conversation_id: int,
    user_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Gruptan üye çıkar (admin) veya kendini çıkar."""
    my_membership = _get_membership(db, conversation_id, current_user.id)
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or conv.type != "group":
        raise HTTPException(status_code=400, detail="Bu işlem sadece grup konuşmalar için geçerlidir")

    is_self = (user_id == current_user.id)
    if not is_self and not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici olmalısınız")

    target_membership = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
        .first()
    )
    if not target_membership:
        raise HTTPException(status_code=404, detail="Kullanıcı bu grupta değil")

    target_user = db.query(User).filter(User.id == user_id).first()
    target_name = f"{target_user.first_name} {target_user.last_name}" if target_user else "Kullanıcı"

    # Sistem mesajı
    if is_self:
        sys_content = f"{target_name} gruptan ayrıldı"
    else:
        sys_content = f"{current_user.first_name} {current_user.last_name}, {target_name} kullanıcısını gruptan çıkardı"

    _create_system_message(db, conversation_id, current_user.id, sys_content)

    # Üyeyi sil
    db.delete(target_membership)

    log_action(db, current_user.id, "delete", "group_member", conversation_id,
               f"Gruptan üye çıkarıldı: {target_name}",
               get_client_ip(request))
    db.commit()

    # WS bildirimi: tüm üyelere + çıkarılan kişiye
    all_member_ids = _get_other_member_ids(db, conversation_id, current_user.id)
    event = {
        "type": "group_member_removed",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "removed_by": current_user.id,
    }
    if all_member_ids:
        background_tasks.add_task(manager.send_to_users, all_member_ids, event)
    # Çıkarılan kişiye de bildir
    if not is_self:
        background_tasks.add_task(manager.send_to_user, user_id, event)

    return {"detail": "Üye çıkarıldı"}


# ─── Yönetici Güncelleme ─────────────────────────────────────────────


@router.patch("/conversations/{conversation_id}/admins/{user_id}")
def update_group_admin(
    conversation_id: int,
    user_id: int,
    data: GroupAdminUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Grup yöneticisi ata/kaldır (sadece admin)."""
    my_membership = _get_membership(db, conversation_id, current_user.id)
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or conv.type != "group":
        raise HTTPException(status_code=400, detail="Bu işlem sadece grup konuşmalar için geçerlidir")
    if not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici olmalısınız")

    target_membership = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
        .first()
    )
    if not target_membership:
        raise HTTPException(status_code=404, detail="Kullanıcı bu grupta değil")

    if target_membership.is_admin == data.is_admin:
        return {"detail": "Değişiklik yok"}

    # Son yönetici yetkisini bırakmasını engelle
    if not data.is_admin and target_membership.is_admin:
        admin_count = (
            db.query(ConversationMember)
            .filter(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.is_admin == True,
            )
            .count()
        )
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Grupta en az bir yönetici olmalıdır. Önce başka birini yönetici yapın.",
            )

    target_user = db.query(User).filter(User.id == user_id).first()
    target_name = f"{target_user.first_name} {target_user.last_name}" if target_user else "Kullanıcı"

    target_membership.is_admin = data.is_admin

    if data.is_admin:
        sys_content = f"{current_user.first_name} {current_user.last_name}, {target_name} kullanıcısını yönetici yaptı"
    else:
        sys_content = f"{current_user.first_name} {current_user.last_name}, {target_name} kullanıcısının yöneticiliğini kaldırdı"

    _create_system_message(db, conversation_id, current_user.id, sys_content)
    action_detail = f"Yönetici {'atandı' if data.is_admin else 'kaldırıldı'}: {target_name}"
    log_action(db, current_user.id, "update", "group_admin", conversation_id,
               action_detail, get_client_ip(request))
    db.commit()

    _broadcast_to_conversation(background_tasks, db, conversation_id, current_user.id, {
        "type": "group_admin_changed",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "is_admin": data.is_admin,
        "changed_by": current_user.id,
    })

    return {"detail": "Yönetici güncellendi", "members": _get_group_members(db, conversation_id)}


# ─── Grup Adı Değiştirme ─────────────────────────────────────────────


@router.patch("/conversations/{conversation_id}/name")
def update_group_name(
    conversation_id: int,
    data: GroupNameUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("messaging", "use")),
):
    """Grup adını değiştir (sadece admin)."""
    my_membership = _get_membership(db, conversation_id, current_user.id)
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or conv.type != "group":
        raise HTTPException(status_code=400, detail="Bu işlem sadece grup konuşmalar için geçerlidir")
    if not my_membership.is_admin:
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici olmalısınız")

    if not data.name or not data.name.strip():
        raise HTTPException(status_code=400, detail="Grup adı boş olamaz")

    old_name = conv.name
    conv.name = data.name.strip()

    _create_system_message(
        db, conversation_id, current_user.id,
        f"{current_user.first_name} {current_user.last_name}, grup adını '{conv.name}' olarak değiştirdi"
    )
    log_action(db, current_user.id, "update", "group_name", conversation_id,
               f"Grup adı değiştirildi: '{old_name}' → '{conv.name}'",
               get_client_ip(request))
    db.commit()

    _broadcast_to_conversation(background_tasks, db, conversation_id, current_user.id, {
        "type": "group_name_changed",
        "conversation_id": conversation_id,
        "name": conv.name,
        "changed_by": current_user.id,
    })

    return {"detail": "Grup adı güncellendi", "name": conv.name}
