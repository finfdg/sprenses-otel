"""Onay Akışı — onay talebi endpoint'leri (gönderme, onaylama, reddetme, iade, iptal)."""

import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.constants import WSEvent
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.approval import (
    ACTION_APPROVE,
    ACTION_CANCEL,
    ACTION_REJECT,
    ACTION_RESUBMIT,
    ACTION_RETURN,
    STATUS_PENDING,
    STATUS_RETURNED,
    ApprovalRequest,
    ApprovalRequestLog,
)
from app.models.user import User
from app.schemas.approval import (
    ApprovalAction,
    ApprovalRejectAction,
    TriggerApprovalRequest,
)
from app.utils.approval_executor import cleanup_rejected_or_cancelled, execute_approved_payload
from app.utils.approval_service import (
    check_and_trigger_approval,
    get_entity_type_label,
    get_pending_approver_ids,
    is_user_approver,
    process_action,
)
from app.utils.audit import log_action
from app.utils.notification import create_and_send_notifications
from app.websocket.manager import manager

router = APIRouter()


async def _broadcast_approval_update(module_code: Optional[str] = None) -> None:
    """Onay durumu değiştiğinde tüm bağlı kullanıcılara WS event gönder.

    3 event gönderilir:
    - finance_updated: ScheduledModule vb. sayfalar yenilensin
    - approval_updated: Onay akışı sayfası yenilensin
    - approval_status_changed: Modül bazlı sayfalarda badge güncellensin
    """
    try:
        await manager.send_to_all({
            "type": WSEvent.FINANCE_UPDATED,
            "module": "approval",
            "action": "update",
        })
        await manager.send_to_all({
            "type": WSEvent.APPROVAL_UPDATED,
        })
        if module_code:
            await manager.send_to_all({
                "type": WSEvent.APPROVAL_STATUS_CHANGED,
                "module_code": module_code,
            })
    except Exception:
        pass


# --- Yardımcı fonksiyonlar ---

# payload_json içinde maskelenmesi gereken hassas alan adı parçaları
_SENSITIVE_KEY_PARTS = ("password", "secret", "token", "pwd", "hash", "api_key")


