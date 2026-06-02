"""Onay kontrol yardımcısı — tüm CRUD endpoint'lerinde kullanılır.

Her modülün POST/PATCH/DELETE endpoint'lerinde işlem yapılmadan önce
bu fonksiyon çağrılır. Eşleşen aktif bir onay tanımı varsa işlem
bekletilir (payload_json olarak saklanır) ve 202 Accepted döner.

Aynı kayıt için zaten bekleyen bir onay talebi varsa 409 Conflict döner.
"""

import json
import logging
from typing import List, Optional

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models.approval import STATUS_PENDING, ApprovalRequest
from app.utils.approval_service import (
    check_and_trigger_approval,
    get_entity_type_label,
    get_pending_approver_ids,
)
from app.utils.notification import create_and_send_notifications_sync
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


def _broadcast_approval_created(module_code: str) -> None:
    """Onay oluşturulduğunda WS broadcast gönder (senkron context).

    manager.send_to_all_sync() ile ana event loop'a thread-safe coroutine ekler.
    """
    try:
        manager.send_to_all_sync({"type": "finance_updated", "module": "approval", "action": "update"})
        manager.send_to_all_sync({"type": "approval_updated"})
        manager.send_to_all_sync({"type": "approval_status_changed", "module_code": module_code})
    except Exception:
        logger.debug("Onay WS broadcast gönderilemedi", exc_info=True)


def check_approval(
    db: Session,
    module_code: str,
    entity_id: int,
    user_id: int,
    action_type: str,
    payload: dict,
    context_data: Optional[dict] = None,
) -> Optional[JSONResponse]:
    """CRUD endpoint'inde onay gerekip gerekmediğini kontrol et.

    Onay gerekiyorsa 202 JSONResponse döndürür, endpoint işlemi YAPMAZ.
    Aynı kayıt için bekleyen onay varsa 409 Conflict döner.
    Gerekmiyorsa None döner, endpoint normal devam eder.

    Args:
        db: Veritabanı oturumu
        module_code: Modül kodu (ör: "finance.krediler", "hr.salary")
        entity_id: Etkilenen kayıt ID (create durumunda 0)
        user_id: İşlemi yapan kullanıcı ID
        action_type: İşlem türü — "create", "update", "delete"
        payload: Bekletilecek değişiklik verisi (dict)
        context_data: Koşul değerlendirme için ek veri (opsiyonel)

    Returns:
        JSONResponse(409) — aynı kayıt için bekleyen onay varsa
        JSONResponse(202) — onay gerekiyorsa (yeni talep oluşturuldu)
        None — onay gerekmiyorsa (endpoint normal devam eder)

    Kullanım:
        approval_resp = check_approval(
            db, "finance.krediler", product.id, current_user.id,
            "update", data.model_dump(exclude_unset=True)
        )
        if approval_resp:
            return approval_resp
        # ... normal işlem devam eder
    """
    # Aynı kayıt için bekleyen onay var mı?
    if entity_id > 0:
        existing = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.module_code == module_code,
                ApprovalRequest.entity_id == entity_id,
                ApprovalRequest.status == STATUS_PENDING,
            )
            .first()
        )
        if existing:
            return JSONResponse(
                status_code=409,
                content={
                    "has_pending_approval": True,
                    "request_id": existing.id,
                    "requested_by": existing.requested_by,
                    "action_type": existing.action_type,
                    "message": "Bu kayıt için bekleyen bir onay talebi var. "
                               "Önce mevcut talebin sonuçlanması gerekiyor.",
                },
            )

    result = check_and_trigger_approval(
        db=db,
        module_code=module_code,
        entity_id=entity_id,
        requested_by=user_id,
        action_type=action_type,
        payload_json=json.dumps(payload, default=str, ensure_ascii=False),
        context_data=context_data,
    )
    if result:
        db.commit()

        # Onaycılara bildirim gönder
        try:
            approvers = get_pending_approver_ids(db, result)
            if approvers:
                entity_label = get_entity_type_label(result.entity_type)
                action_labels = {"create": "oluşturma", "update": "güncelleme", "delete": "silme"}
                action_text = action_labels.get(action_type, action_type)
                create_and_send_notifications_sync(
                    db, approvers,
                    type="approval_needed",
                    title="Yeni Onay Talebi",
                    body=f"{entity_label} #{entity_id} {action_text} onayı bekliyor",
                    link="/dashboard/sistem/onay-akisi",
                )
        except Exception:
            logger.warning("Onay bildirimi gönderilemedi", exc_info=True)

        # Tüm kullanıcılara WS broadcast (açık ekranlar anında güncellensin)
        _broadcast_approval_created(module_code)

        return JSONResponse(
            status_code=202,
            content={
                "requires_approval": True,
                "request_id": result.id,
                "message": "İşlem onay sürecine alındı",
            },
        )
    return None


def get_pending_approvals_for_entities(
    db: Session,
    module_code: str,
    entity_ids: List[int],
) -> dict:
    """Birden çok kayıt için bekleyen onay taleplerini toplu sorgula.

    Returns:
        {entity_id: {"request_id": ..., "action_type": ..., "requested_by": ...}}
    """
    if not entity_ids:
        return {}

    pending = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.module_code == module_code,
            ApprovalRequest.entity_id.in_(entity_ids),
            ApprovalRequest.status == STATUS_PENDING,
        )
        .all()
    )

    result = {}
    for req in pending:
        result[req.entity_id] = {
            "request_id": req.id,
            "action_type": req.action_type,
            "requested_by": req.requested_by,
        }
    return result
