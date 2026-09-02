"""Doluluk (occupancy) metrikleri — rezervasyon verisinden geceleme/oda-gece/ADR.

Maliyet kontrol modülü tüketim maliyetini (Sedna stok) doluluğa böler (kişi başı maliyet,
CPOR). Geceleme **occupancy-overlap** ile hesaplanır (generate_series): bir konaklama birden
çok aya yayılırsa her ayın gecelemesine doğru pay düşer — stok tüketim ayıyla eşleşir.

pax = adult + child_paid + child_free + baby. checkout_date EXCLUSIVE.
"""
from datetime import date as date_cls
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.reservation import Reservation
from app.models.room_type import RoomType


def _reservation_span(db: Session):
    """Tüm rezervasyonların min(checkin) ↔ max(checkout) aralığı (varsayılan aralık)."""
    row = db.query(func.min(Reservation.checkin_date), func.max(Reservation.checkout_date)).first()
    return (row[0], row[1]) if row else (None, None)


def guest_nights_by_period(db: Session, start: date_cls, end: date_cls) -> dict:
    """Her takvim ayı (YYYY-MM) için occupancy-overlap geceleme/oda-gece/pax/gelir.

    Döner: {period: {guest_nights, room_nights, eur, rez}}.
    """
    if not start or not end or end < start:
        return {}
    rows = db.execute(text("""
        SELECT to_char(d.day, 'YYYY-MM') AS period,
               COALESCE(SUM(r.adult + r.child_paid + r.child_free + r.baby), 0) AS guest_nights,
               COALESCE(SUM(r.rooms), 0) AS room_nights,
               COALESCE(SUM(CASE WHEN r.nights > 0 THEN r.eur_total / r.nights ELSE 0 END), 0) AS eur,
               COUNT(DISTINCT r.id) AS rez
        FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') AS d(day)
        LEFT JOIN reservations r
          ON r.checkin_date <= d.day AND r.checkout_date > d.day
        GROUP BY to_char(d.day, 'YYYY-MM')
        ORDER BY period
    """), {"start": start, "end": end}).fetchall()
    return {
        r.period: {
            "guest_nights": int(r.guest_nights or 0),
            "room_nights": int(r.room_nights or 0),
            "eur": float(r.eur or 0),
            "rez": int(r.rez or 0),
        }
        for r in rows
    }


def occupancy_metrics(db: Session, start: Optional[date_cls] = None, end: Optional[date_cls] = None) -> dict:
    """Aralık için toplam doluluk: oda-gece, geceleme, pax, doluluk %, ADR/RevPAR (EUR)."""
    if not start or not end:
        s, e = _reservation_span(db)
        start = start or s
        end = end or e
    by = guest_nights_by_period(db, start, end)
    room_nights = sum(v["room_nights"] for v in by.values())
    guest_nights = sum(v["guest_nights"] for v in by.values())
    eur = sum(v["eur"] for v in by.values())

    capacity = int(
        db.query(func.coalesce(func.sum(RoomType.total_rooms), 0))
        .filter(RoomType.is_active.is_(True)).scalar() or 0
    )
    days = (end - start).days + 1 if (start and end) else 0
    capacity_nights = capacity * days
    occupancy_pct = round(room_nights / capacity_nights * 100, 1) if capacity_nights else 0.0
    adr = round(eur / room_nights, 2) if room_nights else 0.0          # ortalama oda fiyatı (EUR)
    revpar = round(eur / capacity_nights, 2) if capacity_nights else 0.0  # mevcut oda başına gelir

    return {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "room_nights": room_nights, "guest_nights": guest_nights,
        "capacity": capacity, "occupancy_pct": occupancy_pct,
        "revenue_eur": round(eur, 2), "adr_eur": adr, "revpar_eur": revpar,
        "by_period": by,
    }
