"""Kredi ödeme planı CRUD."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.user import User
from app.schemas.credit import (
    CreditPaymentBulkCreate,
    CreditPaymentResponse,
    CreditPaymentUpdate,
)
from app.constants import BroadcastModule
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.services import credit_service

router = APIRouter()


@router.post("/{product_id}/payments", status_code=status.HTTP_201_CREATED)
def add_payments(
    product_id: int,
    data: CreditPaymentBulkCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Ödeme planı ekle (toplu)."""
    product = db.query(CreditProduct).filter(CreditProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi ürünü bulunamadı")

    if not data.payments:
        raise HTTPException(status_code=400, detail="En az 1 ödeme gerekli")

    created = []
    for p in data.payments:
        payment = CreditPayment(
            credit_product_id=product_id,
            installment_no=p.installment_no,
            due_date=p.due_date,
            amount=p.amount,
            principal=p.principal,
            interest=p.interest,
            bsmv=p.bsmv,
            commission=p.commission,
            notes=p.notes,
        )
        db.add(payment)
        created.append(payment)

    log_action(
        db, current_user.id, "create", "credit_payment",
        entity_id=product_id,
        details=f"{len(created)} ödeme eklendi: {product.name}",
        ip_address=get_client_ip(request),
    )
    db.flush()
    for cp in created:
        finance_event_svc.upsert_credit_payment(db, cp, product)
    db.commit()

    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "create")
    return [
        CreditPaymentResponse(
            id=p.id,
            credit_product_id=p.credit_product_id,
            installment_no=p.installment_no,
            due_date=p.due_date,
            amount=float(p.amount),
            principal=float(p.principal) if p.principal is not None else None,
            interest=float(p.interest) if p.interest is not None else None,
            bsmv=float(p.bsmv) if p.bsmv is not None else None,
            commission=float(p.commission) if p.commission is not None else None,
            is_paid=p.is_paid,
            paid_date=p.paid_date,
            notes=p.notes,
            created_at=p.created_at,
        ).model_dump()
        for p in created
    ]


@router.patch("/payments/{payment_id}")
def update_payment(
    payment_id: int,
    data: CreditPaymentUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Ödeme güncelle (ödendi işaretleme dahil)."""
    payment = db.query(CreditPayment).filter(CreditPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Ödeme bulunamadı")

    approval_resp = check_approval(db, "finance.krediler", payment_id, current_user.id, "update", {"_target": "payment", **data.model_dump(exclude_unset=True)})
    if approval_resp:
        return approval_resp

    credit_service.apply_payment_update(db, payment, data.model_dump(exclude_unset=True))

    log_action(
        db, current_user.id, "update", "credit_payment",
        entity_id=payment_id,
        details="Ödeme güncellendi",
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(payment)

    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "update")
    return CreditPaymentResponse(
        id=payment.id,
        credit_product_id=payment.credit_product_id,
        installment_no=payment.installment_no,
        due_date=payment.due_date,
        amount=float(payment.amount),
        principal=float(payment.principal) if payment.principal is not None else None,
        interest=float(payment.interest) if payment.interest is not None else None,
        bsmv=float(payment.bsmv) if payment.bsmv is not None else None,
        commission=float(payment.commission) if payment.commission is not None else None,
        is_paid=payment.is_paid,
        paid_date=payment.paid_date,
        bank_transaction_id=payment.bank_transaction_id,
        match_number=payment.match_number,
        notes=payment.notes,
        created_at=payment.created_at,
    ).model_dump()


@router.delete("/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    payment_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Ödeme sil."""
    payment = db.query(CreditPayment).filter(CreditPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Ödeme bulunamadı")

    approval_resp = check_approval(db, "finance.krediler", payment_id, current_user.id, "delete", {"_target": "payment"})
    if approval_resp:
        return approval_resp

    credit_service.delete_payment(db, payment)

    log_action(
        db, current_user.id, "delete", "credit_payment",
        entity_id=payment_id,
        ip_address=get_client_ip(request),
    )
    db.commit()

    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "delete")
