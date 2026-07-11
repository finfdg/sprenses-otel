"""Yaşlanan eşleşmemişler + tahmin doğruluğu raporları (Faz 3 #21/#25, 2026-07-12).

Salt-okuma GET'ler — onaydan muaf. Tahmin→gerçekleşme geçişinin iki sessiz kopma
sınıfını görünür kılar:
- #21: vadesi geçtiği halde hâlâ eşleşmemiş tahminler (FE) + etiketsiz/eşleşmesiz
  banka hareketleri — bugüne dek yalnız satır satır taranarak fark ediliyordu.
- #25: eşleşme izlerinden (event_matches) tahmin-tarih ↔ gerçekleşme-tarih sapması —
  sistematik geç ödeyen cari/tür için vade önerisi (tahminler zamanla iyileşir).
"""
import logging
import statistics
from datetime import datetime, timedelta

import pytz
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models import Advance, BankTransaction, CreditPayment, Vendor
from app.models.check import Check
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.finance_event import FinanceEvent
from app.models.scheduled import ScheduledEntry
from app.models.user import User
from app.models.vendor_transaction import VendorTransaction

logger = logging.getLogger(__name__)
router = APIRouter()

tz_istanbul = pytz.timezone("Europe/Istanbul")

_SOURCE_LABELS = {
    "check": "Çek", "credit": "Kredi Taksiti", "advance": "Avans",
    "vendor_payment": "Cari Ödemesi", "cc_payment": "KK Ekstresi",
    "tax": "Vergi", "recurring": "Düzenli Ödeme", "salary": "Maaş",
    "withholding": "Stopaj", "sgk": "SGK", "rent_income": "Alınan Kira",
    "rent_expense": "Verilen Kira", "dividend": "Temettü",
    "dividend_stopaj": "Temettü Stopajı",
}


def compute_aging(db: Session, days: int = 7, item_limit: int = 50) -> dict:
    """Yaşlanan eşleşmemişler özeti (endpoint + cron bildirimi ORTAK çekirdek)."""
    today = datetime.now(tz_istanbul).date()
    cutoff = today - timedelta(days=days)

    # (a) Vadesi geçmiş, hâlâ eşleşmemiş/gerçekleşmemiş tahminler (banka hariç)
    stale_q = (
        db.query(FinanceEvent)
        .filter(FinanceEvent.source_type != "bank",
                FinanceEvent.is_matched == False,  # noqa: E712
                FinanceEvent.is_realized == False,  # noqa: E712
                FinanceEvent.event_date < cutoff)
    )
    groups = {}
    for st, cnt, total, oldest in (
        stale_q.with_entities(FinanceEvent.source_type, func.count(FinanceEvent.id),
                              func.coalesce(func.sum(func.coalesce(FinanceEvent.amount_try,
                                                                   FinanceEvent.amount)), 0),
                              func.min(FinanceEvent.event_date))
        .group_by(FinanceEvent.source_type).all()
    ):
        groups[st] = {"label": _SOURCE_LABELS.get(st, st), "count": cnt,
                      "total_try": round(float(total), 2),
                      "oldest_date": oldest.isoformat() if oldest else None}
    stale_items = [
        {"source_type": e.source_type, "source_id": e.source_id,
         "event_date": e.event_date.isoformat(), "amount": float(e.amount or 0),
         "currency": e.currency, "description": e.description,
         "days_overdue": (today - e.event_date).days}
        for e in stale_q.order_by(FinanceEvent.event_date.asc()).limit(item_limit).all()
    ]

    # (b) Yaşlanan etiketsiz/eşleşmesiz banka hareketleri
    unmatched_q = (
        db.query(BankTransaction)
        .filter(BankTransaction.date < cutoff,
                BankTransaction.match_number.is_(None),
                BankTransaction.category_id.is_(None),
                BankTransaction.vendor_id.is_(None))
    )
    ub_count = unmatched_q.count()
    ub_total = float(db.query(func.coalesce(func.sum(func.abs(BankTransaction.amount)), 0))
                     .filter(BankTransaction.date < cutoff,
                             BankTransaction.match_number.is_(None),
                             BankTransaction.category_id.is_(None),
                             BankTransaction.vendor_id.is_(None)).scalar() or 0)
    ub_items = [
        {"id": t.id, "date": t.date.isoformat(), "amount": float(t.amount),
         "description": t.description,
         "days_old": (today - t.date).days}
        for t in unmatched_q.order_by(BankTransaction.date.asc()).limit(item_limit).all()
    ]

    return {
        "days": days,
        "cutoff": cutoff.isoformat(),
        "stale_forecasts": {"by_source": groups,
                            "total_count": sum(g["count"] for g in groups.values()),
                            "items": stale_items},
        "unmatched_bank": {"count": ub_count, "total": round(ub_total, 2),
                           "items": ub_items},
    }


