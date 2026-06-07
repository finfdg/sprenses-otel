"""Otel rezervasyonlarını SednaPrenses (önbüro/PMS) DB'sinden doğrudan içe aktarma.

XLS yüklemenin (Crystal Reports) **canlı** alternatifi: aynı `rec_id` uzayına (RecId) upsert
eder → mükerrer yapmaz, elle dosya gerektirmez. Doluluk (geceleme/pax) maliyet KPI'larını
besler (`occupancy_metrics`). Merkezi Sedna sync'in (`sedna_sync.py`) bir adımı + tekil endpoint.

**Aktif-yalnız değişmezliği (kritik):** `occupancy_metrics` rez_status'a bakmaz — tablodaki HER
rezervasyonu sayar. XLS akışı tabloyu aktif-yalnız tutar (iptaller removal_candidate olur). Bu
senkron da aynı değişmezliği korur: pencere (`checkin >= yıl başı`) içinde **aktif olanları upsert**
eder, **aktif olmayan her kaydı (iptal Status=-1 veya kaynakta silinmiş) siler** → tablo Sedna'nın
aktif rezervasyonlarının birebir aynası olur.
"""

import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.reservation import Reservation
from app.models.user import User
from app.utils.audit import log_action
from app.utils.sedna_client import SednaUnavailable, fetch_reservations, sedna_configured

logger = logging.getLogger(__name__)

# Sedna Status kodu → okunabilir durum (Excel ile aynı sözlük). -1 = iptal (silinir).
_STATUS_LABELS = {1: "Reservation", 2: "InHouse", 3: "CheckOut"}

router = APIRouter()


def _window_start() -> date:
    """Senkron penceresinin başlangıcı: içinde bulunulan yılın 1 Ocak'ı.

    Geçmiş yıllar (XLS'ten gelen) dokunulmadan kalır; cari yıl + ileri rezervasyonlar senkronlanır.
    """
    return date(date.today().year, 1, 1)


def run_reservation_import(db: Session, current_user: User, ip: Optional[str] = None) -> dict:
    """SednaPrenses'ten rezervasyonları çekip pencereyi (cari yıl+) Sedna ile aynalar.

    Aktifleri upsert eder, aktif-olmayanları (iptal/silinmiş) siler. Commit eder, audit'ler.
    HTTP'siz — orchestrator + tekil endpoint çağırır.
    """
    start = _window_start()
    rows = fetch_reservations(start.isoformat())

    # Aktif = iptal değil (Status<>-1 ve CancelDate boş). active_ids = aynalanacak küme.
    active = [r for r in rows if r["status_code"] != -1 and not r["cancel_date"]]
    active_ids = {r["rec_id"] for r in active}

    # Pencere içindeki mevcut DB kayıtları (tek sorgu) — hem upsert hem silme süpürmesi için.
    existing = {
        r.rec_id: r
        for r in db.query(Reservation).filter(Reservation.checkin_date >= start).all()
    }

    new_count = 0
    updated = 0
    for r in active:
        ci = r["checkin_date"]
        co = r["checkout_date"]
        if not ci or not co:
            continue  # check-in/out olmadan doluluk hesaplanamaz — atla
        nights = (co - ci).days
        adult = int(r["adult"] or 0)
        eur_total = float(r["room_price"] or 0)
        per_adult = round(eur_total / adult, 2) if adult else None
        fields = {
            "agency": ((r["agency"] or "").strip()[:50] or None),
            "room_type": ((r["room_type"] or "").strip()[:40] or None),
            "voucher": ((r["voucher"] or "").strip()[:40] or None),
            "guests": ((r["guests"] or "").strip() or None),
            "checkin_date": ci,
            "checkout_date": co,
            "nights": nights,
            "record_date": r["record_date"] or ci,
            "board": ((r["board"] or "").strip()[:10] or None),
            "vip_type": ((r["vip_type"] or "").strip()[:20] or None),
            "rooms": 1,  # Sedna'da her Reservation satırı = 1 oda
            "adult": adult,
            "child_paid": int(r["child_paid"] or 0),
            "child_free": int(r["child_free"] or 0),
            "baby": int(r["baby"] or 0),
            "nation": ((r["nation"] or "").strip()[:10] or None),
            "net_amount": (eur_total or None),
            "currency": "EUR",
            "eur_total": eur_total,
            "per_room": (round(eur_total, 2) if eur_total else None),
            "per_adult": per_adult,
            "rez_status": "Definite",
            "status": _STATUS_LABELS.get(r["status_code"]),
        }
        cur = existing.get(r["rec_id"])
        if cur:
            for k, v in fields.items():
                setattr(cur, k, v)
            updated += 1
        else:
            db.add(Reservation(rec_id=r["rec_id"], upload_id=None, **fields))
            new_count += 1

    # Süpürme: pencere içindeki aktif-olmayan her DB kaydını sil (iptal + kaynakta silinmiş).
    removed = 0
    for rec_id, dbrow in existing.items():
        if rec_id not in active_ids:
            db.delete(dbrow)
            removed += 1

    result = {
        "reservations_total": len(rows),
        "reservations_active": len(active),
        "reservations_new": new_count,
        "reservations_updated": updated,
        "removed": removed,
        "window_start": start.isoformat(),
    }
    log_action(db, current_user.id, "create", "reservation_sync", None,
               json.dumps(result, ensure_ascii=False), ip)
    db.commit()
    logger.info("Rezervasyon senkronu: %s", result)
    return result


# ─── Durum + içe aktarma endpoint'i (tekil; merkezi sync de çağırır) ─────────

@router.get("/sedna-status")
def reservation_sedna_status(_: User = Depends(get_current_user)):
    """Sedna rezervasyon içe aktarma etkin mi (buton gösterimi)."""
    return {"configured": sedna_configured()}


@router.post("/sedna-import")
def reservation_sedna_import(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.hotel_reservation", "use")),
):
    """SednaPrenses'ten rezervasyonları içe aktar (tekil; merkezi sync de çağırır)."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        return run_reservation_import(db, current_user, get_client_ip(request))
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
