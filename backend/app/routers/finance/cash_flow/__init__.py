"""Nakit akım — finance_events üzerinden listeleme, özet, EUR bakiye, eşleştirme."""

from fastapi import APIRouter

from .eur_balances import router as eur_balances_router
from .listing import router as listing_router
from .matching import router as matching_router

router = APIRouter()
router.include_router(listing_router)
router.include_router(eur_balances_router)
router.include_router(matching_router)
