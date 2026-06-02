"""Otel rezervasyon paketinde paylaşılan yardımcı fonksiyonlar ve sabitler."""

import calendar
import logging
import os
from datetime import date as date_cls
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.reservation import Reservation

logger = logging.getLogger(__name__)

# `reservations/` paketi 4 seviye derinlikte: backend/app/routers/sales/reservations/_helpers.py
# UPLOAD_DIR — backend/uploads/reservation_files
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))),
    "uploads", "reservation_files",
)


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _parse_date(value: Optional[str]) -> Optional[date_cls]:
    """ISO tarih string'ini date'e çevir, hatalıysa None döndür."""
    if not value:
        return None
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _resolve_date_range(
    db: Session,
    start_date_str: Optional[str],
    end_date_str: Optional[str],
    filtered_ids: list,
) -> Tuple[Optional[date_cls], Optional[date_cls], int]:
    """Doluluk paydası için tarih aralığını çöz.

    Hiyerarşi:
    1. Hem start hem end verildi → (start, end, end-start+1 gün)
    2. Yalnızca biri verildi veya hiçbiri yok → rezervasyonların min(checkin) ↔ max(checkout)
       aralığı kullanılır. checkout exclusive olduğundan gün sayısı = max_co - min_ci.
    3. Hiç rezervasyon yoksa → (None, None, 0)
    """
    sd = _parse_date(start_date_str)
    ed = _parse_date(end_date_str)

    if sd and ed:
        days = (ed - sd).days + 1
        return sd, ed, max(days, 0)

    if not filtered_ids:
        return sd, ed, 0

    row = (
        db.query(
            func.min(Reservation.checkin_date),
            func.max(Reservation.checkout_date),
        )
        .filter(Reservation.id.in_(filtered_ids))
        .first()
    )
    if not row or not row[0] or not row[1]:
        return sd, ed, 0
    min_ci, max_co = row[0], row[1]
    days = (max_co - min_ci).days  # checkout exclusive
    return (sd or min_ci), (ed or max_co), max(days, 0)


def _month_days_in_range(
    year: int, month: int, range_start: Optional[date_cls], range_end: Optional[date_cls],
) -> int:
    """Belirtilen ay ile tarih aralığının kesişimindeki gün sayısı.

    Aylık doluluk için kullanılır. Filtre verilmemişse o ayın tüm günleri döner.
    """
    month_start = date_cls(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    month_end = date_cls(year, month, last_day)

    if range_start and range_start > month_start:
        month_start = range_start
    if range_end and range_end < month_end:
        month_end = range_end

    if month_end < month_start:
        return 0
    return (month_end - month_start).days + 1


def _apply_filters(query, start_date, end_date, agency, nation, room_type, rez_status, search):
    """Ortak filtre uygulayıcı — listeleme ve özette aynı filtreler kullanılır."""
    if start_date:
        try:
            sd = date_cls.fromisoformat(start_date)
            query = query.filter(Reservation.checkin_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = date_cls.fromisoformat(end_date)
            query = query.filter(Reservation.checkin_date <= ed)
        except ValueError:
            pass
    if agency:
        query = query.filter(Reservation.agency == agency)
    if nation:
        query = query.filter(Reservation.nation == nation)
    if room_type:
        query = query.filter(Reservation.room_type == room_type)
    if rez_status:
        query = query.filter(Reservation.rez_status == rez_status)
    if search and search.strip():
        s = search.strip()[:200].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{s}%"
        query = query.filter(
            (Reservation.guests.ilike(pattern, escape="\\")) |
            (Reservation.voucher.ilike(pattern, escape="\\")) |
            (Reservation.agency.ilike(pattern, escape="\\"))
        )
    return query
