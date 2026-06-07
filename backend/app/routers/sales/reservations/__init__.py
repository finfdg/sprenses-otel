"""Otel rezervasyon paketi — XLS yükleme, listeleme, özet, doluluk."""

from fastapi import APIRouter

from .listing import router as listing_router
from .occupancy import router as occupancy_router
from .sedna_import import router as sedna_import_router
from .summary import router as summary_router
from .uploads import router as uploads_router

router = APIRouter(prefix="/reservations")
router.include_router(uploads_router)
router.include_router(listing_router)
router.include_router(summary_router)
router.include_router(occupancy_router)
router.include_router(sedna_import_router)
