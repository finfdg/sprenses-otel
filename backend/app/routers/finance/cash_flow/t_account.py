"""Nakit Akım T Hesap Cetveli — dönem bazlı giriş/çıkış gruplaması (EUR).

Panel yeniden tasarımındaki T-hesap görünümü için: seçilen dönemdeki
(gün/hafta/ay/yıl) eşleşmemiş finance_events kayıtları giriş (direction=+1)
ve çıkış (direction=-1) sütunlarına ayrılır, kaynak/kategori bazında
gruplanır ve tüm tutarlar o günkü TCMB EUR alış kuruyla EUR'a çevrilir (Sedna defter kuru hizası, 2026-07-11).
USD kalemler USD/EUR çaprazıyla doğrudan çevrilir (amount × USD alış / EUR alış —
eur_balances `to_eur` ile aynı; 2026-07-19 öncesi amount_try NULL olduğundan atlanıyorlardı).

Transfer kategorileri (Virman / Döviz Satım / İade) frontend `groupByMonth`
ile aynı kuralla tamamen hariç tutulur — bunlar hesaplar arası iç hareket
olduğundan gerçek giriş/çıkış değildir.

**2026-09-02 yeniden yapılandırma:** hesaplama çekirdeği (sabitler + alt-çizgili yardımcılar +
endpoint gövdesi) BİREBİR `app/services/t_account_service.py`'ye taşındı. Bu dosya yalnız HTTP
kabuğudur: `router`, `taccount_limiter` ve ince `t_account` endpoint'i. Taşınan adlar aşağıda
geriye uyumluluk için yeniden ihraç edilir — `chart.py`, testler ve
`services/audit_finance_invariants.py` bu yoldan import eder.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import RateLimiter
from app.models.user import User
from app.services.t_account_service import (  # noqa: F401 — geriye uyumluluk: testler/parmak izi/chart.py bu yoldan import eder
    AGENCY_LABEL,
    FINANSMAN_SOURCES,
    INFO_CATEGORIES,
    MAX_ITEMS_PER_GROUP,
    SOURCE_LABELS,
    TRANSFER_CATEGORIES,
    UNTAGGED_LABEL,
    _eur_rate_for,
    _event_eur,
    _group_label,
    _item_name,
    _period_range,
    _rate_for,
    _section,
    compute_t_account,
)

# Tarih gezgini ok tıklamaları art arda istek üretir — heavy_limiter (10/dk) gezinmeyi
# boğuyordu (12 ay geriye = 12 istek); okuma-ağırlıklı bu endpoint için daha geniş pencere
taccount_limiter = RateLimiter(max_requests=30, window_seconds=60)

router = APIRouter()


@router.get("/cash-flow/t-account")
def t_account(
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|yearly)$"),
    offset: int = Query(0, le=24, ge=-120, description="0=bu dönem, negatif=geçmiş, pozitif=gelecek dönem"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Dönem bazlı T hesap cetveli — giriş/çıkış grupları, EUR karşılıklarıyla."""
    taccount_limiter.check(f"cashflow-taccount-{current_user.id}")

    return compute_t_account(db, period, offset)
