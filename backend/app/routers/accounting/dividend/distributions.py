"""Kâr payı dağıtımı CRUD — dağıtım başlığı + pay sahipleri + taksitler + ödeme satırları."""

import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session, joinedload

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.dividend import (
    DividendDistribution,
    DividendInstallment,
    DividendPayment,
    DividendShareholder,
)
from app.models.user import User
from app.schemas.dividend import (
    DividendDistributionCreate,
    DividendDistributionUpdate,
)
from app.services import dividend_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.routers.accounting.dividend._helpers import (
    batch_rollup_stats,
    build_detail_response,
    build_distribution_response,
)

PERM = "accounting.dividend"

router = APIRouter()


# ─── LIST ─────────────────────────────────────────────

@router.get("/")
def list_distributions(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PERM, "view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    year: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    q = db.query(DividendDistribution).options(joinedload(DividendDistribution.creator))
    if year:
        q = q.filter(DividendDistribution.year == year)
    if status:
        q = q.filter(DividendDistribution.status == status)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(
            DividendDistribution.name.ilike(like),
            DividendDistribution.notes.ilike(like),
        ))

    total = q.count()
    items = (
        q.order_by(desc(DividendDistribution.year), desc(DividendDistribution.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    stats = batch_rollup_stats(db, [d.id for d in items])
    from app.utils.pagination import page_meta
    return page_meta(
        [build_distribution_response(d, stats[d.id], d.creator.full_name if d.creator else None) for d in items],
        total, page, page_size,
    )


# ─── YEARS (yıl seçici için — veri olan tüm yıllar) ──
# NOT: "/{distribution_id}" (path param) rotasından ÖNCE tanımlanmalı; aksi halde
# FastAPI "years" segmentini int distribution_id olarak çözmeye çalışır.

@router.get("/years")
def list_years(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PERM, "view")),
):
    """Kâr payı dağıtımı olan distinct yılları döner (yıl seçici sabit aralığa
    takılmasın; gelecekteki yıllara ait dağıtım menüden erişilebilsin)."""
    rows = db.query(DividendDistribution.year).distinct().all()
    return {"years": sorted(r[0] for r in rows if r[0] is not None)}


# ─── GET (detail) ─────────────────────────────────────

@router.get("/{distribution_id}")
def get_distribution(
    distribution_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PERM, "view")),
):
    dist = (
        db.query(DividendDistribution)
        .options(joinedload(DividendDistribution.creator))
        .filter(DividendDistribution.id == distribution_id)
        .first()
    )
    if not dist:
        raise HTTPException(status_code=404, detail="Kâr payı dağıtımı bulunamadı")

    shareholders = (
        db.query(DividendShareholder)
        .filter(DividendShareholder.distribution_id == distribution_id)
        .order_by(DividendShareholder.sort_order)
        .all()
    )
    installments = (
        db.query(DividendInstallment)
        .filter(DividendInstallment.distribution_id == distribution_id)
        .order_by(DividendInstallment.installment_no)
        .all()
    )
    payments = (
        db.query(DividendPayment)
        .filter(DividendPayment.distribution_id == distribution_id)
        .all()
    )
    stats = batch_rollup_stats(db, [distribution_id])[distribution_id]
    return build_detail_response(
        dist, stats, dist.creator.full_name if dist.creator else None,
        shareholders, installments, payments,
    )


# ─── CREATE ───────────────────────────────────────────

@router.post("/", status_code=201)
def create_distribution(
    data: DividendDistributionCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM, "use")),
):
    approval_resp = check_approval(
        db, PERM, 0, current_user.id, "create", data.model_dump(),
    )
    if approval_resp:
        return approval_resp

    try:
        dist = dividend_service.create_distribution(db, data.model_dump(), current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        db, current_user.id, "create", "dividend_distribution", dist.id,
        json.dumps({
            "name": data.name, "total_gross": data.total_gross,
            "installment_count": data.installment_count,
            "shareholders": len(data.shareholders),
        }, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ACCOUNTING, "create")
    db.refresh(dist)

    shareholders = (
        db.query(DividendShareholder).filter(DividendShareholder.distribution_id == dist.id)
        .order_by(DividendShareholder.sort_order).all()
    )
    installments = (
        db.query(DividendInstallment).filter(DividendInstallment.distribution_id == dist.id)
        .order_by(DividendInstallment.installment_no).all()
    )
    payments = db.query(DividendPayment).filter(DividendPayment.distribution_id == dist.id).all()
    stats = batch_rollup_stats(db, [dist.id])[dist.id]
    return build_detail_response(
        dist, stats, current_user.full_name, shareholders, installments, payments,
    )


# ─── UPDATE (metadata) ────────────────────────────────

@router.patch("/{distribution_id}")
def update_distribution(
    distribution_id: int,
    data: DividendDistributionUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM, "use")),
):
    dist = db.query(DividendDistribution).filter(
        DividendDistribution.id == distribution_id,
    ).first()
    if not dist:
        raise HTTPException(status_code=404, detail="Kâr payı dağıtımı bulunamadı")

    approval_resp = check_approval(
        db, PERM, distribution_id, current_user.id, "update",
        data.model_dump(exclude_unset=True),
    )
    if approval_resp:
        return approval_resp

    dividend_service.apply_distribution_update(db, dist, data.model_dump(exclude_unset=True))

    log_action(
        db, current_user.id, "update", "dividend_distribution", dist.id,
        json.dumps(data.model_dump(exclude_unset=True), ensure_ascii=False, default=str),
        get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ACCOUNTING, "update")
    db.refresh(dist)
    stats = batch_rollup_stats(db, [dist.id])[dist.id]
    return build_distribution_response(dist, stats, current_user.full_name)


# ─── DELETE ───────────────────────────────────────────

@router.delete("/{distribution_id}")
def delete_distribution(
    distribution_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM, "use")),
):
    dist = db.query(DividendDistribution).filter(
        DividendDistribution.id == distribution_id,
    ).first()
    if not dist:
        raise HTTPException(status_code=404, detail="Kâr payı dağıtımı bulunamadı")

    approval_resp = check_approval(db, PERM, distribution_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    log_action(
        db, current_user.id, "delete", "dividend_distribution", dist.id,
        json.dumps({"name": dist.name, "total_gross": float(dist.total_gross)}, ensure_ascii=False),
        get_client_ip(request),
    )
    dividend_service.delete_distribution(db, dist)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ACCOUNTING, "delete")
    return {"detail": "Kâr payı dağıtımı silindi"}
