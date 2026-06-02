"""Otel günlük doluluk endpoint'i — aylık bar'ın drill-down'ı."""

import calendar
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.schemas.reservation import DailyOccupancyResponse, DailyOccupancyRow

from ._helpers import _apply_filters

router = APIRouter()


@router.get("/daily-occupancy")
def daily_occupancy(
    month: str = Query(..., description="YYYY-MM formatı (örn. 2026-05)"),
    agency: Optional[str] = Query(None),
    nation: Optional[str] = Query(None),
    room_type: Optional[str] = Query(None),
    rez_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.hotel_reservation", "view")),
):
    """Belirli bir ayın günlük doluluk dağılımı — aylık bar'ın drill-down'ı.

    Her gün için: dolu/boş oda, doluluk %, ciro, check-in/out sayıları.
    `total_capacity` (otelin fiziksel oda sayısı) tüm günlerde sabit payda.
    """
    # ── Ay parametresi parse ───────────────────────────────
    try:
        year_str, month_str = month.split("-")
        y = int(year_str)
        m = int(month_str)
        if not (1 <= m <= 12) or not (1900 <= y <= 2200):
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="Geçersiz ay formatı. Beklenen: YYYY-MM (örn. 2026-05)",
        )

    month_start = date_cls(y, m, 1)
    last_day = calendar.monthrange(y, m)[1]
    month_end = date_cls(y, m, last_day)

    # ── Toplam kapasite (sabit payda) ──────────────────────
    total_capacity = int(
        db.query(func.coalesce(func.sum(RoomType.total_rooms), 0))
        .filter(RoomType.is_active.is_(True))
        .scalar() or 0
    )

    # ── Filtre kapsamındaki rez ID'leri (aya değen) ────────
    base_q = _apply_filters(
        db.query(Reservation.id), None, None, agency, nation, room_type, rez_status, search,
    ).filter(
        Reservation.checkin_date <= month_end,
        Reservation.checkout_date > month_start,
    )
    filtered_ids = [row[0] for row in base_q.all()]

    # ── Günlük aggregation ─────────────────────────────────
    rows = db.execute(
        text("""
            SELECT
                gs::date AS day,
                (EXTRACT(ISODOW FROM gs)::int - 1) AS weekday,
                COALESCE(SUM(r.rooms), 0)::int AS room_nights,
                COALESCE(SUM(r.adult + r.child_paid + r.child_free + r.baby), 0)::int AS pax,
                COALESCE(SUM(CASE WHEN r.nights > 0 THEN r.eur_total / r.nights ELSE 0 END), 0)::float AS eur,
                COALESCE(COUNT(DISTINCT CASE WHEN r.checkin_date = gs::date THEN r.id END), 0)::int AS ci,
                COALESCE(COUNT(DISTINCT CASE WHEN r.checkout_date = gs::date THEN r.id END), 0)::int AS co
            FROM generate_series(CAST(:s AS timestamp), CAST(:e AS timestamp), INTERVAL '1 day') AS gs
            LEFT JOIN reservations r ON (
                r.id = ANY(:ids)
                AND r.checkin_date <= gs::date
                AND r.checkout_date > gs::date
            )
            GROUP BY day, weekday
            ORDER BY day
        """),
        {
            "s": month_start,
            "e": month_end,
            "ids": filtered_ids if filtered_ids else [0],  # boş array PG'de problem yaratıyor
        },
    ).fetchall()

    days: list = []
    occ_values: list = []
    for r in rows:
        d = r[0]
        wd = int(r[1] or 0)
        rn = int(r[2] or 0)
        empty = max(total_capacity - rn, 0)
        occ_pct = (rn / total_capacity * 100) if total_capacity > 0 else 0.0
        occ_values.append((occ_pct, d))
        days.append(DailyOccupancyRow(
            date=d,
            weekday=wd,
            room_nights=rn,
            capacity=total_capacity,
            empty=empty,
            occupancy_pct=round(occ_pct, 2),
            pax=int(r[3] or 0),
            eur=round(float(r[4] or 0), 2),
            checkin_count=int(r[5] or 0),
            checkout_count=int(r[6] or 0),
        ))

    avg_occ = (sum(v for v, _ in occ_values) / len(occ_values)) if occ_values else 0.0
    peak = max(occ_values, key=lambda x: x[0]) if occ_values else (0.0, None)
    low = min(occ_values, key=lambda x: x[0]) if occ_values else (0.0, None)

    return DailyOccupancyResponse(
        month=month,
        days=days,
        total_capacity=total_capacity,
        avg_occupancy_pct=round(avg_occ, 2),
        peak_date=peak[1],
        peak_occupancy_pct=round(peak[0], 2),
        low_date=low[1],
        low_occupancy_pct=round(low[0], 2),
    ).model_dump(mode="json")
