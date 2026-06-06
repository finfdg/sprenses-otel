from fastapi import APIRouter

from app.constants import BroadcastModule, SourceType
from app.routers.scheduled_base import create_scheduled_router

taxes_router = create_scheduled_router(
    source_type=SourceType.TAX,
    permission_code="accounting.taxes",
    entity_label="Vergi",
    broadcast_module=BroadcastModule.ACCOUNTING,
)

recurring_router = create_scheduled_router(
    source_type=SourceType.RECURRING,
    permission_code="accounting.recurring",
    entity_label="Düzenli Ödeme",
    broadcast_module=BroadcastModule.ACCOUNTING,
    enable_vendor_sync=True,  # cari-bağlı (Elektrik→CK, Su→ASAT) senkron + /sync-vendors
)

rent_income_router = create_scheduled_router(
    source_type=SourceType.RENT_INCOME,
    permission_code="accounting.rent_income",
    entity_label="Alınan Kira",
    broadcast_module=BroadcastModule.ACCOUNTING,
    direction=1,  # GELİR
)

rent_expense_router = create_scheduled_router(
    source_type=SourceType.RENT_EXPENSE,
    permission_code="accounting.rent_expense",
    entity_label="Verilen Kira",
    broadcast_module=BroadcastModule.ACCOUNTING,
    direction=-1,  # GİDER
)

dividend_router = create_scheduled_router(
    source_type=SourceType.DIVIDEND,
    permission_code="accounting.dividend",
    entity_label="Temettü",
    broadcast_module=BroadcastModule.ACCOUNTING,
    direction=-1,  # GİDER
)

router = APIRouter()
router.include_router(taxes_router, prefix="/taxes")
router.include_router(recurring_router, prefix="/recurring")
router.include_router(rent_income_router, prefix="/rent-income")
router.include_router(rent_expense_router, prefix="/rent-expense")
router.include_router(dividend_router, prefix="/dividend")
