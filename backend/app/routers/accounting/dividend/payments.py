"""Kâr payı ödeme satırı — pay sahibi × taksit net/stopaj ödendi işaretleme."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.dividend import DividendInstallment, DividendPayment, DividendShareholder
from app.models.user import User
from app.schemas.dividend import DividendPaymentUpdate
from app.services import dividend_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.routers.accounting.dividend._helpers import payment_response

PERM = "accounting.dividend"

router = APIRouter()


@router.patch("/payments/{payment_id}")
def update_payment(
    payment_id: int,
    data: DividendPaymentUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PERM, "use")),
):
    """Ödeme satırının net/stopaj ödendi durumunu güncelle."""
    payment = db.query(DividendPayment).filter(DividendPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Ödeme satırı bulunamadı")

    approval_resp = check_approval(
        db, PERM, payment_id, current_user.id, "update",
        {"_target": "payment", **data.model_dump(exclude_unset=True)},
    )
    if approval_resp:
        return approval_resp

    dividend_service.apply_payment_update(db, payment, data.model_dump(exclude_unset=True))

    log_action(
        db, current_user.id, "update", "dividend_payment", payment_id,
        "Ödeme satırı güncellendi",
        get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ACCOUNTING, "update")
    db.refresh(payment)

    sh = db.query(DividendShareholder).filter(DividendShareholder.id == payment.shareholder_id).first()
    inst = db.query(DividendInstallment).filter(DividendInstallment.id == payment.installment_id).first()
    return payment_response(
        payment,
        shareholder_name=sh.name if sh else None,
        installment_no=inst.installment_no if inst else None,
    )
