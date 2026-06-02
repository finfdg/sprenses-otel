"""Onay Akışı — iş akışı tanım CRUD endpoint'leri (modül + rol tabanlı)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.approval import (
    ApprovalWorkflow,
    ApprovalWorkflowApproverRole,
    ApprovalWorkflowRequestorRole,
)
from app.models.module import Module
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.schemas.approval import WorkflowCreate, WorkflowUpdate
from app.utils.audit import log_action

router = APIRouter()


# --- Yardımcı fonksiyonlar ---

def _build_workflow_response(wf: ApprovalWorkflow, user_map: dict) -> dict:
    """WorkflowResponse dict oluştur."""
    creator_name = user_map.get(wf.created_by) if wf.created_by else None

    module_code = None
    module_name = None
    if wf.module:
        module_code = wf.module.code
        module_name = wf.module.name

    req_roles = [{"id": rr.role_id, "name": rr.role.name} for rr in wf.requestor_roles if rr.role]
    app_roles = [{"id": ar.role_id, "name": ar.role.name} for ar in wf.approver_roles if ar.role]

    return {
        "id": wf.id,
        "name": wf.name,
        "module_id": wf.module_id,
        "module_code": module_code,
        "module_name": module_name,
        "description": wf.description,
        "is_active": wf.is_active,
        "conditions_json": wf.conditions_json,
        "requestor_roles": req_roles,
        "approver_roles": app_roles,
        "created_by_name": creator_name,
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }


def _load_user_map(db: Session) -> dict:
    """Kullanıcı ID → ad haritası yükle."""
    users = db.query(User.id, User.first_name, User.last_name).all()
    return {u.id: f"{u.first_name} {u.last_name}" for u in users}


def _sync_junction_roles(
    db: Session,
    workflow_id: int,
    role_ids: List[int],
    model_class,
):
    """Junction tablosunu güncelle — mevcut silinip yeniden oluşturulur."""
    db.query(model_class).filter(model_class.workflow_id == workflow_id).delete()
    db.flush()
    for role_id in role_ids:
        db.add(model_class(workflow_id=workflow_id, role_id=role_id))


# --- Endpoint'ler ---

@router.get("/modules-with-roles")
def get_modules_with_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Aktif modülleri ve her modülde can_use yetkisine sahip rolleri döndür."""
    modules = (
        db.query(Module)
        .filter(Module.is_active.is_(True))
        .order_by(Module.sort_order, Module.name)
        .all()
    )

    result = []
    for m in modules:
        perms = (
            db.query(RoleModulePermission)
            .filter(
                RoleModulePermission.module_id == m.id,
                RoleModulePermission.can_use.is_(True),
            )
            .all()
        )
        if not perms:
            continue

        role_ids = [p.role_id for p in perms]
        roles = (
            db.query(Role)
            .filter(Role.id.in_(role_ids), Role.is_active.is_(True))
            .order_by(Role.name)
            .all()
        )
        if not roles:
            continue

        result.append({
            "id": m.id,
            "name": m.name,
            "code": m.code,
            "parent_id": m.parent_id,
            "roles": [{"id": r.id, "name": r.name} for r in roles],
        })

    return result


