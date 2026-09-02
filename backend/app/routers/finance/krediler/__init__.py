"""Krediler paketi — kredi ürünleri, ödeme planı, KMH durumu ve özet endpoint'leri.

(2026-09-02) Eski `__all__` re-export bloğu kaldırıldı: banks.py bu paketten hiçbir helper import
etmiyordu (yorum yanlıştı); tüketiciler helper'ları kendi kaynak modülünden alır.
"""

from fastapi import APIRouter

from .kmh import router as kmh_router
from .payments import router as payments_router
from .products import router as products_router
from .summary import router as summary_router

router = APIRouter(prefix="/krediler")
# Özet ve KMH özel path'leri önce — /{product_id} ile çakışmasını engelle
router.include_router(summary_router)
router.include_router(kmh_router)
router.include_router(products_router)
router.include_router(payments_router)

