"""Kalite modülü — alt router'ları birleştirip tek router olarak export eder."""

from fastapi import APIRouter

from .forms import router as forms_router
from .scheduler import router as scheduler_router
from .templates import router as templates_router

router = APIRouter()
router.include_router(templates_router)
router.include_router(forms_router)
router.include_router(scheduler_router)
