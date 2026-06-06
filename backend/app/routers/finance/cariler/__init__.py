"""Cari hesap yönetimi — Excel yükleme, ödeme planı, eşleştirme, FIFO hesaplama."""

from fastapi import APIRouter

from .matching import router as matching_router
from .payment_schedule import router as payment_schedule_router
from .sedna_import import router as sedna_import_router
from .uploads import router as uploads_router
from .vendors import router as vendors_router

router = APIRouter(prefix="/cariler")
router.include_router(uploads_router)
router.include_router(vendors_router)
router.include_router(payment_schedule_router)
router.include_router(matching_router)
router.include_router(sedna_import_router)
