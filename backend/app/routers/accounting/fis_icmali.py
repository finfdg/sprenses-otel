"""Kullanıcı Fiş İcmali — Sedna muhasebe fişlerini KESEN kullanıcıya göre gün/ay icmali.

Canlı Sedna sorgusu (yerel saklama yok): `AccountingOwner.RecordUser` (fişi kesen) + `Users`
(tam ad). Kullanıcı × dönem (gün/ay) pivot. Tarih ekseni `record` (kayıt = ne zaman girdi) veya
`fiche` (muhasebe tarihi). Salt-okunur; tünel kapalıysa 503.
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.utils.sedna_client import SednaUnavailable, fetch_voucher_summary, sedna_configured

logger = logging.getLogger(__name__)

_MAX_RANGE_DAYS = 400  # günlük görünümde sütun patlamasını + ağır sorguyu sınırla

router = APIRouter()


def _parse_iso(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"Geçersiz tarih ({name}): YYYY-AA-GG bekleniyor.")


def _build_pivot(rows: list, granularity: str, date_field: str, start: str, end: str) -> dict:
    """Sedna satırlarından kullanıcı × dönem pivot + satır/sütun toplamları."""
    users: dict = {}
    period_totals: dict = {}
    periods: set = set()
    grand = 0
    for r in rows:
        uc = r["user_code"]
        per = r["period"]
        cnt = int(r["cnt"] or 0)
        periods.add(per)
        u = users.setdefault(uc, {"user_code": uc, "user_name": (r["user_name"] or uc),
                                  "by_period": {}, "total": 0})
        u["by_period"][per] = u["by_period"].get(per, 0) + cnt
        u["total"] += cnt
        period_totals[per] = period_totals.get(per, 0) + cnt
        grand += cnt
    return {
        "periods": sorted(periods),
        "users": sorted(users.values(), key=lambda x: -x["total"]),
        "period_totals": period_totals,
        "grand_total": grand,
        "user_count": len(users),
        "granularity": granularity,
        "date_field": date_field,
        "start_date": start,
        "end_date": end,
    }


@router.get("/status")
def fis_icmali_status(_: User = Depends(get_current_user)):
    """Sedna fiş icmali etkin mi (sayfa gösterimi)."""
    return {"configured": sedna_configured()}


@router.get("/summary")
def fis_icmali_summary(
    start_date: str = Query(..., description="YYYY-AA-GG (dahil)"),
    end_date: str = Query(..., description="YYYY-AA-GG (dahil)"),
    granularity: str = Query("month", pattern="^(month|day)$"),
    date_field: str = Query("record", pattern="^(record|fiche)$"),
    current_user: User = Depends(require_permission("accounting.fis_icmali", "view")),
):
    """Kullanıcı × dönem fiş icmali (canlı Sedna). granularity=month|day, date_field=record|fiche."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    sd = _parse_iso(start_date, "start_date")
    ed = _parse_iso(end_date, "end_date")
    if ed < sd:
        raise HTTPException(status_code=422, detail="Bitiş tarihi başlangıçtan önce olamaz.")
    if (ed - sd).days > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Tarih aralığı en fazla {_MAX_RANGE_DAYS} gün olabilir.")
    end_excl = (ed + timedelta(days=1)).isoformat()  # bitiş dahil → SQL'de exclusive
    try:
        rows = fetch_voucher_summary(sd.isoformat(), end_excl, granularity, date_field)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return _build_pivot(rows, granularity, date_field, sd.isoformat(), ed.isoformat())