@router.get("/workflows")
def list_workflows(
    page: int = 1,
    page_size: int = 50,
    module_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """Tüm aktif iş akışı tanımlarını listele."""
    query = db.query(ApprovalWorkflow).filter(
        ApprovalWorkflow.module_id.isnot(None),
        ApprovalWorkflow.is_active.is_(True),
    )
    if module_id:
        query = query.filter(ApprovalWorkflow.module_id == module_id)

    total = query.count()
    workflows = (
        query.order_by(ApprovalWorkflow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    user_map = _load_user_map(db)
    items = [_build_workflow_response(wf, user_map) for wf in workflows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/workflows/{workflow_id}")
def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "view")),
):
    """İş akışı detayı."""
    wf = db.query(ApprovalWorkflow).filter(ApprovalWorkflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="İş akışı bulunamadı")

    user_map = _load_user_map(db)
    return _build_workflow_response(wf, user_map)


@router.post("/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow(
    data: WorkflowCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "use")),
):
    """Yeni iş akışı oluştur (modül + rol tabanlı)."""
    # İsim tekrarı kontrolü — name kolonu DB seviyesinde unique, pasif kayıtlar da dahil
    exists = db.query(ApprovalWorkflow).filter(
        ApprovalWorkflow.name == data.name,
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Bu isimde bir iş akışı zaten mevcut")

    # Modül kontrolü
    module = db.query(Module).filter(Module.id == data.module_id, Module.is_active.is_(True)).first()
    if not module:
        raise HTTPException(status_code=400, detail="Geçersiz veya pasif modül")

    # Rol kontrolü
    all_role_ids = set(data.requestor_role_ids + data.approver_role_ids)
    existing_roles = db.query(Role.id).filter(Role.id.in_(all_role_ids), Role.is_active.is_(True)).all()
    existing_role_ids = {r.id for r in existing_roles}
    missing = all_role_ids - existing_role_ids
    if missing:
        raise HTTPException(status_code=400, detail=f"Geçersiz rol ID'leri: {missing}")

    wf = ApprovalWorkflow(
        name=data.name,
        module_id=data.module_id,
        entity_type=module.code,
        description=data.description,
        is_active=data.is_active,
        conditions_json=data.conditions_json,
        created_by=current_user.id,
    )
    db.add(wf)
    db.flush()

    # Talep eden roller
    for role_id in data.requestor_role_ids:
        db.add(ApprovalWorkflowRequestorRole(workflow_id=wf.id, role_id=role_id))

    # Onay veren roller
    for role_id in data.approver_role_ids:
        db.add(ApprovalWorkflowApproverRole(workflow_id=wf.id, role_id=role_id))

    log_action(db, current_user.id, "create", "approval_workflow", wf.id,
               f"Onay akışı oluşturuldu: {wf.name}", get_client_ip(request))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Bu isimde bir iş akışı zaten mevcut")

    user_map = _load_user_map(db)
    return _build_workflow_response(wf, user_map)


@router.patch("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: int,
    data: WorkflowUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "use")),
):
    """İş akışı güncelle."""
    wf = db.query(ApprovalWorkflow).filter(ApprovalWorkflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="İş akışı bulunamadı")

    if data.name is not None and data.name != wf.name:
        exists = db.query(ApprovalWorkflow).filter(
            ApprovalWorkflow.name == data.name, ApprovalWorkflow.id != workflow_id
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="Bu isimde bir iş akışı zaten mevcut")
        wf.name = data.name

    if data.description is not None:
        wf.description = data.description
    if data.is_active is not None:
        wf.is_active = data.is_active
    if data.conditions_json is not None:
        wf.conditions_json = data.conditions_json

    # Rolleri güncelle
    if data.requestor_role_ids is not None:
        _sync_junction_roles(db, wf.id, data.requestor_role_ids, ApprovalWorkflowRequestorRole)

    if data.approver_role_ids is not None:
        _sync_junction_roles(db, wf.id, data.approver_role_ids, ApprovalWorkflowApproverRole)

    log_action(db, current_user.id, "update", "approval_workflow", wf.id,
               f"Onay akışı güncellendi: {wf.name}", get_client_ip(request))
    db.commit()

    user_map = _load_user_map(db)
    return _build_workflow_response(wf, user_map)


@router.delete("/workflows/{workflow_id}")
def delete_workflow(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.approval", "use")),
):
    """İş akışı sil (pasifleştir)."""
    wf = db.query(ApprovalWorkflow).filter(ApprovalWorkflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="İş akışı bulunamadı")

    wf.is_active = False

    log_action(db, current_user.id, "delete", "approval_workflow", wf.id,
               f"Onay akışı pasifleştirildi: {wf.name}", get_client_ip(request))
    db.commit()
    return {"ok": True}
