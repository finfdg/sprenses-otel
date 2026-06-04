from fastapi import APIRouter

from app.constants import BroadcastModule, SourceType
from app.routers.scheduled_base import create_scheduled_router

salary_router = create_scheduled_router(
    source_type=SourceType.SALARY,
    permission_code="hr.salary",
    entity_label="Maaş",
    broadcast_module=BroadcastModule.HR,
)

withholding_router = create_scheduled_router(
    source_type=SourceType.WITHHOLDING,
    permission_code="hr.withholding",
    entity_label="Stopaj",
    broadcast_module=BroadcastModule.HR,
)

sgk_router = create_scheduled_router(
    source_type=SourceType.SGK,
    permission_code="hr.sgk",
    entity_label="SGK",
    broadcast_module=BroadcastModule.HR,
)

router = APIRouter()
router.include_router(salary_router, prefix="/salary")
router.include_router(withholding_router, prefix="/withholding")
router.include_router(sgk_router, prefix="/sgk")
