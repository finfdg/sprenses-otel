"""Otel rezervasyon listesi — sayfalanmış, filtrelenebilir."""

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import ReservationResponse

from ._helpers import _apply_filters

router = APIRouter()


@router.get("/")
def list_reservations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    agency: Optional[str] = Query(None),
    nation: Optional[str] = Query(None),
    room_type: Optional[str] = Query(None),
    rez_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.hotel_reservation", "view")),
):
    """Rezervasyon listesi — sayfalanmış, filtrelenebilir."""
    query = _apply_filters(
        db.query(Reservation),
        start_date, end_date, agency, nation, room_type, rez_status, search,
    )

    total = query.count()
    items = (
        query.order_by(Reservation.checkin_date.desc(), Reservation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [ReservationResponse.model_validate(r).model_dump(mode="json") for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }
