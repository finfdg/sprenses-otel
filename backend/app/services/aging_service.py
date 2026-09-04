"""Yaşlanan eşleşmemişler çekirdeği — `cash_flow/aging.py`'den BİREBİR çıkarım (2026-09-02).

Yeniden yapılandırma (katman yönü: router → service → model). `tz_istanbul`, `_SOURCE_LABELS`,
`_PLANNED_DATE_SOURCES` ve `compute_aging` gövdesi `app/routers/finance/cash_flow/aging.py`'den
satırı satırına, DEĞİŞTİRİLMEDEN taşındı (finansal parmak izi kapısı: eski-kod/yeni-kod 41
değişmez sıfır fark vermelidir — hiçbir varsayılan, yuvarlama, guard ya da sorgu sırası
değiştirilmedi). `aging.py` router'ı bu adların TÜMÜNÜ geriye uyumluluk için modül düzeyinde
yeniden dışa verir (`tests/test_faz3_integrity.py` ve `services/audit_finance_invariants.py`
o yoldan import eder; `forecast_accuracy` endpoint'i `tz_istanbul`/`_SOURCE_LABELS`/
`_PLANNED_DATE_SOURCES`'ı router'da kullanmaya devam eder). `cron_sedna_sync._maybe_notify_aging`
artık doğrudan bu modülden çözer.

Özgün açıklama (aging.py, Faz 3 #21): vadesi geçtiği halde hâlâ eşleşmemiş tahminler (FE) +
etiketsiz/eşleşmesiz banka hareketleri — endpoint + cron bildirimi ORTAK çekirdek.
"""
from datetime import datetime, timedelta

import pytz
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Advance, BankTransaction, CreditPayment
from app.models.check import Check
from app.models.finance_event import FinanceEvent
from app.models.scheduled import ScheduledEntry
from app.models.vendor_transaction import VendorTransaction

tz_istanbul = pytz.timezone("Europe/Istanbul")

_SOURCE_LABELS = {
    "check": "Çek", "credit": "Kredi Taksiti", "advance": "Avans",
    "vendor_payment": "Cari Ödemesi", "cc_payment": "KK Ekstresi",
    "tax": "Vergi", "recurring": "Düzenli Ödeme", "salary": "Maaş",
    "withholding": "Stopaj", "sgk": "SGK", "rent_income": "Alınan Kira",
    "rent_expense": "Verilen Kira", "dividend": "Temettü",
    "dividend_stopaj": "Temettü Stopajı",
}

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
