from fastapi import APIRouter

from app.routers.scheduled_base import create_scheduled_router

salary_router = create_scheduled_router(
    source_type="salary",
    permission_code="hr.salary",
    entity_label="Maaş",
    broadcast_module="hr",
)

withholding_router = create_scheduled_router(
    source_type="withholding",
    permission_code="hr.withholding",
    entity_label="Stopaj",
    broadcast_module="hr",
)

sgk_router = create_scheduled_router(
    source_type="sgk",
    permission_code="hr.sgk",
    entity_label="SGK",
    broadcast_module="hr",
)

router = APIRouter()
router.include_router(salary_router, prefix="/salary")
router.include_router(withholding_router, prefix="/withholding")
router.include_router(sgk_router, prefix="/sgk")
