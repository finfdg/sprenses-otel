"""Otel rezervasyon dashboard özeti — tek istekte tüm KPI ve dağılımlar."""

import statistics
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, extract, func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.schemas.reservation import (
    AgencyRow,
    BoardRow,
    KpiData,
    LeadTimeStats,
    LosBucket,
    MonthlyRow,
    NationRow,
    PickupRow,
    SummaryResponse,
    TypeRow,
)

from ._helpers import _apply_filters, _month_days_in_range, _resolve_date_range

router = APIRouter()


@router.get("/years")
def reservation_years(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.hotel_reservation", "view")),
):
    """Yıl filtresi seçenekleri — rezervasyon VERİSİNDE gerçekten geçen yıllar.

    Yükleme periyodunun yalnız başlangıç/bitiş yılını kullanmak yıl atlıyordu (ör.
    periyot 2026→2030 ise 2027/2028/2029 seçilemiyordu ve o yıllara ait rezervasyonlar
    hiç gösterilemiyordu). Burada check-in VE check-out yıllarının birleşimi alınır →
    yıl sınırına taşan konaklamalar (ör. 26 Ara → 3 Oca) her iki yılda da seçilebilir;
    verisi olmayan yıllar (yükleme periyodu artığı) listeye girmez.
    """
    rows = db.execute(
        text("""
            SELECT DISTINCT y FROM (
                SELECT EXTRACT(YEAR FROM checkin_date)::int AS y FROM reservations
                UNION
                SELECT EXTRACT(YEAR FROM checkout_date)::int AS y FROM reservations
            ) t
            WHERE y IS NOT NULL
            ORDER BY y DESC
        """)
    ).fetchall()
    return {"years": [int(r[0]) for r in rows]}


