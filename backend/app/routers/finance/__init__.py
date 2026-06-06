from fastapi import APIRouter

from .advances import router as advances_router
from .bank_instructions import router as bank_instructions_router
from .banks import router as banks_router
from .butce import router as butce_router
from .cariler import router as cariler_router
from .cash_flow import router as cash_flow_router
from .cc_statements import router as cc_statements_router
from .checks import router as checks_router
from .departmanlar import router as departmanlar_router
from .exchange_rates import router as exchange_rates_router
from .krediler import router as krediler_router
from .onay import router as onay_router
from .payment_instructions import router as payment_instructions_router
from .sedna_sync import router as sedna_sync_router
from .transaction_tags import router as tags_router

router = APIRouter()
router.include_router(cash_flow_router)
router.include_router(banks_router)
router.include_router(exchange_rates_router)
router.include_router(tags_router)
router.include_router(cariler_router)
router.include_router(checks_router)
router.include_router(krediler_router)
router.include_router(cc_statements_router)
router.include_router(advances_router)
router.include_router(butce_router)
router.include_router(departmanlar_router)
router.include_router(onay_router)
router.include_router(bank_instructions_router)
router.include_router(payment_instructions_router)
router.include_router(sedna_sync_router)
