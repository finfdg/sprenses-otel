"""Krediler paketi — kredi ürünleri, ödeme planı, KMH durumu ve özet endpoint'leri."""

from fastapi import APIRouter

from ._helpers import (
    _batch_payment_stats,
    _build_product_response,
    _regenerate_bch_payments,
    _regenerate_kmh_payments,
)
from .kmh import router as kmh_router
from .payments import _match_credits_to_bank
from .payments import router as payments_router
from .products import router as products_router
from .summary import router as summary_router

router = APIRouter(prefix="/krediler")
# Özet ve KMH özel path'leri önce — /{product_id} ile çakışmasını engelle
router.include_router(summary_router)
router.include_router(kmh_router)
router.include_router(products_router)
router.include_router(payments_router)

# Geriye uyumluluk için yeniden ihraç edilen yardımcılar
# (banks.py `from app.routers.finance.krediler import _match_credits_to_bank` yapıyor)
__all__ = [
    "router",
    "_match_credits_to_bank",
    "_batch_payment_stats",
    "_build_product_response",
    "_regenerate_bch_payments",
    "_regenerate_kmh_payments",
]
