"""Nakit Koruma / Runway — içinde bulunulan ay için nakit projeksiyonu (EUR).

Ay-içi runway görünümü: BUGÜNKÜ toplam banka nakdi (`start_eur`) başlangıç
noktası; bugünden ay sonuna kadar GERÇEKLEŞMEMİŞ + EŞLEŞMEMİŞ planlı hareketler
(`FinanceEvent`) gelir (`inflows`) ve gider (`outs`) kalemleri olarak listelenir.
Gerçekleşen hareketler (bankada zaten var) ve eşleşmiş/çift-sayım kayıtları
dışarıda kalır. Transfer kategorileri (Virman / Döviz Satım / İade) tamamen
hariçtir — bunlar hesaplar arası iç hareket, gerçek nakit giriş/çıkışı değil.

Tüm tutarlar EUR'a çevrilir:
- `start_eur`: her hesabın son bakiyesi (blocked_amount düşülmüş) o günün EN SON
  TCMB EUR/USD alış kuruyla EUR'a çevrilir (mobile_dashboard_summary "son bakiye"
  deseni + eur_balances `to_eur` çevrim mantığı).
- kalem tutarları: olayın kendi `event_date`'indeki EUR alış kuru (`_get_eur_rate`);
  USD/GBP kalemler çapraz kurla (amount × {code} alış / EUR alış, `_get_fx_buying`).
Kur yoksa kalem 1 TL = 1 EUR gibi çevrilmez → ATLANIR + `skipped_no_rate` sayılır.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import runway_limiter
from app.models.user import User
from app.services.runway_service import (  # noqa: F401 — geriye uyumluluk: testler/parmak izi bu yoldan import eder (2026-09-02 çıkarımı)
    SOURCE_LABELS,
    TR_MONTHS,
    TRANSFER_CATEGORIES,
    _compute_start_eur,
    _event_eur,
    _item_name,
    _natural_date,
    compute_runway,
    compute_start_eur,
)

from ._helpers import (  # noqa: F401 — geriye uyumluluk (eski modül-düzeyi adlar)
    CROSS_EUR_CURRENCIES,
    _get_eur_rate,
    _get_fx_buying,
    bank_snapshot,
)

# Hesaplama gövdesi 2026-09-02'de BİREBİR `app/services/runway_service.py`'ye taşındı (katman yönü:
# router → service → model). Bu dosya yalnız router + ince endpoint + yeniden dışa verim tutar.

router = APIRouter()


@router.get("/cash-flow/runway")
def runway(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Nakit koruma / runway — içinde bulunulan ay için EUR nakit projeksiyonu."""
    runway_limiter.check(f"cashflow-runway-{current_user.id}")
    return compute_runway(db)
