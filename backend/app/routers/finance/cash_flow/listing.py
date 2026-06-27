"""Nakit akım listesi, özet ve mobil dashboard endpoint'leri."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, extract, func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import heavy_limiter
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    FinanceEvent,
)
from app.models.user import User
from app.models.vendor_transaction import VendorTransaction
from app.utils.finance_helpers import MIN_DATE
from app.utils.pagination import page_meta

from ._helpers import _fe_to_response, _get_vendor_net_debts

router = APIRouter()


def _aggregate_vendor_payments(items: list) -> list:
    """Aynı cari + aynı tarih olan vendor_payment kayıtlarını firma bazlı topla.

    Fatura bazlı satırlar yerine firma başına tek satır döner.
    Gruplama anahtarı: (vendor_id, date) — aynı carinin aynı haftadaki
    faturaları tek satırda, toplam tutarla gösterilir.
    """
    result = []
    vendor_groups: dict = {}

    for item in items:
        if item.get("source") == "vendor_payment" and item.get("vendor_id"):
            key = (item["vendor_id"], str(item["date"]))
            if key not in vendor_groups:
                vendor_groups[key] = []
            vendor_groups[key].append(item)
        else:
            result.append(item)

    for _key, group in vendor_groups.items():
        first = group[0]
        total_amount = sum(g["amount"] for g in group)
        merged = {**first}
        merged["amount"] = round(total_amount, 2)
        merged["invoice_count"] = len(group)
        if len(group) > 1:
            merged["tag_note"] = f"{len(group)} fatura"
        result.append(merged)

    result.sort(key=lambda x: (str(x.get("date", "")), x.get("id", 0)), reverse=True)
    return result


@router.get("/cash-flow/")
def list_cash_flows(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=2000),
    type: Optional[str] = Query(None, pattern="^(income|expense)$"),
    source: Optional[str] = Query(None, pattern="^(bank|check|credit|cc_payment|advance|vendor_payment)$"),
    category_id: Optional[int] = Query(None),
    tagged: Optional[bool] = Query(None),
    vendor_id: Optional[int] = Query(None),
    payment_method: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="Başlangıç tarihi (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Bitiş tarihi (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Açıklama/banka/cari araması"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Tüm nakit akım — finance_events tablosundan tek sorgu, SQL sayfalama."""
    heavy_limiter.check(f"cashflow-{current_user.id}")

    query = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.is_matched == False,
            FinanceEvent.event_date >= MIN_DATE,
        )
    )

    # Tarih aralığı filtresi
    if start_date:
        try:
            from datetime import date as date_cls
            sd = date_cls.fromisoformat(start_date)
            query = query.filter(FinanceEvent.event_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            from datetime import date as date_cls
            ed = date_cls.fromisoformat(end_date)
            query = query.filter(FinanceEvent.event_date <= ed)
        except ValueError:
            pass

    # Metin araması
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            FinanceEvent.description.ilike(term)
            | FinanceEvent.bank_name.ilike(term)
            | FinanceEvent.vendor_code.ilike(term)
            | FinanceEvent.tag_note.ilike(term)
        )

    # Filtreler
    if type == "income":
        query = query.filter(FinanceEvent.direction == DIRECTION_INCOME)
    elif type == "expense":
        query = query.filter(FinanceEvent.direction == DIRECTION_EXPENSE)

    if source:
        query = query.filter(FinanceEvent.source_type == source)

    if category_id is not None:
        query = query.filter(FinanceEvent.category_id == category_id)

    if tagged is True:
        query = query.filter(FinanceEvent.category_id.isnot(None))
    elif tagged is False:
        query = query.filter(FinanceEvent.category_id.is_(None))

    if vendor_id is not None:
        query = query.filter(FinanceEvent.vendor_id == vendor_id)

    if payment_method is not None:
        query = query.filter(FinanceEvent.payment_method == payment_method)

    total = query.count()

    events = (
        query
        .options(joinedload(FinanceEvent.vendor))
        .order_by(FinanceEvent.event_date.desc(), FinanceEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    raw_items = [_fe_to_response(fe) for fe in events]
    items = _aggregate_vendor_payments(raw_items)

    return page_meta(items, total, page, page_size)


@router.get("/cash-flow/mobile-dashboard")
def mobile_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Mobil için tek istekte tüm finans özeti."""
    from datetime import date as date_cls
    from datetime import timedelta

    from app.models.credit_product import CreditPayment

    today = date_cls.today()
    week_end = today + timedelta(days=7)

    # ── Toplam banka bakiyesi ─────────────────────────────
    accounts = db.query(BankAccount).all()

    last_tx_sub = db.query(
        BankTransaction.account_id,
        func.max(BankTransaction.id).label("max_id"),
    ).filter(BankTransaction.balance.isnot(None)).group_by(BankTransaction.account_id).subquery()

    last_balance_rows = db.query(
        BankTransaction.account_id,
        BankTransaction.balance,
    ).join(
        last_tx_sub,
        (BankTransaction.account_id == last_tx_sub.c.account_id) &
        (BankTransaction.id == last_tx_sub.c.max_id),
    ).all()

    last_bal = {row.account_id: float(row.balance) for row in last_balance_rows}
    account_currency = {a.id: a.currency for a in accounts}

    total_try_balance = sum(
        v for acc_id, v in last_bal.items()
        if account_currency.get(acc_id, "TRY") == "TRY"
    )

    # ── Bekleyen çekler ──────────────────────────────────
    pending_checks = db.query(
        func.count(Check.id),
        func.coalesce(func.sum(Check.amount_tl), 0),
    ).filter(Check.status == "pending", Check.due_date >= today).first()

    overdue_checks = db.query(
        func.count(Check.id),
        func.coalesce(func.sum(Check.amount_tl), 0),
    ).filter(Check.status == "pending", Check.due_date < today).first()

    # ── Bu haftaki cari ödemeler ─────────────────────────
    weekly_vendor = db.query(
        func.coalesce(func.sum(VendorTransaction.alacak), 0),
        func.count(VendorTransaction.id),
    ).filter(
        VendorTransaction.payment_due_date >= today,
        VendorTransaction.payment_due_date <= week_end,
        VendorTransaction.alacak > 0,
        VendorTransaction.match_number.is_(None),
    ).first()

    # ── Vadesi geçmiş kredi taksitleri ───────────────────
    from app.models.credit_product import CreditProduct
    overdue_credits = db.query(
        func.count(CreditPayment.id),
        func.coalesce(func.sum(CreditPayment.amount), 0),
    ).join(
        CreditProduct, CreditPayment.credit_product_id == CreditProduct.id,
    ).filter(
        CreditProduct.status == "active",  # kapalı kredilerin taksitleri sayılmaz
        CreditPayment.is_paid == False,
        CreditPayment.due_date < today,
        CreditPayment.due_date >= MIN_DATE,
    ).first()

    # ── Son 6 ay aylık özet (grafik) ─────────────────────
    six_months_ago = today.replace(day=1) - timedelta(days=180)
    monthly = db.query(
        extract("year",  BankTransaction.date).label("year"),
        extract("month", BankTransaction.date).label("month"),
        func.coalesce(func.sum(
            case((BankTransaction.type == "income", BankTransaction.amount), else_=0)
        ), 0).label("income"),
        func.coalesce(func.sum(
            case((BankTransaction.type == "expense", func.abs(BankTransaction.amount)), else_=0)
        ), 0).label("expense"),
    ).filter(
        BankTransaction.date >= six_months_ago,
        BankTransaction.date <= today,
    ).group_by("year", "month").order_by("year", "month").all()

    return {
        "bank": {
            "total_try_balance": total_try_balance,
            "account_count": len(accounts),
        },
        "checks": {
            "pending_count": int(pending_checks[0] or 0),
            "pending_amount": float(pending_checks[1] or 0),
            "overdue_count": int(overdue_checks[0] or 0),
            "overdue_amount": float(overdue_checks[1] or 0),
        },
        "weekly_vendor_payments": {
            "amount": float(weekly_vendor[0] or 0),
            "invoice_count": int(weekly_vendor[1] or 0),
            "period_end": week_end.isoformat(),
        },
        "overdue_credits": {
            "count": int(overdue_credits[0] or 0),
            "amount": float(overdue_credits[1] or 0),
        },
        "monthly_chart": [
            {
                "year": int(row.year),
                "month": int(row.month),
                "income": float(row.income),
                "expense": float(row.expense),
                "balance": float(row.income) - float(row.expense),
            }
            for row in monthly
        ],
    }


@router.get("/cash-flow/summary")
def cash_flow_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Toplam gelir, gider ve bakiye (banka + çek)."""
    total_income = (
        db.query(func.coalesce(func.sum(BankTransaction.amount), 0))
        .filter(BankTransaction.type == "income", BankTransaction.date >= MIN_DATE)
        .scalar()
    )
    total_expense = (
        db.query(func.coalesce(func.sum(func.abs(BankTransaction.amount)), 0))
        .filter(BankTransaction.type == "expense", BankTransaction.date >= MIN_DATE)
        .scalar()
    )
    check_pending = (
        db.query(func.coalesce(func.sum(Check.amount_tl), 0))
        .filter(Check.status == "pending", Check.due_date >= MIN_DATE)
        .scalar()
    )
    vendor_debts = _get_vendor_net_debts(db)
    vendor_pending = sum(vendor_debts.values())
    return {
        "total_income": float(total_income),
        "total_expense": float(total_expense),
        "balance": float(total_income) - float(total_expense),
        "check_pending": float(check_pending),
        "vendor_pending": float(vendor_pending),
    }


@router.get("/cash-flow/monthly-summary")
def monthly_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Aylık gelir/gider/bakiye özeti (2026-01-01 sonrası)."""
    rows = (
        db.query(
            extract("year", BankTransaction.date).label("year"),
            extract("month", BankTransaction.date).label("month"),
            func.coalesce(
                func.sum(case((BankTransaction.type == "income", BankTransaction.amount), else_=0)), 0
            ).label("total_income"),
            func.coalesce(
                func.sum(case((BankTransaction.type == "expense", func.abs(BankTransaction.amount)), else_=0)), 0
            ).label("total_expense"),
        )
        .filter(BankTransaction.date >= MIN_DATE)
        .group_by("year", "month")
        .order_by(
            extract("year", BankTransaction.date).desc(),
            extract("month", BankTransaction.date).desc(),
        )
        .all()
    )

    return [
        {
            "year": int(r.year),
            "month": int(r.month),
            "total_income": float(r.total_income),
            "total_expense": float(r.total_expense),
            "balance": float(r.total_income) - float(r.total_expense),
        }
        for r in rows
    ]
