"""Satış modülü — uçak rezervasyon, otel rezervasyon, oda tipleri ve acente grupları."""

from fastapi import APIRouter

from app.routers.sales import agency_groups, flights, reservations, room_types

router = APIRouter()
router.include_router(flights.router, prefix="/flights", tags=["sales-flights"])
router.include_router(reservations.router, tags=["sales-reservations"])
router.include_router(room_types.router, tags=["sales-room-types"])
router.include_router(agency_groups.router, tags=["sales-agency-groups"])