def _redact_sensitive(obj):
    """payload içindeki şifre/sır benzeri alanları '***' ile maskeler (özyinelemeli)."""
    if isinstance(obj, dict):
        return {
            k: ("***" if isinstance(k, str) and any(p in k.lower() for p in _SENSITIVE_KEY_PARTS)
                else _redact_sensitive(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_sensitive(v) for v in obj]
    return obj


def _redact_payload(payload_json: Optional[str]) -> Optional[str]:
    """payload_json'u parse edip hassas alanları maskeleyerek geri serileştirir.

    Onay yükü (ör. kullanıcı oluşturma) düz-metin şifre içerebilir; API yanıtında
    asla dışarı verilmemeli. Yürütme (execute_approved_payload) yükü doğrudan DB
    kolonundan okuduğu için bu maskeleme onayın UYGULANMASINI etkilemez — yalnızca
    serileştirilen yanıtı temizler.
    """
    if not payload_json:
        return payload_json
    try:
        data = json.loads(payload_json)
    except (ValueError, TypeError):
        return None  # parse edilemeyen yükü dışarı verme
    return json.dumps(_redact_sensitive(data), ensure_ascii=False, default=str)


def _user_can_view_request(db: Session, user_id: int, req: ApprovalRequest) -> bool:
    """Kullanıcı bu talebi görüntüleyebilir mi? (IDOR koruması)

    Yalnızca (a) talep sahibi, (b) talebe daha önce işlem yapmış (loglarda actor),
    veya (c) mevcut adımın onaycısı görebilir. system.approval:view izni TEK BAŞINA
    başkasının talebinin yükünü (payload) görmeye yetmez.
    """
    if req.requested_by == user_id:
        return True
    if any(log.actor_id == user_id for log in (req.logs or [])):
        return True
    return is_user_approver(db, user_id, req)


def _build_request_response(req: ApprovalRequest, user_map: dict, step_map: Optional[dict] = None) -> dict:
    """ApprovalRequestResponse dict oluştur."""
    requester_name = user_map.get(req.requested_by) if req.requested_by else None
    completer_name = user_map.get(req.completed_by) if req.completed_by else None
    workflow_name = req.workflow.name if req.workflow else None

    # Mevcut adım onaycı adı
    current_approver_name = None
    if step_map and req.workflow_id and req.status == STATUS_PENDING:
        step_key = (req.workflow_id, req.current_step)
        current_approver_name = step_map.get(step_key)

    logs = []
    for log in (req.logs or []):
        logs.append({
            "id": log.id,
            "step_number": log.step_number,
            "action": log.action,
            "actor_id": log.actor_id,
            "actor_name": user_map.get(log.actor_id) if log.actor_id else None,
            "note": log.note,
            "created_at": log.created_at,
        })

    # Modül adını al
    module_name = None
    if req.module_code and req.workflow and req.workflow.module:
        module_name = req.workflow.module.name
    entity_label = module_name or get_entity_type_label(req.entity_type)

    # İşlem türü etiketi
    action_labels = {"create": "Oluşturma", "update": "Güncelleme", "delete": "Silme"}
    action_label = action_labels.get(req.action_type, "") if req.action_type else ""
    summary_parts = [entity_label]
    if action_label:
        summary_parts.append(f"({action_label})")
    summary_parts.append(f"#{req.entity_id}")

    return {
        "id": req.id,
        "workflow_id": req.workflow_id,
        "workflow_name": workflow_name,
        "entity_type": req.entity_type,
        "entity_id": req.entity_id,
        "entity_summary": " ".join(summary_parts),
        "module_code": req.module_code,
        "action_type": req.action_type,
        "payload_json": _redact_payload(req.payload_json),
        "status": req.status,
        "current_step": req.current_step,
        "total_steps": req.total_steps,
        "requested_by": req.requested_by,
        "requested_by_name": requester_name,
        "requested_at": req.requested_at,
        "completed_at": req.completed_at,
        "completed_by_name": completer_name,
        "current_step_approver_name": current_approver_name,
        "logs": logs,
    }


def _collect_user_map(db: Session) -> dict:
    """Kullanıcı ID → ad haritası."""
    users = db.query(User.id, User.first_name, User.last_name).all()
    return {u.id: f"{u.first_name} {u.last_name}" for u in users}


# --- Endpoint'ler ---

@router.get("/requests/pending")
def list_pending_requests(
    page: int = 1,
    page_size: int = 50,
    entity_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Kullanıcının onaylaması gereken bekleyen talepler."""
    # Tüm pending talepleri al
    query = db.query(ApprovalRequest).filter(ApprovalRequest.status == STATUS_PENDING)
    if entity_type:
        query = query.filter(ApprovalRequest.entity_type == entity_type)

    all_pending = query.order_by(ApprovalRequest.requested_at.desc()).all()

    # Kullanıcının onaycı olduğu talepleri filtrele
    my_pending = [r for r in all_pending if is_user_approver(db, current_user.id, r)]

    total = len(my_pending)
    start = (page - 1) * page_size
    paged = my_pending[start:start + page_size]

    user_map = _collect_user_map(db)
    items = [_build_request_response(r, user_map) for r in paged]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


@router.get("/requests/pending/count")
def pending_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Bekleyen onay sayısı (sidebar badge)."""
    all_pending = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.status == STATUS_PENDING)
        .all()
    )
    count = sum(1 for r in all_pending if is_user_approver(db, current_user.id, r))
    return {"count": count}


@router.get("/requests/my-submissions")
def list_my_submissions(
    page: int = 1,
    page_size: int = 50,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Kullanıcının gönderdiği talepler."""
    query = db.query(ApprovalRequest).filter(ApprovalRequest.requested_by == current_user.id)
    if status_filter:
        query = query.filter(ApprovalRequest.status == status_filter)

    total = query.count()
    requests = (
        query.order_by(ApprovalRequest.requested_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    user_map = _collect_user_map(db)
    items = [_build_request_response(r, user_map) for r in requests]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


@router.get("/requests/history")
def list_history(
    page: int = 1,
    page_size: int = 50,
    entity_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Kullanıcının ilgili olduğu onay geçmişi (gönderdiği veya işlem yaptığı tamamlanan talepler).

    IDOR koruması: system.approval:view tek başına TÜM organizasyonun yükünü görmeye
    yetmez. Yalnızca talep sahibi olunan veya loglarda işlem yapılan (onay/ret/iade)
    talepler döner — SQL-tarafı filtre ile (ölçeklenebilir, fetch-all yok).
    """
    query = db.query(ApprovalRequest).filter(
        ApprovalRequest.status.notin_([STATUS_PENDING, STATUS_RETURNED])
    )
    if entity_type:
        query = query.filter(ApprovalRequest.entity_type == entity_type)
    if status_filter:
        query = query.filter(ApprovalRequest.status == status_filter)

    # Yalnızca kullanıcının ilgili olduğu talepler (sahip VEYA loglarda actor)
    acted_request_ids = db.query(ApprovalRequestLog.request_id).filter(
        ApprovalRequestLog.actor_id == current_user.id
    )
    query = query.filter(
        or_(
            ApprovalRequest.requested_by == current_user.id,
            ApprovalRequest.id.in_(acted_request_ids),
        )
    )

    total = query.count()
    requests = (
        query.order_by(ApprovalRequest.completed_at.desc().nulls_last())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    user_map = _collect_user_map(db)
    items = [_build_request_response(r, user_map) for r in requests]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


@router.get("/requests/{request_id}")
def get_request_detail(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Tek bir onay talebi detayı (yalnızca sahip / işlem yapan / mevcut onaycı)."""
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onay talebi bulunamadı")
    if not _user_can_view_request(db, current_user.id, req):
        raise HTTPException(status_code=403, detail="Bu talebi görüntüleme yetkiniz yok")

    user_map = _collect_user_map(db)
    return _build_request_response(req, user_map)


@router.post("/requests/{request_id}/approve")
async def approve_request(
    request_id: int,
    data: ApprovalAction,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "use")),
):
    """Onay talebi — onayla."""
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onay talebi bulunamadı")
    if req.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail="Bu talep bekleyen durumda değil")
    if not is_user_approver(db, current_user.id, req):
        raise HTTPException(status_code=403, detail="Bu adımı onaylama yetkiniz yok")

    was_last_step = req.current_step >= req.total_steps
    process_action(db, req, ACTION_APPROVE, current_user.id, data.note)

    # Onay tamamlandıysa bekletilen değişikliği uygula
    if req.status == "approved" and req.payload_json:
        success = execute_approved_payload(db, req)
        if not success:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Onay verildi ancak değişiklik uygulanırken hata oluştu",
            )

    log_action(db, current_user.id, "approve", "approval_request", req.id,
               f"Onay talebi onaylandı: {req.entity_type}#{req.entity_id} (adım {req.current_step - (0 if was_last_step else 1)})",
               get_client_ip(request))
    db.commit()

    # Bildirimleri gönder
    entity_label = get_entity_type_label(req.entity_type)
    if req.status == "approved":
        # Talep tamamlandı — talep sahibine bildir
        if req.requested_by:
            await create_and_send_notifications(
                db, [req.requested_by],
                type="approval_approved",
                title="Onay Talebi Onaylandı",
                body=f"{entity_label} #{req.entity_id} onaylandı",
                link="/dashboard/sistem/onay-akisi",
            )
    else:
        # Sonraki adım onaycılarına bildir
        next_approvers = get_pending_approver_ids(db, req)
        if next_approvers:
            await create_and_send_notifications(
                db, next_approvers,
                type="approval_needed",
                title="Yeni Onay Talebi",
                body=f"{entity_label} #{req.entity_id} — Adım {req.current_step}/{req.total_steps}",
                link="/dashboard/sistem/onay-akisi",
            )

    # Tüm kullanıcılara WS broadcast (açık ekranlar anında güncellensin)
    await _broadcast_approval_update(req.module_code)

    return {"ok": True, "status": req.status, "current_step": req.current_step}


@router.post("/requests/{request_id}/reject")
async def reject_request(
    request_id: int,
    data: ApprovalRejectAction,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "use")),
):
    """Onay talebi — reddet (gerekçe zorunlu)."""
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onay talebi bulunamadı")
    if req.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail="Bu talep bekleyen durumda değil")
    if not is_user_approver(db, current_user.id, req):
        raise HTTPException(status_code=403, detail="Bu adımı reddetme yetkiniz yok")

    process_action(db, req, ACTION_REJECT, current_user.id, data.note)

    # Pasif oluşturulan kaydı temizle (create onayı reddedildi)
    cleanup_rejected_or_cancelled(db, req)

    log_action(db, current_user.id, "reject", "approval_request", req.id,
               f"Onay talebi reddedildi: {req.entity_type}#{req.entity_id}", get_client_ip(request))
    db.commit()

    # Talep sahibine bildir
    entity_label = get_entity_type_label(req.entity_type)
    if req.requested_by:
        await create_and_send_notifications(
            db, [req.requested_by],
            type="approval_rejected",
            title="Onay Talebi Reddedildi",
            body=f"{entity_label} #{req.entity_id} reddedildi: {data.note[:100]}",
            link="/dashboard/sistem/onay-akisi",
        )

    await _broadcast_approval_update(req.module_code)

    return {"ok": True, "status": req.status}


@router.post("/requests/{request_id}/return")
async def return_request(
    request_id: int,
    data: ApprovalRejectAction,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "use")),
):
    """Onay talebi — iade et (düzeltme için geri gönder, gerekçe zorunlu)."""
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onay talebi bulunamadı")
    if req.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail="Bu talep bekleyen durumda değil")
    if not is_user_approver(db, current_user.id, req):
        raise HTTPException(status_code=403, detail="Bu adımı iade etme yetkiniz yok")

    process_action(db, req, ACTION_RETURN, current_user.id, data.note)

    log_action(db, current_user.id, "return", "approval_request", req.id,
               f"Onay talebi iade edildi: {req.entity_type}#{req.entity_id}", get_client_ip(request))
    db.commit()

    # Talep sahibine bildir
    entity_label = get_entity_type_label(req.entity_type)
    if req.requested_by:
        await create_and_send_notifications(
            db, [req.requested_by],
            type="approval_returned",
            title="Onay Talebi İade Edildi",
            body=f"{entity_label} #{req.entity_id} düzeltme için iade edildi: {data.note[:100]}",
            link="/dashboard/sistem/onay-akisi",
        )

    await _broadcast_approval_update(req.module_code)

    return {"ok": True, "status": req.status}


@router.post("/requests/{request_id}/cancel")
async def cancel_request(
    request_id: int,
    data: ApprovalAction,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Onay talebi — iptal et (talep sahibi veya onaycılar, bekleyen/iade durumda)."""
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onay talebi bulunamadı")
    # Talep sahibi veya onaycı iptal edebilir
    is_owner = req.requested_by == current_user.id
    is_approver = is_user_approver(db, current_user.id, req)
    if not is_owner and not is_approver:
        raise HTTPException(status_code=403, detail="Bu talebi iptal etme yetkiniz yok")
    if req.status not in (STATUS_PENDING, STATUS_RETURNED):
        raise HTTPException(status_code=400, detail="Bu talep iptal edilebilir durumda değil")

    process_action(db, req, ACTION_CANCEL, current_user.id, data.note)

    # Pasif oluşturulan kaydı temizle (create onayı iptal edildi)
    cleanup_rejected_or_cancelled(db, req)

    log_action(db, current_user.id, "cancel", "approval_request", req.id,
               f"Onay talebi iptal edildi: {req.entity_type}#{req.entity_id}", get_client_ip(request))
    db.commit()

    # İlgili kullanıcılara bildirim gönder
    entity_label = get_entity_type_label(req.entity_type)
    canceller_name = f"{current_user.first_name} {current_user.last_name}"
    notify_ids = []
    if is_owner:
        # Talep sahibi iptal etti → onaycılara bildir
        notify_ids = get_pending_approver_ids(db, req)
    else:
        # Onaycı iptal etti → talep sahibine bildir
        if req.requested_by:
            notify_ids = [req.requested_by]
    if notify_ids:
        await create_and_send_notifications(
            db, notify_ids,
            type="approval_cancelled",
            title="Onay Talebi İptal Edildi",
            body=f"{entity_label} #{req.entity_id} onay talebi {canceller_name} tarafından iptal edildi",
            link="/dashboard/sistem/onay-akisi",
        )

    await _broadcast_approval_update(req.module_code)

    return {"ok": True, "status": req.status}


@router.post("/requests/{request_id}/resubmit")
async def resubmit_request(
    request_id: int,
    data: ApprovalAction,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Onay talebi — yeniden gönder (iade edildikten sonra)."""
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Onay talebi bulunamadı")
    if req.requested_by != current_user.id:
        raise HTTPException(status_code=403, detail="Sadece talep sahibi yeniden gönderebilir")
    if req.status != STATUS_RETURNED:
        raise HTTPException(status_code=400, detail="Sadece iade edilen talepler yeniden gönderilebilir")

    process_action(db, req, ACTION_RESUBMIT, current_user.id, data.note)

    log_action(db, current_user.id, "resubmit", "approval_request", req.id,
               f"Onay talebi yeniden gönderildi: {req.entity_type}#{req.entity_id}", get_client_ip(request))
    db.commit()

    # İlk adım onaycılarına bildir
    entity_label = get_entity_type_label(req.entity_type)
    approvers = get_pending_approver_ids(db, req)
    if approvers:
        await create_and_send_notifications(
            db, approvers,
            type="approval_needed",
            title="Onay Talebi Yeniden Gönderildi",
            body=f"{entity_label} #{req.entity_id} yeniden onaya gönderildi",
            link="/dashboard/sistem/onay-akisi",
        )

    return {"ok": True, "status": req.status, "current_step": req.current_step}


@router.post("/trigger")
async def trigger_approval(
    data: TriggerApprovalRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Bir kayıt için onay sürecini tetikle."""
    result = check_and_trigger_approval(
        db, data.entity_type, data.entity_id, current_user.id, data.context_data
    )

    if not result:
        return {"triggered": False, "message": "Bu kayıt için aktif onay akışı bulunamadı"}

    log_action(db, current_user.id, "create", "approval_request", result.id,
               f"Onay talebi oluşturuldu: {data.entity_type}#{data.entity_id}", get_client_ip(request))
    db.commit()

    # İlk adım onaycılarına bildir
    entity_label = get_entity_type_label(data.entity_type)
    approvers = get_pending_approver_ids(db, result)
    if approvers:
        await create_and_send_notifications(
            db, approvers,
            type="approval_needed",
            title="Yeni Onay Talebi",
            body=f"{entity_label} #{data.entity_id} onay bekliyor",
            link="/dashboard/sistem/onay-akisi",
        )

    return {"triggered": True, "request_id": result.id, "status": result.status}


@router.post("/status/bulk")
def get_bulk_approval_status(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Birden çok kayıt için bekleyen onay durumunu toplu sorgula.

    Body: {"module_code": "hr.salary", "entity_ids": [1, 2, 3]}
    Returns: {"pending": {entity_id: {request_id, action_type, requested_by, requested_by_name}}}
    """
    module_code = data.get("module_code", "")
    entity_ids = data.get("entity_ids", [])

    if not module_code or not entity_ids:
        return {"pending": {}}

    pending = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.module_code == module_code,
            ApprovalRequest.entity_id.in_(entity_ids),
            ApprovalRequest.status == STATUS_PENDING,
        )
        .all()
    )

    user_map = _collect_user_map(db)
    result = {}
    for req in pending:
        result[str(req.entity_id)] = {
            "request_id": req.id,
            "action_type": req.action_type,
            "requested_by": req.requested_by,
            "requested_by_name": user_map.get(req.requested_by, ""),
        }

    return {"pending": result}


@router.get("/status/{entity_type}/{entity_id}")
def get_entity_approval_status(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Bir kaydın onay durumunu sorgula."""
    req = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.entity_type == entity_type,
            ApprovalRequest.entity_id == entity_id,
        )
        .order_by(ApprovalRequest.id.desc())
        .first()
    )
    if not req:
        return {"has_approval": False, "status": None}

    # IDOR koruması: durum görünür ama yük (payload) yalnızca ilgili kullanıcıya açılır
    if not _user_can_view_request(db, current_user.id, req):
        return {"has_approval": True, "status": req.status, "request": None}

    user_map = _collect_user_map(db)
    return {
        "has_approval": True,
        "status": req.status,
        "request": _build_request_response(req, user_map),
    }
