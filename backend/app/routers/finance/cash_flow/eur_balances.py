"""EUR bazlı bakiye hesaplama — günlük ve aylık projeksiyon."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import eur_balances_limiter
from app.models.user import User
from app.services.eur_balances_service import (
    compute_eur_balances,  # noqa: F401 — geriye uyumluluk: testler/report.py bu yoldan import eder (2026-09-02 çıkarımı)
)

# Hesaplama gövdesi (`compute_eur_balances`, 480 satır) 2026-09-02'de BİREBİR
# `app/services/eur_balances_service.py`'ye taşındı (katman yönü: router → service → model).
# Bu dosya yalnız router + ince endpoint + yeniden dışa verim tutar.

router = APIRouter()


@router.get("/cash-flow/eur-balances")
def eur_balances(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Günlük ve aylık EUR bazlı toplam banka bakiyesi."""
    eur_balances_limiter.check(f"eur-bal-{current_user.id}")
    return compute_eur_balances(db)
