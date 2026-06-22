"""Krediler paketinde paylaşılan yardımcı fonksiyonlar."""

import json

from sqlalchemy import case as sa_case
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.credit_product import (
    CREDIT_TYPE_LABELS,
    CreditPayment,
    CreditProduct,
)
from app.schemas.credit import CreditProductResponse


def _build_product_response(p: CreditProduct, stats: dict) -> dict:
    """Kredi ürünü yanıtı oluştur (stats: önceden hesaplanmış istatistikler)."""
    details = None
    if p.details:
        try:
            details = json.loads(p.details)
        except (json.JSONDecodeError, TypeError):
            details = None

    s = stats.get(p.id, {})
    return CreditProductResponse(
        id=p.id,
        type=p.type,
        type_label=CREDIT_TYPE_LABELS.get(p.type, p.type),
        name=p.name,
        bank_name=p.bank_name,
        company=p.company,
        currency=p.currency,
        total_amount=float(p.total_amount),
        remaining_amount=float(p.remaining_amount),
        interest_rate=float(p.interest_rate) if p.interest_rate is not None else None,
        bsmv_rate=float(p.bsmv_rate) if p.bsmv_rate is not None else None,
        commission_rate=float(p.commission_rate) if p.commission_rate is not None else None,
        linked_account_id=p.linked_account_id,
        start_date=p.start_date,
        end_date=p.end_date,
        status=p.status,
        closed_date=p.closed_date,
        details=details,
        notes=p.notes,
        created_by=p.created_by,
        creator_name=p.creator.full_name if p.creator else None,
        created_at=p.created_at,
        updated_at=p.updated_at,
        payment_count=s.get("payment_count", 0),
        paid_count=s.get("paid_count", 0),
        next_payment_date=s.get("next_date"),
        next_payment_amount=s.get("next_amount"),
    ).model_dump()


def _batch_payment_stats(db: Session, product_ids: list) -> dict:
    """Kredi ürünleri için ödeme istatistiklerini toplu hesapla (N+1 engeli)."""
    if not product_ids:
        return {}

    # Toplam ve ödenen taksit sayıları — tek sorgu
    rows = (
        db.query(
            CreditPayment.credit_product_id,
            func.count(CreditPayment.id).label("total"),
            func.sum(sa_case((CreditPayment.is_paid == True, 1), else_=0)).label("paid"),
        )
        .filter(CreditPayment.credit_product_id.in_(product_ids))
        .group_by(CreditPayment.credit_product_id)
        .all()
    )
    stats = {pid: {"payment_count": total, "paid_count": int(paid or 0)} for pid, total, paid in rows}

    # Sonraki ödeme — ödenmemiş en yakın taksit per ürün
    subq = (
        db.query(
            CreditPayment.credit_product_id,
            func.min(CreditPayment.due_date).label("min_date"),
        )
        .filter(
            CreditPayment.credit_product_id.in_(product_ids),
            CreditPayment.is_paid == False,
        )
        .group_by(CreditPayment.credit_product_id)
        .subquery()
    )
    next_rows = (
        db.query(CreditPayment)
        .join(subq, (CreditPayment.credit_product_id == subq.c.credit_product_id) & (CreditPayment.due_date == subq.c.min_date))
        .all()
    )
    for np in next_rows:
        if np.credit_product_id in stats:
            stats[np.credit_product_id]["next_date"] = np.due_date
            stats[np.credit_product_id]["next_amount"] = float(np.amount)
        else:
            stats[np.credit_product_id] = {
                "payment_count": 0, "paid_count": 0,
                "next_date": np.due_date, "next_amount": float(np.amount),
            }

    return stats
