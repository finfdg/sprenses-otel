"""Onay Akışı router paketi."""

from fastapi import APIRouter

from app.routers.approval.requests import router as requests_router
from app.routers.approval.workflows import router as workflows_router

router = APIRouter()
router.include_router(workflows_router)
router.include_router(requests_router)
