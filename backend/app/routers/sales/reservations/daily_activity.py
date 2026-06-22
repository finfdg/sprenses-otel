"""Günlük Rezervasyon Hareketleri — Sedna önbürodan canlı gelen/iptal akışı.

Rezervasyon senkronu iptalleri TABLODAN SİLER (`occupancy_metrics` aktif-yalnız değişmezliği)
→ lokal tabloda iptal tarihçesi yoktur. Bu modül "hangi gün kaç rezervasyon geldi / iptal
edildi"yi Sedna'dan CANLI sorgular (Mizan/Fiş İcmali kalıbı): RecordDate ekseni = gelen,
CancelDate ekseni = iptal. Bir rezervasyon aynı gün gelip iptal edilmişse her iki sayıma da
girer (gün neti 0 olur — doğru davranış).

Salt-okunur (yalnız GET) → onay akışı (check_approval) kapsam dışıdır. Tutarlar
`Contrack.Currency` para biriminden EUR'ya çevrilir (rezervasyon senkronuyla aynı katsayılar).
60sn TTL cache: aralık fetch'i tarih gezinmelerinde Sedna'yı tekrar yormaz. Tünel kapalıysa 503.
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.utils.sedna_client import (
    SednaUnavailable,
    fetch_reservation_activity,
    sedna_configured,
)

from app.services.reservation_service import _currency_to_eur_factors

logger = logging.getLogger(__name__)

_MAX_RANGE_DAYS = 92            # günlük detay modülü — çeyrek dönem yeter, Sedna'yı koru
_CACHE_TTL = 60                 # saniye — özet + drill-down aynı fetch'i paylaşır

_cache: dict = {}               # key → (expiry_ts, rows)

router = APIRouter()


def _parse_iso(value: Optional[str], name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"Geçersiz tarih ({name}): YYYY-AA-GG bekleniyor.")


def _validate_range(start_date: str, end_date: str):
    sd = _parse_iso(start_date, "start_date")
    ed = _parse_iso(end_date, "end_date")
    if ed < sd:
        raise HTTPException(status_code=422, detail="Bitiş tarihi başlangıçtan önce olamaz.")
    if (ed - sd).days > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Tarih aralığı en fazla {_MAX_RANGE_DAYS} gün olabilir.")
    return sd, ed


def _fetch_rows(db: Session, sd: date, ed: date) -> list:
    """Aralığın ham Sedna satırlarını çek, EUR'ya normalize et (60sn cache'li)."""
    key = (sd.isoformat(), ed.isoformat())
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]

    raw = fetch_reservation_activity(sd.isoformat(), (ed + timedelta(days=1)).isoformat())
    factors = _currency_to_eur_factors(db)

    rows = []
    for r in raw:
        ci = r["checkin_date"]
        co = r["checkout_date"]
        nights = (co - ci).days if ci and co else 0
        # pax tanımı summary.py ile aynı: yetişkin + ücretli çocuk + ücretsiz çocuk (bebek hariç)
        pax = int(r["adult"] or 0) + int(r["child_paid"] or 0) + int(r["child_free"] or 0)
        cur_code = ((r.get("currency") or "EUR").strip().upper()) or "EUR"
        amount = float(r["room_price"] or 0)
        if factors:
            eur = round(amount * factors.get(cur_code, 1.0), 2)  # bilinmeyen → EUR varsay
        else:
            eur = round(amount, 2) if cur_code == "EUR" else 0.0  # kur yoksa yalnız EUR
        # Misafir adı (guests) bilinçli olarak yer almaz — kişisel veri, modülde gösterilmez.
        rows.append({
            "rec_id": r["rec_id"],
            "voucher": ((r["voucher"] or "").strip() or None),
            "agency": ((r["agency"] or "").strip() or None),
            "nation": ((r["nation"] or "").strip() or None),
            "room_type": ((r["room_type"] or "").strip() or None),
            "board": ((r["board"] or "").strip() or None),
            "checkin_date": ci.isoformat() if ci else None,
            "checkout_date": co.isoformat() if co else None,
            "nights": nights,
            "adult": int(r["adult"] or 0),
            "child": int(r["child_paid"] or 0) + int(r["child_free"] or 0),
            "baby": int(r["baby"] or 0),
            "pax": pax,
            "amount": round(amount, 2),
            "currency": cur_code,
            "eur": eur,
            "record_date": r["record_date"].isoformat() if r["record_date"] else None,
            "cancel_date": r["cancel_date"].isoformat() if r["cancel_date"] else None,
            # iptal = CancelDate dolu VEYA Status=-1 (senkronun "aktif değil" tanımıyla aynı)
            "is_cancelled": bool(r["cancel_date"]) or r["status_code"] == -1,
        })

    _cache[key] = (now + _CACHE_TTL, rows)
    if len(_cache) > 32:  # sınırsız büyümeyi önle — süresi dolmuş girdileri temizle
        for k in [k for k, (exp, _v) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
    return rows


def _zero_bucket() -> dict:
    return {"count": 0, "nights": 0, "pax": 0, "eur": 0.0}


def _add(bucket: dict, row: dict) -> None:
    bucket["count"] += 1
    bucket["nights"] += row["nights"]
    bucket["pax"] += row["pax"]
    bucket["eur"] = round(bucket["eur"] + row["eur"], 2)


@router.get("/status")
def daily_activity_status(_: User = Depends(get_current_user)):
    """Sedna günlük hareket sorgusu etkin mi (sayfa gösterimi)."""
    return {"configured": sedna_configured()}


@router.get("/summary")
def daily_activity_summary(
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.daily_reservations", "view")),
):
    """Gün gün gelen rezervasyon / iptal özeti + dönem toplamları.

    Gelen = RecordDate o güne düşen TÜM kayıtlar (sonradan iptal edilmiş olsa bile o gün
    gelmiştir). İptal = CancelDate o güne düşen kayıtlar. Hareketsiz günler 0'larla döner.
    """
    sd, ed = _validate_range(start_date, end_date)
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        rows = _fetch_rows(db, sd, ed)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    days = {}
    d = sd
    while d <= ed:
        days[d.isoformat()] = {"date": d.isoformat(), "new": _zero_bucket(), "cancelled": _zero_bucket()}
        d += timedelta(days=1)

    totals_new = _zero_bucket()
    totals_cancelled = _zero_bucket()
    for row in rows:
        rd = row["record_date"]
        cd = row["cancel_date"]
        if rd and rd in days:
            _add(days[rd]["new"], row)
            _add(totals_new, row)
        if cd and cd in days:
            _add(days[cd]["cancelled"], row)
            _add(totals_cancelled, row)

    day_list = []
    for key in sorted(days.keys(), reverse=True):  # en yeni gün üstte
        item = days[key]
        item["net_count"] = item["new"]["count"] - item["cancelled"]["count"]
        item["net_eur"] = round(item["new"]["eur"] - item["cancelled"]["eur"], 2)
        day_list.append(item)

    gross = totals_new["count"] + totals_cancelled["count"]
    return {
        "start_date": sd.isoformat(),
        "end_date": ed.isoformat(),
        "days": day_list,
        "totals": {
            "new": totals_new,
            "cancelled": totals_cancelled,
            "net_count": totals_new["count"] - totals_cancelled["count"],
            "net_eur": round(totals_new["eur"] - totals_cancelled["eur"], 2),
            # iptal payı: dönemdeki toplam hareket içinde iptallerin oranı (%)
            "cancel_rate": round(100.0 * totals_cancelled["count"] / gross, 1) if gross else 0.0,
        },
    }


@router.get("/details")
def daily_activity_details(
    activity_date: str = Query(...),
    type: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.daily_reservations", "view")),
):
    """Drill-down: bir günün gelen (`type=new`) veya iptal edilen (`type=cancelled`)
    rezervasyon satırları. Gelenlerde `is_cancelled` sonradan-iptali işaretler;
    iptallerde `record_date` rezervasyonun ne zaman gelmiş olduğunu gösterir.
    """
    if type not in ("new", "cancelled"):
        raise HTTPException(status_code=422, detail="type 'new' veya 'cancelled' olmalıdır.")
    ad = _parse_iso(activity_date, "activity_date")
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        rows = _fetch_rows(db, ad, ad)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    key = "record_date" if type == "new" else "cancel_date"
    items = [r for r in rows if r[key] == ad.isoformat()]
    items.sort(key=lambda r: (r["agency"] or "", r["rec_id"]))
    return {
        "date": ad.isoformat(),
        "type": type,
        "items": items,
        "count": len(items),
        "eur_total": round(sum(r["eur"] for r in items), 2),
    }
