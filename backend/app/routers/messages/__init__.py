"""Mesajlaşma modülü — alt router'ları birleştirip tek router olarak export eder.

main.py'deki ``from app.routers import messages`` + ``messages.router``
import'u değişmeden çalışmaya devam eder.
"""

from fastapi import APIRouter

from .conversations import router as conversations_router
from .groups import router as groups_router
from .msg_operations import router as msg_operations_router
from .users import router as users_router

router = APIRouter()
router.include_router(conversations_router)
router.include_router(groups_router)
router.include_router(msg_operations_router)
router.include_router(users_router)