@router.get("/cash-flow/reconciliation/aging")
def reconciliation_aging(
    days: int = Query(default=7, ge=1, le=180),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Yaşlanan eşleşmemişler raporu — X günden eski açık tahminler + eşleşmesiz banka."""
    return compute_aging(db, days=days)


# ─── Tahmin Doğruluğu (Faz 3 #25) ────────────────────────────────────────────

_PLANNED_DATE_SOURCES = {
    "check": (Check, "due_date"),
    "credit": (CreditPayment, "due_date"),
    "advance": (Advance, "advance_date"),
    "vendor_payment": (VendorTransaction, "payment_due_date"),
    "tax": (ScheduledEntry, "entry_date"),
    "sgk": (ScheduledEntry, "entry_date"),
    "withholding": (ScheduledEntry, "entry_date"),
    "salary": (ScheduledEntry, "entry_date"),
    "rent_expense": (ScheduledEntry, "entry_date"),
    "recurring": (ScheduledEntry, "entry_date"),
}


@router.get("/cash-flow/forecast-accuracy")
def forecast_accuracy(
    months: int = Query(default=6, ge=1, le=24),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Tahmin vs gerçekleşme sapması — eşleşme izlerinden (event_matches).

    Pozitif medyan = sistematik GEÇ gerçekleşme (tahminler iyimser). Cari bazında
    'önerilen vade' = mevcut payment_days + medyan gecikme (uygulama kullanıcı
    kararıyla mevcut cari-vade PATCH'i üzerinden — otomatik ayar YOK).
    """
    today = datetime.now(tz_istanbul).date()
    since = today - timedelta(days=months * 30)

    matches = (
        db.query(EventMatch)
        .filter(EventMatch.method != MATCH_METHOD_SUGGESTION,
                EventMatch.bank_source_type == "bank",
                EventMatch.created_at >= datetime.now(tz_istanbul) - timedelta(days=months * 30))
        .all()
    )
    if not matches:
        return {"months": months, "by_type": [], "by_vendor": [], "total_matches": 0}

    btx_ids = {m.bank_source_id for m in matches}
    btx_dates = {tid: d for tid, d in db.query(BankTransaction.id, BankTransaction.date)
                 .filter(BankTransaction.id.in_(list(btx_ids))).all()}

    delays_by_type = {}
    delays_by_vendor = {}
    used = 0
    for m in matches:
        src = _PLANNED_DATE_SOURCES.get(m.target_source_type)
        realized = btx_dates.get(m.bank_source_id)
        if src is None or realized is None or realized < since:
            continue
        model, field = src
        row = db.query(model).filter(model.id == m.target_source_id).first()
        planned = getattr(row, field, None) if row is not None else None
        if planned is None:
            continue
        delay = (realized - planned).days
        delays_by_type.setdefault(m.target_source_type, []).append(delay)
        used += 1
        if m.target_source_type == "vendor_payment" and getattr(row, "vendor_id", None):
            delays_by_vendor.setdefault(row.vendor_id, []).append(delay)

    by_type = [
        {"source_type": st, "label": _SOURCE_LABELS.get(st, st), "count": len(ds),
         "median_delay_days": round(statistics.median(ds), 1),
         "avg_delay_days": round(sum(ds) / len(ds), 1)}
        for st, ds in sorted(delays_by_type.items(), key=lambda kv: -len(kv[1]))
    ]

    by_vendor = []
    if delays_by_vendor:
        vendors = {v.id: v for v in db.query(Vendor)
                   .filter(Vendor.id.in_(list(delays_by_vendor.keys()))).all()}
        for vid, ds in sorted(delays_by_vendor.items(), key=lambda kv: -len(kv[1]))[:50]:
            v = vendors.get(vid)
            median = round(statistics.median(ds), 1)
            current = int(v.payment_days) if v and v.payment_days else 0
            by_vendor.append({
                "vendor_id": vid,
                "vendor_name": v.hesap_adi if v else str(vid),
                "count": len(ds),
                "median_delay_days": median,
                "current_payment_days": current,
                "suggested_payment_days": max(0, int(current + median)) if abs(median) >= 3 else None,
            })

    return {"months": months, "total_matches": used, "by_type": by_type, "by_vendor": by_vendor}
