"""Yapay zeka paketi — ai.asistan modülü (/api/ai)."""
from fastapi import APIRouter

from app.routers.ai import assistant

router = APIRouter()
router.include_router(assistant.router, tags=["ai-assistant"])
