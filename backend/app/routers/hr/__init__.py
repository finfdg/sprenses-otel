from fastapi import APIRouter

from app.constants import BroadcastModule, SourceType
from app.routers.common.scheduled_factory import create_scheduled_router
from app.routers.hr import shift_schedule, shifts

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
# Etiketler yeniden yapılandırma (2026-09-02) öncesi main.py kablolamasıyla birebir: fabrika
# modülleri "hr", vardiyalar "hr-shifts"/"hr-shift-schedule". Devam takip (attendance/) /api/attendance
# yolunu koruduğu için ayrı paket olarak kalır (QR kartlar/PWA bu yolu gömer).
router.include_router(salary_router, prefix="/salary", tags=["hr"])
router.include_router(withholding_router, prefix="/withholding", tags=["hr"])
router.include_router(sgk_router, prefix="/sgk", tags=["hr"])
router.include_router(shifts.router, tags=["hr-shifts"])
router.include_router(shift_schedule.router, tags=["hr-shift-schedule"])
