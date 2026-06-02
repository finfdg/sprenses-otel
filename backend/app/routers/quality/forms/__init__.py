"""Kalite formları paketi — CRUD, doldurma/gönderme, PDF dışa aktarma."""

from fastapi import APIRouter

from .crud import router as crud_router
from .fill_submit import router as fill_submit_router
from .pdf import router as pdf_router

router = APIRouter()
# Path-spesifik (literal) endpoint'ler önce — /forms/{id} ile çakışmasını engelle
router.include_router(fill_submit_router)
router.include_router(pdf_router)
router.include_router(crud_router)
