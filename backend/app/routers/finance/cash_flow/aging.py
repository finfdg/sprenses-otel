"""Yaşlanan eşleşmemişler + tahmin doğruluğu raporları (Faz 3 #21/#25, 2026-07-12).

Salt-okuma GET'ler — onaydan muaf. Tahmin→gerçekleşme geçişinin iki sessiz kopma
sınıfını görünür kılar:
- #21: vadesi geçtiği halde hâlâ eşleşmemiş tahminler (FE) + etiketsiz/eşleşmesiz
  banka hareketleri — bugüne dek yalnız satır satır taranarak fark ediliyordu.
- #25: eşleşme izlerinden (event_matches) tahmin-tarih ↔ gerçekleşme-tarih sapması —
  sistematik geç ödeyen cari/tür için vade önerisi (tahminler zamanla iyileşir).

**Yeniden yapılandırma (2026-09-02):** `compute_aging` çekirdeği + `tz_istanbul` /
`_SOURCE_LABELS` / `_PLANNED_DATE_SOURCES` sabitleri BİREBİR `app/services/aging_service.py`'ye
taşındı; bu router yalnız `router` + iki endpoint'i tutar ve taşınan adları geriye uyumluluk
için modül düzeyinde yeniden dışa verir (`tests/test_faz3_integrity.py`,
`services/audit_finance_invariants.py` bu yoldan import eder).
"""
import logging
import statistics
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models import BankTransaction, Vendor
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.user import User
from app.services.aging_service import (  # noqa: F401 — geriye uyumluluk: testler/parmak izi bu yoldan import eder
    _PLANNED_DATE_SOURCES,
    _SOURCE_LABELS,
    compute_aging,
    tz_istanbul,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/cash-flow/reconciliation/aging")
def reconciliation_aging(
    days: int = Query(default=7, ge=1, le=180),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Yaşlanan eşleşmemişler raporu — X günden eski açık tahminler + eşleşmesiz banka."""
    return compute_aging(db, days=days)


# ─── Tahmin Doğruluğu (Faz 3 #25) ────────────────────────────────────────────


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
