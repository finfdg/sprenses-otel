"""Departmanlar modülü — Departman CRUD."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.department import Department
from app.models.user import User
from app.schemas.budget import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
)
from app.utils.approval_check import check_approval
from app.services import department_service
from app.utils.audit import log_action

router = APIRouter(prefix="/departmanlar", tags=["Departmanlar"])


# ─── Liste ──────────────────────────────────────────────

@router.get("/", response_model=List[DepartmentResponse])
def list_departments(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.butce", "view")),
):
    """Tüm departmanları listele (yönetici adıyla birlikte)."""
    departments = (
        db.query(Department)
        .order_by(Department.sort_order, Department.name)
        .all()
    )

    # Yönetici adlarını toplu al (N+1 engeli)
    manager_ids = [d.manager_id for d in departments if d.manager_id]
    manager_map = {}
    if manager_ids:
        managers = db.query(User).filter(User.id.in_(manager_ids)).all()
        manager_map = {
            u.id: f"{u.first_name} {u.last_name}" for u in managers
        }

    return [
        DepartmentResponse(
            id=d.id,
            name=d.name,
            code=d.code,
            manager_id=d.manager_id,
            manager_name=manager_map.get(d.manager_id),
            is_active=d.is_active,
            sort_order=d.sort_order,
            created_at=d.created_at,
        )
        for d in departments
    ]


# ─── Oluştur ───────────────────────────────────────────

@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_department(
    data: DepartmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Yeni departman oluştur."""
    approval_resp = check_approval(db, "finance.butce", 0, current_user.id, "create", {"_target": "department", **data.model_dump()})
    if approval_resp:
        return approval_resp

    dept = department_service.create_department(db, data.model_dump())
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Bu departman adı veya kodu zaten kayıtlı",
        )

    log_action(
        db,
        current_user.id,
        "create",
        "department",
        entity_id=dept.id,
        details=f"{dept.name} ({dept.code})",
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(dept)

    manager_name = None
    if dept.manager_id and dept.manager:
        manager_name = f"{dept.manager.first_name} {dept.manager.last_name}"

    return DepartmentResponse(
        id=dept.id,
        name=dept.name,
        code=dept.code,
        manager_id=dept.manager_id,
        manager_name=manager_name,
        is_active=dept.is_active,
        sort_order=dept.sort_order,
        created_at=dept.created_at,
    )


# ─── Güncelle ──────────────────────────────────────────

@router.patch("/{dept_id}", response_model=DepartmentResponse)
def update_department(
    dept_id: int,
    data: DepartmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Departmanı güncelle."""
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departman bulunamadı")

    approval_resp = check_approval(db, "finance.butce", dept_id, current_user.id, "update", {"_target": "department", **data.model_dump(exclude_unset=True)})
    if approval_resp:
        return approval_resp

    department_service.apply_department_update(db, dept, data.model_dump(exclude_unset=True))

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Bu departman adı veya kodu zaten kayıtlı",
        )

    log_action(
        db,
        current_user.id,
        "update",
        "department",
        entity_id=dept_id,
        details=f"{dept.name} ({dept.code})",
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(dept)

    manager_name = None
    if dept.manager_id and dept.manager:
        manager_name = f"{dept.manager.first_name} {dept.manager.last_name}"

    return DepartmentResponse(
        id=dept.id,
        name=dept.name,
        code=dept.code,
        manager_id=dept.manager_id,
        manager_name=manager_name,
        is_active=dept.is_active,
        sort_order=dept.sort_order,
        created_at=dept.created_at,
    )


# ─── Sil ───────────────────────────────────────────────

@router.delete("/{dept_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    dept_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.butce", "use")),
):
    """Departmanı sil (fatura veya bütçe kaydı varsa engelle)."""
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departman bulunamadı")

    approval_resp = check_approval(db, "finance.butce", dept_id, current_user.id, "delete", {"_target": "department"})
    if approval_resp:
        return approval_resp

    log_action(
        db,
        current_user.id,
        "delete",
        "department",
        entity_id=dept_id,
        details=f"{dept.name} ({dept.code})",
        ip_address=get_client_ip(request),
    )
    try:
        department_service.delete_department(db, dept)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
