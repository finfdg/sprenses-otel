"""Audit log endpoint'leri — sayfalanmış listeleme ve filtreleme."""

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


@router.get("/")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.audit_logs", "view")),
):
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # Kullanıcı bilgilerini toplu al
    user_ids = list({log.user_id for log in logs if log.user_id})
    user_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        user_map = {u.id: u for u in users}

    items = []
    for log in logs:
        user = user_map.get(log.user_id)
        items.append({
            "id": log.id,
            "user_id": log.user_id,
            "username": user.username if user else None,
            "user_full_name": f"{user.first_name} {user.last_name}" if user else None,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "created_at": log.created_at,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }
