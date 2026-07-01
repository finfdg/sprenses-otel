from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.error_log import ErrorLog
from app.models.user import User
from app.utils.sql_search import like_pattern
from app.utils.pagination import page_meta

router = APIRouter()


@router.get("/")
def list_error_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    level: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.error_logs", "view")),
):
    """Hata loglarını listele."""
    query = db.query(ErrorLog)

    if level:
        query = query.filter(ErrorLog.level == level)
    if source:
        query = query.filter(ErrorLog.source.ilike(like_pattern(source), escape="\\"))
    if search:
        query = query.filter(ErrorLog.message.ilike(like_pattern(search), escape="\\"))

    total = query.count()
    logs = (
        query.order_by(ErrorLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for log in logs:
        items.append({
            "id": log.id,
            "level": log.level,
            "source": log.source,
            "message": log.message,
            "traceback": log.traceback,
            "method": log.method,
            "path": log.path,
            "user_id": log.user_id,
            "ip_address": log.ip_address,
            "created_at": log.created_at,
        })

    return page_meta(items, total, page, page_size)


@router.get("/summary")
def error_log_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.error_logs", "view")),
):
    """Hata log özeti — seviye bazlı sayılar."""
    from sqlalchemy import func

    rows = (
        db.query(ErrorLog.level, func.count(ErrorLog.id))
        .group_by(ErrorLog.level)
        .all()
    )
    return {row[0]: row[1] for row in rows}


# ONAY AKIŞI İSTİSNASI (2026-07-01 kararı): Hata logu silme/temizleme salt-teknik,
# idempotent bir bakım işlemidir (iş verisi değil) → bilinçli olarak `check_approval`'dan
# GEÇMEZ. İşlem yalnız `system.error_logs` use izniyle yapılır ve audit'lenir.
@router.delete("/{log_id}")
def delete_error_log(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.error_logs", "use")),
):
    """Tek hata kaydı sil."""
    log = db.query(ErrorLog).filter(ErrorLog.id == log_id).first()
    if not log:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Hata kaydı bulunamadı")
    db.delete(log)
    db.commit()
    return {"ok": True}


@router.delete("/")
def clear_error_logs(
    level: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.error_logs", "use")),
):
    """Hata loglarını temizle (opsiyonel seviye filtresi)."""
    query = db.query(ErrorLog)
    if level:
        query = query.filter(ErrorLog.level == level)
    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}
