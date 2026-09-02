"""Onay Akışı merkezi servisi — modül bazlı, rol tabanlı iş akışı yönetimi."""

import json
import logging
from datetime import datetime
from typing import List, Optional

import pytz
from sqlalchemy.orm import Session

from app.models.approval import (
    ACTION_APPROVE,
    ACTION_CANCEL,
    ACTION_REJECT,
    ACTION_RESUBMIT,
    ACTION_RETURN,
    ACTION_SUBMIT,
    APPROVER_TYPE_DEPT_MANAGER,
    APPROVER_TYPE_ROLE,
    APPROVER_TYPE_USER,
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RETURNED,
    ApprovalRequest,
    ApprovalRequestLog,
    ApprovalWorkflow,
    ApprovalWorkflowStep,
)
from app.models.department import Department
from app.models.module import Module
from app.models.user import User

logger = logging.getLogger(__name__)
tz_istanbul = pytz.timezone("Europe/Istanbul")


def get_entity_type_label(entity_type: str) -> str:
    """Varlık tipi / modül kodu için Türkçe etiket döndür."""
    # Dinamik: modül tablosundan çek (fallback olarak entity_type döndür)
    return entity_type


def find_matching_workflow(
    db: Session,
    module_code: str,
    user_role_id: Optional[int] = None,
    context_data: Optional[dict] = None,
) -> Optional[ApprovalWorkflow]:
    """Verilen modül kodu ve kullanıcı rolü için eşleşen aktif iş akışı bul."""
    # Modülü bul
    module = db.query(Module).filter(Module.code == module_code, Module.is_active.is_(True)).first()
    if not module:
        return None

    workflows = (
        db.query(ApprovalWorkflow)
        .filter(
            ApprovalWorkflow.module_id == module.id,
            ApprovalWorkflow.is_active.is_(True),
        )
        .all()
    )

    for wf in workflows:
        # Kullanıcının rolü talep eden roller arasında mı?
        if user_role_id is not None:
            requestor_role_ids = [rr.role_id for rr in wf.requestor_roles]
            if user_role_id not in requestor_role_ids:
                continue

        # Koşul kontrolü
        if wf.conditions_json:
            try:
                conditions = json.loads(wf.conditions_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if not _evaluate_conditions(conditions, context_data):
                continue

        return wf

    return None


def _evaluate_conditions(conditions: dict, context_data: Optional[dict]) -> bool:
    """Basit koşul değerlendirici. Desteklenen anahtarlar:
    - min_amount: Tutar bu değerden büyükse eşleşir
    - max_amount: Tutar bu değerden küçükse eşleşir
    - field_equals: {"alan_adı": "beklenen_değer"} dict'i
    """
    if not context_data:
        return False

    if "min_amount" in conditions:
        amount = context_data.get("amount", 0)
        if amount < conditions["min_amount"]:
            return False

    if "max_amount" in conditions:
        amount = context_data.get("amount", 0)
        if amount > conditions["max_amount"]:
            return False

    if "field_equals" in conditions:
        for field, expected in conditions["field_equals"].items():
            if context_data.get(field) != expected:
                return False

    return True


def check_and_trigger_approval(
    db: Session,
    module_code: str,
    entity_id: int,
    requested_by: int,
    action_type: Optional[str] = None,
    payload_json: Optional[str] = None,
    context_data: Optional[dict] = None,
) -> Optional[ApprovalRequest]:
    """Kayıt için onay gerekip gerekmediğini kontrol et, gerekiyorsa talep oluştur.

    Args:
        module_code: Modül kodu (ör: finance.cariler)
        entity_id: Etkilenen kayıt ID'si (create durumunda 0)
        requested_by: Talep eden kullanıcı ID'si
        action_type: İşlem türü (create, update, delete)
        payload_json: Bekletilen değişiklik verisi (JSON string)
        context_data: Koşul değerlendirme için ek veri

    Returns:
        ApprovalRequest — eğer onay tetiklendiyse, None — eğer onay gerekmiyorsa
    """
    # Kullanıcının rolünü bul
    user = db.query(User).filter(User.id == requested_by).first()
    if not user:
        return None

    user_role_id = user.role_id

    # Eşleşen iş akışı bul
    workflow = find_matching_workflow(db, module_code, user_role_id, context_data)
    if not workflow:
        return None

    # Talep oluştur
    request = ApprovalRequest(
        workflow_id=workflow.id,
        entity_type=module_code,
        entity_id=entity_id,
        module_code=module_code,
        action_type=action_type,
        payload_json=payload_json,
        status=STATUS_PENDING,
        current_step=1,
        total_steps=1,
        requested_by=requested_by,
    )
    db.add(request)
    db.flush()

    # İlk log kaydı
    log = ApprovalRequestLog(
        request_id=request.id,
        step_number=1,
        action=ACTION_SUBMIT,
        actor_id=requested_by,
    )
    db.add(log)
    db.flush()

    return request


def get_approval_status(
    db: Session,
    entity_type: str,
    entity_id: int,
) -> Optional[str]:
    """Bir kayıt için mevcut onay durumunu döndür. Talep yoksa None."""
    request = (
        db.query(ApprovalRequest.status)
        .filter(
            ApprovalRequest.entity_type == entity_type,
            ApprovalRequest.entity_id == entity_id,
        )
        .order_by(ApprovalRequest.id.desc())
        .first()
    )
    return request[0] if request else None


def get_pending_approver_ids(db: Session, request: ApprovalRequest) -> List[int]:
    """Mevcut iş akışı için onaycı kullanıcı ID'lerini çözümle."""
    if not request.workflow_id:
        return []

    workflow = db.query(ApprovalWorkflow).filter(ApprovalWorkflow.id == request.workflow_id).first()
    if not workflow:
        return []

    # Yeni modül-rol tabanlı sistem
    if workflow.module_id is not None:
        approver_role_ids = [ar.role_id for ar in workflow.approver_roles]
        if not approver_role_ids:
            return []
        users = (
            db.query(User.id)
            .filter(User.role_id.in_(approver_role_ids), User.is_active.is_(True))
            .all()
        )
        return [u[0] for u in users]

    # Eski adım tabanlı sistem (geriye uyumluluk)
    step = (
        db.query(ApprovalWorkflowStep)
        .filter(
            ApprovalWorkflowStep.workflow_id == request.workflow_id,
            ApprovalWorkflowStep.step_number == request.current_step,
            ApprovalWorkflowStep.is_active.is_(True),
        )
        .first()
    )
    if not step:
        return []

    if step.approver_type == APPROVER_TYPE_USER:
        return [step.approver_user_id] if step.approver_user_id else []

    if step.approver_type == APPROVER_TYPE_ROLE:
        if not step.approver_role_id:
            return []
        users = (
            db.query(User.id)
            .filter(User.role_id == step.approver_role_id, User.is_active.is_(True))
            .all()
        )
        return [u[0] for u in users]

    if step.approver_type == APPROVER_TYPE_DEPT_MANAGER:
        dept_id = step.approver_dept_id
        if not dept_id:
            return []
        dept = db.query(Department).filter(Department.id == dept_id).first()
        if dept and dept.manager_id:
            return [dept.manager_id]
        return []

    return []


def is_user_approver(db: Session, user_id: int, request: ApprovalRequest) -> bool:
    """Kullanıcı bu talebin onaycısı mı?"""
    approver_ids = get_pending_approver_ids(db, request)
    return user_id in approver_ids


def process_action(
    db: Session,
    request: ApprovalRequest,
    action: str,
    actor_id: int,
    note: Optional[str] = None,
) -> ApprovalRequest:
    """Onay talebine aksiyon uygula (onayla, reddet, iade, iptal, yeniden gönder)."""
    now = datetime.now(tz_istanbul)

    if action == ACTION_APPROVE:
        # Adım logu
        log = ApprovalRequestLog(
            request_id=request.id,
            step_number=request.current_step,
            action=ACTION_APPROVE,
            actor_id=actor_id,
            note=note,
        )
        db.add(log)

        if request.current_step >= request.total_steps:
            # Son adım — tamamlandı
            request.status = STATUS_APPROVED
            request.completed_at = now
            request.completed_by = actor_id
        else:
            # Sonraki adıma geç
            request.current_step += 1

    elif action == ACTION_REJECT:
        request.status = STATUS_REJECTED
        request.completed_at = now
        request.completed_by = actor_id
        log = ApprovalRequestLog(
            request_id=request.id,
            step_number=request.current_step,
            action=ACTION_REJECT,
            actor_id=actor_id,
            note=note,
        )
        db.add(log)

    elif action == ACTION_RETURN:
        request.status = STATUS_RETURNED
        log = ApprovalRequestLog(
            request_id=request.id,
            step_number=request.current_step,
            action=ACTION_RETURN,
            actor_id=actor_id,
            note=note,
        )
        db.add(log)

    elif action == ACTION_CANCEL:
        request.status = STATUS_CANCELLED
        request.completed_at = now
        request.completed_by = actor_id
        log = ApprovalRequestLog(
            request_id=request.id,
            step_number=request.current_step,
            action=ACTION_CANCEL,
            actor_id=actor_id,
            note=note,
        )
        db.add(log)

    elif action == ACTION_RESUBMIT:
        request.status = STATUS_PENDING
        request.current_step = 1
        request.completed_at = None
        request.completed_by = None
        log = ApprovalRequestLog(
            request_id=request.id,
            step_number=1,
            action=ACTION_RESUBMIT,
            actor_id=actor_id,
            note=note,
        )
        db.add(log)

    db.flush()
    return request
