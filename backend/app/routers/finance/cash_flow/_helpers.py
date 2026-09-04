"""Nakit akım modülü paylaşılan yanıt oluşturucular ve yardımcı fonksiyonlar."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.finance_event import DIRECTION_INCOME, FinanceEvent
from app.models.vendor_transaction import VendorTransaction
from app.schemas.cash_flow import CashFlowResponse
from app.services.bank_snapshot_service import (  # noqa: F401 — geriye uyumluluk: runway/chart/t_account/testler bu yoldan import eder (2026-09-02 çıkarımı)
    _get_eur_rate,
    _get_fx_buying,
    _latest_buying,
    bank_snapshot,
)
from app.services.fx_rates import CROSS_EUR_CURRENCIES  # noqa: F401 — re-export (tek kaynak services/fx_rates)

# `_get_eur_rate` / `_get_fx_buying` / `_latest_buying` / `bank_snapshot` gövdeleri 2026-09-02'de
# BİREBİR `app/services/bank_snapshot_service.py`'ye taşındı (katman yönü); burada yalnız
# yeniden dışa verilir.


def _get_vendor_net_debts(db: Session) -> dict:
    """Her carinin net borcunu hesapla. Sadece borçlu olanları döndür."""
    rows = (
        db.query(
            VendorTransaction.vendor_id,
            func.coalesce(func.sum(VendorTransaction.alacak), 0).label("total_alacak"),
            func.coalesce(func.sum(VendorTransaction.borc), 0).label("total_borc"))
        .group_by(VendorTransaction.vendor_id)
        .all()
    )
    debts = {}
    for row in rows:
        net = float(row.total_alacak) - float(row.total_borc)
        if net > 0.01:
            debts[row.vendor_id] = net
    return debts


def _fe_to_response(fe: FinanceEvent) -> dict:
    """FinanceEvent → CashFlowResponse dict."""
    return CashFlowResponse(
        id=fe.source_id,
        date=fe.event_date,
        description=fe.description or "",
        amount=float(fe.amount),
        type="income" if fe.direction == DIRECTION_INCOME else "expense",
        source=fe.source_type,
        balance=float(fe.balance) if fe.balance is not None else None,
        receipt_no=fe.receipt_no,
        bank_name=fe.bank_name,
        currency=fe.currency,
        iban=fe.iban,
        account_id=fe.account_id,
        category_id=fe.category_id,
        category_name=fe.category_name,
        category_color=fe.category_color,
        tag_note=fe.tag_note,
        tag_source=fe.tag_source,
        vendor_id=fe.vendor_id,
        vendor_name=fe.vendor.hesap_adi if fe.vendor_id and fe.vendor else None,
        payment_method=fe.payment_method,
        match_number=fe.match_number,
        check_no=fe.check_no,
        check_status=fe.event_status,
        vendor_code=fe.vendor_code,
        amount_try=float(fe.amount_try) if fe.amount_try else (float(fe.amount) if fe.currency == "TRY" else None),
        is_matched=bool(fe.is_matched),
    ).model_dump()