@router.get("/summary")
def reservation_summary(
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
    """Dashboard için tek istekte tüm özet veriler."""
    base_filter_args = (start_date, end_date, agency, nation, room_type, rez_status, search)

    def q():
        return _apply_filters(db.query(Reservation), *base_filter_args)

    # ── KPI ────────────────────────────────────────────────
    nights_col = Reservation.nights
    rooms_col = Reservation.rooms
    pax_col = (
        func.coalesce(Reservation.adult, 0)
        + func.coalesce(Reservation.child_paid, 0)
        + func.coalesce(Reservation.child_free, 0)
        + func.coalesce(Reservation.baby, 0)
    )

    kpi_row = q().with_entities(
        func.count(Reservation.id),
        func.coalesce(func.sum(Reservation.eur_total), 0),
        func.coalesce(func.sum(rooms_col * nights_col), 0),
        func.coalesce(func.sum(pax_col * nights_col), 0),
        func.coalesce(func.sum(pax_col), 0),
        func.coalesce(func.sum(Reservation.adult), 0),
        func.coalesce(func.sum(Reservation.child_paid), 0),
        func.coalesce(func.sum(Reservation.child_free), 0),
        func.coalesce(func.sum(Reservation.baby), 0),
    ).first()

    total_rez = int(kpi_row[0] or 0)
    total_eur = float(kpi_row[1] or 0)
    total_room_nights = int(kpi_row[2] or 0)
    total_guest_nights = int(kpi_row[3] or 0)
    total_pax = int(kpi_row[4] or 0)
    total_adult = int(kpi_row[5] or 0)
    total_child_paid = int(kpi_row[6] or 0)
    total_child_free = int(kpi_row[7] or 0)
    total_baby = int(kpi_row[8] or 0)

    adr = (total_eur / total_room_nights) if total_room_nights else 0.0
    avg_los = (total_room_nights / total_rez) if total_rez else 0.0

    definite_count = q().filter(Reservation.rez_status == "Definite").count()
    option_count = q().filter(Reservation.rez_status == "Option").count()

    # ── Filtre kapsamındaki rezervasyon ID'leri (doluluk + aylık dağılım için) ──
    filtered_ids = [row[0] for row in _apply_filters(
        db.query(Reservation.id), *base_filter_args,
    ).all()]

    # ── Doluluk metrikleri ─────────────────────────────────
    # Toplam kapasite: aktif room_types.total_rooms toplamı (otelin fiziksel oda sayısı)
    total_capacity = int(
        db.query(func.coalesce(func.sum(RoomType.total_rooms), 0))
        .filter(RoomType.is_active.is_(True))
        .scalar() or 0
    )

    # Tip başına kapasite haritası (by_room_type doluluk hesabında kullanılır)
    type_capacity_map = {
        rt.code: rt.total_rooms
        for rt in db.query(RoomType.code, RoomType.total_rooms)
        .filter(RoomType.is_active.is_(True))
        .all()
    }

    # Tarih aralığı + gün sayısı (filtreden veya rezervasyonlardan)
    range_start, range_end, date_range_days = _resolve_date_range(
        db, start_date, end_date, filtered_ids,
    )

    # Doluluk yüzdesi: room_nights / (total_capacity × gün) × 100
    if total_capacity > 0 and date_range_days > 0:
        occupancy_pct = (total_room_nights / (total_capacity * date_range_days)) * 100
    else:
        occupancy_pct = 0.0

    kpi = KpiData(
        total_rez=total_rez,
        total_eur=round(total_eur, 2),
        total_room_nights=total_room_nights,
        total_guest_nights=total_guest_nights,
        total_pax=total_pax,
        total_adult=total_adult,
        total_child_paid=total_child_paid,
        total_child_free=total_child_free,
        total_baby=total_baby,
        adr=round(adr, 2),
        avg_los=round(avg_los, 2),
        definite_count=definite_count,
        option_count=option_count,
        total_capacity=total_capacity,
        date_range_days=date_range_days,
        occupancy_pct=round(occupancy_pct, 2),
    )

    # ── Aylık dağılım — gece bazlı (stay-night attribution) ──
    # Bir rezervasyon birden fazla aya yayılıyorsa, her gece kendi ayına yazılır
    # ve eur_total gece sayısına bölünerek aylara orantılanır.
    # Örnek: 28 Mart → 7 Nisan (10 gece, 1000 EUR) → Mart'a 4 gece 400 EUR, Nisan'a 6 gece 600 EUR.
    # ΣΣ room_nights = KPI.total_room_nights, ΣΣ eur = KPI.total_eur ile uyumlu kalır.
    # Rez sayısı bir rezervasyon iki aya düştüğünde iki ayda da +1 sayılır (DISTINCT içinde).
    if not filtered_ids:
        monthly = []
    else:
        monthly_rows = db.execute(
            text("""
                SELECT
                    EXTRACT(YEAR FROM gs)::int AS y,
                    EXTRACT(MONTH FROM gs)::int AS m,
                    COUNT(DISTINCT r.id) AS rez,
                    COALESCE(SUM(r.rooms), 0)::int AS room_nights,
                    COALESCE(SUM(r.adult + r.child_paid + r.child_free + r.baby), 0)::int AS guest_nights,
                    COALESCE(SUM(CASE WHEN r.nights > 0 THEN r.eur_total / r.nights ELSE 0 END), 0) AS eur
                FROM reservations r
                JOIN LATERAL generate_series(
                    r.checkin_date::timestamp,
                    (r.checkout_date - INTERVAL '1 day')::timestamp,
                    INTERVAL '1 day'
                ) AS gs ON TRUE
                WHERE r.id = ANY(:ids)
                GROUP BY y, m
                ORDER BY y, m
            """),
            {"ids": filtered_ids},
        ).fetchall()
        monthly = []
        for r in monthly_rows:
            y = int(r[0])
            m = int(r[1])
            month_room_nights = int(r[3] or 0)
            # Ayın filtre aralığındaki gün sayısı (filtre yoksa tüm ay)
            month_days = _month_days_in_range(y, m, range_start, range_end)
            capacity_nights = total_capacity * month_days
            empty_nights = max(capacity_nights - month_room_nights, 0)
            if capacity_nights > 0:
                month_occ_pct = (month_room_nights / capacity_nights) * 100
            else:
                month_occ_pct = 0.0
            # Filtre dışına taşan aylar (capacity=0) UI'da kafa karıştırıcı —
            # ayın hiçbir günü filtre kapsamında değilse atla.
            # Örnek: filtre 2026 ise 2027-01'e taşan 1-2 gün gösterilmez.
            if range_start and range_end and capacity_nights == 0:
                continue
            monthly.append(MonthlyRow(
                month=f"{y}-{m:02d}",
                rez=int(r[2] or 0),
                room_nights=month_room_nights,
                pax=int(r[4] or 0),
                eur=round(float(r[5] or 0), 2),
                capacity_nights=capacity_nights,
                empty_nights=empty_nights,
                occupancy_pct=round(month_occ_pct, 2),
            ))

    # ── Acente dağılımı (tümü — frontend toplam göstergesi için tam liste) ──
    agency_rows = (
        q().with_entities(
            Reservation.agency,
            func.count(Reservation.id),
            func.coalesce(func.sum(rooms_col * nights_col), 0),
            func.coalesce(func.sum(pax_col), 0),
            func.coalesce(func.sum(Reservation.eur_total), 0),
        )
        .group_by(Reservation.agency)
        .order_by(desc(func.sum(Reservation.eur_total)))
        .all()
    )
    by_agency = [
        AgencyRow(
            name=r[0] or "(boş)",
            rez=int(r[1] or 0),
            room_nights=int(r[2] or 0),
            pax=int(r[3] or 0),
            eur=round(float(r[4] or 0), 2),
            pct=round((float(r[4] or 0) / total_eur * 100) if total_eur else 0, 2),
        )
        for r in agency_rows
    ]

    # ── Ulus (Top 15) ───────────────────────────────────────
    nation_rows = (
        q().with_entities(
            Reservation.nation,
            func.count(Reservation.id),
            func.coalesce(func.sum(rooms_col * nights_col), 0),
            func.coalesce(func.sum(Reservation.eur_total), 0),
        )
        .group_by(Reservation.nation)
        .order_by(desc(func.sum(Reservation.eur_total)))
        .limit(15)
        .all()
    )
    by_nation = [
        NationRow(
            code=r[0] or "??",
            rez=int(r[1] or 0),
            room_nights=int(r[2] or 0),
            eur=round(float(r[3] or 0), 2),
            pct=round((float(r[3] or 0) / total_eur * 100) if total_eur else 0, 2),
        )
        for r in nation_rows
    ]

    # ── Oda tipi (tümü) ─────────────────────────────────────
    type_rows = (
        q().with_entities(
            Reservation.room_type,
            func.count(Reservation.id),
            func.coalesce(func.sum(rooms_col * nights_col), 0),
            func.coalesce(func.sum(Reservation.eur_total), 0),
        )
        .group_by(Reservation.room_type)
        .order_by(desc(func.sum(Reservation.eur_total)))
        .all()
    )
    by_room_type = []
    for r in type_rows:
        type_name = r[0] or "(boş)"
        type_room_nights = int(r[2] or 0)
        type_capacity = type_capacity_map.get(r[0] or "", 0)
        if type_capacity > 0 and date_range_days > 0:
            type_occ_pct = (type_room_nights / (type_capacity * date_range_days)) * 100
        else:
            type_occ_pct = 0.0
        by_room_type.append(TypeRow(
            name=type_name,
            rez=int(r[1] or 0),
            room_nights=type_room_nights,
            eur=round(float(r[3] or 0), 2),
            pct=round((float(r[3] or 0) / total_eur * 100) if total_eur else 0, 2),
            total_rooms=type_capacity,
            occupancy_pct=round(type_occ_pct, 2),
        ))

    # ── Pansiyon / Board ────────────────────────────────────
    board_rows = (
        q().with_entities(
            Reservation.board,
            func.count(Reservation.id),
            func.coalesce(func.sum(Reservation.eur_total), 0),
        )
        .group_by(Reservation.board)
        .order_by(desc(func.sum(Reservation.eur_total)))
        .all()
    )
    by_board = [
        BoardRow(
            name=r[0] or "(boş)",
            rez=int(r[1] or 0),
            eur=round(float(r[2] or 0), 2),
            pct=round((float(r[2] or 0) / total_eur * 100) if total_eur else 0, 2),
        )
        for r in board_rows
    ]

    # ── Pickup (record_date bazlı) ──────────────────────────
    pickup_rows = (
        q().with_entities(
            extract("year", Reservation.record_date).label("y"),
            extract("month", Reservation.record_date).label("m"),
            func.count(Reservation.id),
            func.coalesce(func.sum(Reservation.eur_total), 0),
        )
        .group_by("y", "m")
        .order_by("y", "m")
        .all()
    )
    pickup = [
        PickupRow(
            month=f"{int(r[0])}-{int(r[1]):02d}",
            rez=int(r[2] or 0),
            eur=round(float(r[3] or 0), 2),
            pct=round((float(r[3] or 0) / total_eur * 100) if total_eur else 0, 2),
        )
        for r in pickup_rows
    ]

    # ── Konaklama uzunluğu (LOS) bucket'ları ────────────────
    # 1-14: gece sayısı string'i / 15-21: "15-21" / 22+: "22+"
    los_raw = (
        q().with_entities(
            nights_col.label("n"),
            func.count(Reservation.id),
        )
        .group_by(nights_col)
        .order_by(nights_col)
        .all()
    )
    bucket_counts: dict = {}
    for n, c in los_raw:
        n_int = int(n or 0)
        if n_int <= 0:
            continue
        if n_int <= 14:
            bucket = str(n_int)
        elif n_int <= 21:
            bucket = "15-21"
        else:
            bucket = "22+"
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + int(c)
    los_order = [str(i) for i in range(1, 15)] + ["15-21", "22+"]
    los_buckets = [LosBucket(bucket=b, count=bucket_counts[b]) for b in los_order if b in bucket_counts]

    # ── Lead time (record → check-in) ───────────────────────
    lead_rows = (
        q().with_entities(
            (Reservation.checkin_date - Reservation.record_date).label("lead"),
        ).all()
    )
    lead_days = [int(getattr(r, "lead", r[0]).days if hasattr(getattr(r, "lead", r[0]), "days") else r[0])
                 for r in lead_rows if r[0] is not None]
    if lead_days:
        lead_avg = round(sum(lead_days) / len(lead_days), 1)
        lead_median = int(statistics.median(lead_days))
        lead_stats = LeadTimeStats(avg=lead_avg, median=lead_median, min=min(lead_days), max=max(lead_days))
    else:
        lead_stats = LeadTimeStats(avg=0.0, median=0, min=0, max=0)

    return SummaryResponse(
        kpi=kpi,
        monthly=monthly,
        by_agency=by_agency,
        by_nation=by_nation,
        by_room_type=by_room_type,
        by_board=by_board,
        pickup=pickup,
        los_buckets=los_buckets,
        lead_time=lead_stats,
    ).model_dump(mode="json")
