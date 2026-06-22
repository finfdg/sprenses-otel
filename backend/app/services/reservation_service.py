"""Rezervasyon servis katmanı — SednaPrenses (önbüro) içe aktarma (HTTP'siz, saf domain).

D1-1/D1-5 (2026-06-22): Eskiden `routers/sales/reservations/sedna_import.py` içindeydi;
`routers/finance/sedna_sync.py` (run_reservation_import) ve `daily_activity.py`
(_currency_to_eur_factors) onları router'dan import ediyordu (router→router coupling).
Artık burada; sedna_import endpoint'i + tüketiciler buradan alır.
"""
import json
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.exchange_rate import ExchangeRate
from app.models.reservation import Reservation
from app.models.user import User
from app.utils.audit import log_action
from app.utils.sedna_client import fetch_reservations

logger = logging.getLogger(__name__)



# Sedna Status kodu → okunabilir durum (Excel ile aynı sözlük). -1 = iptal (silinir).
_STATUS_LABELS = {1: "Reservation", 2: "InHouse", 3: "CheckOut"}


def _currency_to_eur_factors(db: Session) -> Optional[dict]:
    """Para birimi → 1 birimi kaç EUR (son TCMB forex_selling). {'EUR':1.0,'TL':1/eur_try,...}.

    RoomPrice sözleşme para biriminde (`Contrack.Currency`: EUR/TL/USD). NET CİRO'yu EUR'da
    tutmak için TL/USD tutarları çevrilir — aksi halde TL sözleşmeler (yerli/WEBRES) ciroyu ~50×
    şişirir. EUR kuru yoksa None döner (çağıran yalnız EUR'yu olduğu gibi alır, gerisini 0'lar).
    """
    rows = (
        db.query(ExchangeRate.currency_code, ExchangeRate.forex_selling, ExchangeRate.unit)
        .filter(ExchangeRate.currency_code.in_(["EUR", "USD", "GBP"]),
                ExchangeRate.forex_selling.isnot(None))
        .order_by(ExchangeRate.currency_code, ExchangeRate.date.desc())
        .all()
    )
    try_per = {}  # para birimi → TRY (1 birim için)
    for code, fs, unit in rows:
        if code not in try_per and fs:  # ilk = en güncel (date desc)
            try_per[code] = float(fs) / (unit or 1)
    eur_try = try_per.get("EUR")
    if not eur_try:
        return None
    factors = {"EUR": 1.0, "TL": 1.0 / eur_try, "TRY": 1.0 / eur_try}
    for c in ("USD", "GBP"):
        if try_per.get(c):
            factors[c] = try_per[c] / eur_try
    return factors


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

    # DB mutasyonları tek transaction — herhangi bir adım patlarsa rollback + 500
    # (diğer Sedna importları ile tutarlı; aynalama yarım kalıp tutarsız tablo bırakmaz).
    try:
        # Pencere içindeki mevcut DB kayıtları (tek sorgu) — hem upsert hem silme süpürmesi için.
        existing = {
            r.rec_id: r
            for r in db.query(Reservation).filter(Reservation.checkin_date >= start).all()
        }

        factors = _currency_to_eur_factors(db)  # para birimi → EUR çevrim katsayıları

        new_count = 0
        updated = 0
        for r in active:
            ci = r["checkin_date"]
            co = r["checkout_date"]
            if not ci or not co:
                continue  # check-in/out olmadan doluluk hesaplanamaz — atla
            nights = (co - ci).days
            adult = int(r["adult"] or 0)
            cur_code = ((r.get("currency") or "EUR").strip().upper()) or "EUR"
            amount = float(r["room_price"] or 0)  # sözleşme para biriminde
            if factors:
                eur_total = round(amount * factors.get(cur_code, 1.0), 2)  # bilinmeyen → EUR varsay
            else:
                eur_total = round(amount, 2) if cur_code == "EUR" else 0.0  # kur yoksa yalnız EUR
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
                "net_amount": (round(amount, 2) or None),  # sözleşme para birimindeki ham tutar
                "currency": cur_code[:5],
                "eur_total": eur_total,                     # EUR'ya normalize (TL/USD çevrildi)
                "per_room": (eur_total or None),
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
    except Exception as e:
        db.rollback()
        logger.error("Rezervasyon senkronu DB hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Rezervasyon senkronu sırasında veritabanı hatası.")
    logger.info("Rezervasyon senkronu: %s", result)
    return result
