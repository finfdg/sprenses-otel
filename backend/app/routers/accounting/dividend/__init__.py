"""Kâr payı dağıtımı (temettü) router paketi.

Bespoke modül (create_scheduled_router fabrikası DEĞİL) — parent/child veri modeli
(dağıtım → pay sahipleri + taksitler + ödemeler). Router endpoint'leri + onay executor
handler'ı (`_handle_accounting_dividend`) ORTAK `app/services/dividend_service` çağırır.

Mount sırası: payments (/payments/{id}) önce, distributions (/{id} wildcard) sonra —
aksi halde /payments/... yolu /{distribution_id} tarafından yutulur.
"""
from fastapi import APIRouter

from app.routers.accounting.dividend.distributions import router as distributions_router
from app.routers.accounting.dividend.payments import router as payments_router

router = APIRouter()
router.include_router(payments_router)       # /payments/{id} — önce
router.include_router(distributions_router)  # /{distribution_id} wildcard — sonra
