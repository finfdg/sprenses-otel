"""Kredi özet endpoint'leri — tip bazlı özet ve yaklaşan ödemeler."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.credit_product import (
    CREDIT_TYPE_LABELS,
    CreditPayment,
    CreditProduct,
)
from app.models.user import User
from app.schemas.credit import CreditSummaryItem

router = APIRouter()


@router.get("/summary/by-type")
def credit_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Tip bazlı kredi özeti — EUR karşılığı dahil."""
    from app.models.exchange_rate import ExchangeRate

    rows = (
        db.query(
            CreditProduct.type,
            func.count(CreditProduct.id),
            func.coalesce(func.sum(CreditProduct.total_amount), 0),
            func.coalesce(func.sum(CreditProduct.remaining_amount), 0),
        )
        .filter(CreditProduct.status == "active")
        .group_by(CreditProduct.type)
        .all()
    )

    # Tip + para birimi bazlı kalan tutarlar
    currency_rows = (
        db.query(
            CreditProduct.type,
            CreditProduct.currency,
            func.coalesce(func.sum(CreditProduct.remaining_amount), 0),
        )
        .filter(CreditProduct.status == "active")
        .group_by(CreditProduct.type, CreditProduct.currency)
        .all()
    )

    # EUR kuru
    eur_rate = None
    latest_date = db.query(func.max(ExchangeRate.date)).scalar()
    if latest_date:
        eur_obj = db.query(ExchangeRate).filter(
            ExchangeRate.date == latest_date,
            ExchangeRate.currency_code == "EUR",
        ).first()
        if eur_obj and eur_obj.forex_buying and float(eur_obj.forex_buying) > 0:
            eur_rate = float(eur_obj.forex_buying)

    # Tip bazlı EUR karşılığı hesapla
    type_eur: dict = {}
    for ctype, currency, remaining in currency_rows:
        rem = float(remaining)
        if eur_rate:
            eur_val = rem if currency == "EUR" else rem / eur_rate
        else:
            eur_val = None
        if ctype not in type_eur:
            type_eur[ctype] = 0.0 if eur_rate else None
        if eur_val is not None and type_eur[ctype] is not None:
            type_eur[ctype] += eur_val

    result = []
    for r in rows:
        item = CreditSummaryItem(
            type=r[0],
            type_label=CREDIT_TYPE_LABELS.get(r[0], r[0]),
            count=r[1],
            total_amount=float(r[2]),
            remaining_amount=float(r[3]),
        ).model_dump()
        eur_val = type_eur.get(r[0])
        item["remaining_amount_eur"] = round(eur_val, 2) if eur_val is not None else None
        result.append(item)

    return result


@router.get("/upcoming-payments")
def upcoming_payments(
    days: int = Query(30, ge=1, le=365),
    include_paid: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Yaklaşan ödemeler (aktif krediler).

    include_paid=True iken ödenmiş taksitler de döner ve aralık **bu ayın başından**
    başlar (bu ayın tamamı görünür — taksit takvimi/akordiyon için). is_paid + paid_date
    alanları her zaman döner. include_paid=False (varsayılan) eski davranış: sadece
    ödenmemiş, bugünden itibaren.
    """
    today = date.today()
    start = today.replace(day=1) if include_paid else today
    end = today + timedelta(days=days)

    q = (
        db.query(CreditPayment, CreditProduct)
        .join(CreditProduct, CreditPayment.credit_product_id == CreditProduct.id)
        .filter(
            CreditProduct.status == "active",  # kapalı kredilerin taksitleri gösterilmez
            CreditPayment.due_date >= start,
            CreditPayment.due_date <= end,
        )
    )
    if not include_paid:
        q = q.filter(CreditPayment.is_paid == False)

    rows = q.order_by(CreditPayment.due_date).all()

    return [
        {
            "payment_id": p.id,
            "product_id": prod.id,
            "product_name": prod.name,
            "product_type": prod.type,
            "type_label": CREDIT_TYPE_LABELS.get(prod.type, prod.type),
            "bank_name": prod.bank_name,
            "currency": prod.currency,
            "installment_no": p.installment_no,
            "due_date": p.due_date,
            "amount": float(p.amount),
            "is_paid": p.is_paid,
            "paid_date": p.paid_date,
            "principal": float(p.principal) if p.principal is not None else None,
            "interest": float(p.interest) if p.interest is not None else None,
            "bsmv": float(p.bsmv) if p.bsmv is not None else None,
            "commission": float(p.commission) if p.commission is not None else None,
        }
        for p, prod in rows
    ]
