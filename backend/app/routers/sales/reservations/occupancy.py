"""Otel günlük doluluk endpoint'leri — yıllık genel bakış + aylık bar'ın drill-down'ı."""

import calendar
from datetime import date as date_cls
from datetime import datetime
from typing import Optional

import pytz
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

# Tarih-kritik "bugün" hesapları İstanbul-açık yapılır (sunucu UTC — CLAUDE.md kuralı)
_TZ_ISTANBUL = pytz.timezone("Europe/Istanbul")


def _capacity(db: Session) -> int:
    """Aktif oda tiplerinin toplam oda sayısı (otelin fiziksel kapasitesi)."""
    return int(
        db.query(func.coalesce(func.sum(RoomType.total_rooms), 0))
        .filter(RoomType.is_active.is_(True))
        .scalar() or 0
    )


@router.get("/occupancy-overview")
def occupancy_overview(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.acente_mahsup", "view")),
):
    """Doluluk genel bakışı — yeni Doluluk sekmesinin tek-istek veri kaynağı.

    Seçili yılın 12 ayı için oda-gece toplamı, GERÇEKLEŞEN (gece tarihi ≤ bugün)
    ve İLERİ REZERVASYON (gece tarihi > bugün) kırılımıyla döner; üstteki özet
    kartları (bugün / cari ay / yıl ortalaması) için her zaman GERÇEK bugüne göre
    hesaplanan değerler de taşınır. Aylık dağıtım gece bazlıdır (generate_series)
    — `reservations/summary` ile birebir aynı yöntem. Her ay için ayrıca EUR ciro
    (eur_total gece sayısına bölünerek aylara orantılanır — summary/agency-status
    ile aynı dağıtım) ve gerçekleşen/ileri ciro kırılımı döner (bar üstü etiket +
    yıl karşılaştırma görünümünün veri kaynağı).
    """
    today = datetime.now(_TZ_ISTANBUL).date()
    y = year or today.year

    total_capacity = _capacity(db)

    # ── Seçili yılın ayları: oda-gece toplam + gerçekleşen/ileri kırılımı ──
    month_rows = db.execute(
        text("""
            SELECT
                EXTRACT(MONTH FROM gs)::int AS m,
                COALESCE(SUM(r.rooms), 0)::int AS room_nights,
                COALESCE(SUM(CASE WHEN gs::date <= :today THEN r.rooms ELSE 0 END), 0)::int AS past_nights,
                COALESCE(SUM(CASE WHEN r.nights > 0 THEN r.eur_total / r.nights ELSE 0 END), 0)::float AS eur,
                COALESCE(SUM(CASE WHEN r.nights > 0 AND gs::date <= :today THEN r.eur_total / r.nights ELSE 0 END), 0)::float AS past_eur
            FROM reservations r
            JOIN LATERAL generate_series(
                r.checkin_date::timestamp,
                (r.checkout_date - INTERVAL '1 day')::timestamp,
                INTERVAL '1 day'
            ) AS gs ON TRUE
            WHERE EXTRACT(YEAR FROM gs) = :year
            GROUP BY m
        """),
        {"year": y, "today": today},
    ).fetchall()
    by_month = {
        int(r[0]): (int(r[1] or 0), int(r[2] or 0), float(r[3] or 0), float(r[4] or 0))
        for r in month_rows
    }

    months = []
    year_room_nights = 0
    year_capacity_nights = 0
    year_eur = 0.0
    for m in range(1, 13):
        rn, past, eur, past_eur = by_month.get(m, (0, 0, 0.0, 0.0))
        cap_nights = total_capacity * calendar.monthrange(y, m)[1]
        year_room_nights += rn
        year_capacity_nights += cap_nights
        year_eur += eur
        months.append({
            "month": m,
            "room_nights": rn,
            "past_nights": past,
            "future_nights": max(rn - past, 0),
            "capacity_nights": cap_nights,
            "occupancy_pct": round(rn / cap_nights * 100, 2) if cap_nights > 0 else 0.0,
            "eur": round(eur, 2),
            "past_eur": round(past_eur, 2),
            "future_eur": round(max(eur - past_eur, 0.0), 2),
        })

    # ── Özet kartları: bugün + cari ay (seçili yıldan bağımsız, gerçek bugün) ──
    today_rooms = int(
        db.query(func.coalesce(func.sum(Reservation.rooms), 0))
        .filter(Reservation.checkin_date <= today, Reservation.checkout_date > today)
        .scalar() or 0
    )
    cm_row = db.execute(
        text("""
            SELECT COALESCE(SUM(r.rooms), 0)::int
            FROM reservations r
            JOIN LATERAL generate_series(
                r.checkin_date::timestamp,
                (r.checkout_date - INTERVAL '1 day')::timestamp,
                INTERVAL '1 day'
            ) AS gs ON TRUE
            WHERE EXTRACT(YEAR FROM gs) = :ty AND EXTRACT(MONTH FROM gs) = :tm
        """),
        {"ty": today.year, "tm": today.month},
    ).scalar()
    cm_nights = int(cm_row or 0)
    cm_cap_nights = total_capacity * calendar.monthrange(today.year, today.month)[1]

    return {
        "year": y,
        "today": today.isoformat(),
        "capacity": total_capacity,
        "today_rooms": today_rooms,
        "today_pct": round(today_rooms / total_capacity * 100, 2) if total_capacity > 0 else 0.0,
        "current_month": {
            "month": today.month,
            "room_nights": cm_nights,
            "capacity_nights": cm_cap_nights,
            "occupancy_pct": round(cm_nights / cm_cap_nights * 100, 2) if cm_cap_nights > 0 else 0.0,
        },
        "months": months,
        "year_room_nights": year_room_nights,
        "year_capacity_nights": year_capacity_nights,
        "year_pct": round(year_room_nights / year_capacity_nights * 100, 2) if year_capacity_nights > 0 else 0.0,
        "year_eur": round(year_eur, 2),
    }


@router.get("/daily-occupancy")
def daily_occupancy(
    month: str = Query(..., description="YYYY-MM formatı (örn. 2026-05)"),
    agency: Optional[str] = Query(None),
    nation: Optional[str] = Query(None),
    room_type: Optional[str] = Query(None),
    rez_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.acente_mahsup", "view")),
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
    total_capacity = _capacity(db)

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
