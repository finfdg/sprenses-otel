"""Nakit akım — finance_events üzerinden listeleme, özet, EUR bakiye, eşleştirme."""

from fastapi import APIRouter

from .cc_projections import router as cc_projections_router
from .deferral import router as deferral_router
from .eur_balances import router as eur_balances_router
from .listing import router as listing_router
from .matching import router as matching_router
from .report import router as report_router
from .runway import router as runway_router
from .t_account import router as t_account_router

router = APIRouter()
router.include_router(listing_router)
router.include_router(eur_balances_router)
router.include_router(matching_router)
router.include_router(report_router)
router.include_router(runway_router)
router.include_router(t_account_router)
router.include_router(deferral_router)
router.include_router(cc_projections_router)
