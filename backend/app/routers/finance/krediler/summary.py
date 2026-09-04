"""Kredi özet endpoint'leri — tip bazlı özet ve yaklaşan ödemeler.

(2026-09-02) Hesap gövdeleri `app/services/credit_service.py`'ye BİREBİR taşındı
(`summary_by_type`, `upcoming_payments`); bu modül yalnız `router` + iki ince sarmalayıcı
endpoint'i tutar. Endpoint adları/imzaları DEĞİŞMEDİ — `services/audit_finance_invariants.py`
parmak izi `credit_summary(db=db, _=None)` / `upcoming_payments(days=365, include_paid=False,
db=db, _=None)` çağrılarını bu yoldan yapmaya devam eder (`upcoming_payments` adı burada endpoint
olduğu için servis fonksiyonu aynı adla yeniden dışa verilmez; `credit_service.upcoming_payments`).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.services import credit_service
from app.services.credit_service import (
    summary_by_type,  # noqa: F401 — geriye uyumluluk: testler/parmak izi bu yoldan import eder (2026-09-02 çıkarımı)
)

router = APIRouter()


@router.get("/summary/by-type")
def credit_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Tip bazlı kredi özeti — EUR karşılığı dahil."""
    return credit_service.summary_by_type(db)


@router.get("/upcoming-payments")
def upcoming_payments(
    days: int = Query(30, ge=1, le=365),
    include_paid: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Yaklaşan ödemeler (aktif krediler).

    include_paid=True iken ödenmiş taksitler de döner ve aralık **bu ayın başından**
    başlar (bu ayın tamamı görünür — taksit takvimi/akordiyon için). is_paid + paid_date
    alanları her zaman döner. include_paid=False (varsayılan) eski davranış: sadece
    ödenmemiş, bugünden itibaren.
    """
    return credit_service.upcoming_payments(db, days, include_paid)
