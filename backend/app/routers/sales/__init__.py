"""Satış modülü — rezervasyonlar, günlük hareketler, oda tipleri, acente grupları ve
acente mahsup projeksiyonu. Tek RBAC modülü: sales.acente_mahsup (2026-07-09 birleştirme)."""

from fastapi import APIRouter

from app.routers.sales import acente_mahsup, agency_groups, reservations, room_types
from app.routers.sales.reservations import daily_activity

router = APIRouter()
router.include_router(reservations.router, tags=["sales-reservations"])
router.include_router(daily_activity.router, prefix="/daily-activity", tags=["sales-daily-activity"])
router.include_router(room_types.router, tags=["sales-room-types"])
router.include_router(agency_groups.router, tags=["sales-agency-groups"])
router.include_router(acente_mahsup.router, prefix="/acente-mahsup", tags=["sales-acente-mahsup"])
