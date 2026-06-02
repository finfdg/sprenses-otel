"""Nakit akım modülü paylaşılan yanıt oluşturucular ve yardımcı fonksiyonlar."""

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CREDIT_TYPE_LABELS, CreditPayment, CreditProduct
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import DIRECTION_INCOME, FinanceEvent
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.schemas.cash_flow import CashFlowResponse


def _build_bank_response(
    tx: BankTransaction,
    acc: BankAccount,
    cat: Optional[TransactionCategory],
    vendor: Optional[Vendor] = None,
) -> dict:
    """Banka işleminden yanıt oluştur."""
    return CashFlowResponse(
        id=tx.id,
        date=tx.date,
        description=tx.description,
        amount=abs(float(tx.amount)),
        type=tx.type,
        source="bank",
        balance=float(tx.balance) if tx.balance is not None else None,
        receipt_no=tx.receipt_no,
        bank_name=acc.bank_name,
        currency=acc.currency,
        iban=acc.iban,
        account_id=tx.account_id,
        category_id=tx.category_id,
        category_name=cat.name if cat else None,
        category_color=cat.color if cat else None,
        tag_note=tx.tag_note,
        tag_source=tx.tag_source,
        vendor_id=tx.vendor_id,
        vendor_name=vendor.hesap_adi if vendor else None,
        payment_method=tx.payment_method,
        match_number=tx.match_number,
    ).model_dump()


def _build_check_response(c: Check, bank_tx: Optional[BankTransaction] = None) -> dict:
    """Çek kaydından yanıt oluştur."""
    display_date = bank_tx.date if bank_tx else c.due_date

    return CashFlowResponse(
        id=c.id,
        date=display_date,
        description=c.vendor_name,
        amount=float(c.amount_currency),
        type="expense",
        source="check",
        currency="TRY" if c.currency == "TL" else c.currency,
        payment_method="cek",
        check_no=c.check_no,
        check_status=c.status,
        vendor_code=c.vendor_code,
        vendor_name=c.vendor_name,
        tag_note=c.description,
        bank_name=bank_tx.account.bank_name if bank_tx and bank_tx.account else None,
    ).model_dump()


def _build_credit_response(payment: CreditPayment, product: CreditProduct) -> dict:
    """Kredi taksitinden yanıt oluştur."""
    type_label = CREDIT_TYPE_LABELS.get(product.type, product.type)
    desc = f"[{type_label}] {product.name}"
    if payment.installment_no:
        desc += f" — Taksit #{payment.installment_no}"

    return CashFlowResponse(
        id=payment.id,
        date=payment.due_date,
        description=desc,
        amount=float(payment.amount),
        type="expense",
        source="credit",
        currency=product.currency or "TRY",
        bank_name=product.bank_name,
        payment_method=product.type,
        tag_note=f"Anapara: {float(payment.principal):,.2f}" if payment.principal else None,
        check_status="paid" if payment.is_paid else "pending",
    ).model_dump()


def _build_cc_payment_response(stmt: CreditCardStatement, product: CreditProduct) -> dict:
    """Kredi kartı ekstre ödemesinden yanıt oluştur."""
    kalan = float(stmt.toplam_borc) - float(stmt.paid_amount or 0)
    desc = f"[Kredi Kartı] {product.name} — {stmt.kesim_tarihi.strftime('%d.%m.%Y')} Ekstresi"
    if kalan < float(stmt.toplam_borc):
        desc += f" (Kalan: ₺{kalan:,.2f})"

    return CashFlowResponse(
        id=stmt.id,
        date=stmt.son_odeme_tarihi,
        description=desc,
        amount=float(stmt.toplam_borc),
        type="expense",
        source="cc_payment",
        currency="TRY",
        bank_name=product.bank_name,
        payment_method="kredi_karti",
        check_status="paid" if stmt.is_paid else "pending",
        tag_note=f"Asgari: ₺{float(stmt.asgari_odeme):,.2f}",
    ).model_dump()


def _build_advance_response(adv) -> dict:
    """Avans kaydından nakit akım yanıtı oluştur."""
    return CashFlowResponse(
        id=adv.id,
        date=adv.received_date or adv.advance_date,
        description=f"[Avans] {adv.agency_name}",
        amount=float(adv.received_amount or adv.amount),
        type="income",
        source="advance",
        currency=adv.currency,
        check_status=adv.status,
        tag_note=adv.notes,
    ).model_dump()


def _build_vendor_payment_response(
    vtx: VendorTransaction, vendor: Vendor, amount: float
) -> dict:
    """Cari ödeme planından nakit akım yanıtı oluştur."""
    return CashFlowResponse(
        id=vtx.id,
        date=vtx.payment_due_date,
        description=vendor.hesap_adi,
        amount=amount,
        type="expense",
        source="vendor_payment",
        currency="TRY",
        payment_method="cari",
        vendor_id=vtx.vendor_id,
        vendor_name=vendor.hesap_adi,
        vendor_code=vendor.hesap_kodu,
        tag_note=vtx.evrak_no,
    ).model_dump()


def _get_vendor_net_debts(db: Session) -> dict:
    """Her carinin net borcunu hesapla. Sadece borçlu olanları döndür."""
    rows = (
        db.query(
            VendorTransaction.vendor_id,
            func.coalesce(func.sum(VendorTransaction.alacak), 0).label("total_alacak"),
            func.coalesce(func.sum(VendorTransaction.borc), 0).label("total_borc"),
        )
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
    ).model_dump()


def _get_eur_rate(db: Session, target_date) -> float:
    """Belirli tarih için EUR/TRY satış kuru."""
    rate = (
        db.query(ExchangeRate.forex_selling)
        .filter(ExchangeRate.currency_code == "EUR", ExchangeRate.date <= target_date)
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    return float(rate[0]) if rate and rate[0] else 1.0


def _get_usd_rate(db: Session, target_date) -> float:
    """Belirli tarih için USD/TRY satış kuru."""
    rate = (
        db.query(ExchangeRate.forex_selling)
        .filter(ExchangeRate.currency_code == "USD", ExchangeRate.date <= target_date)
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    return float(rate[0]) if rate and rate[0] else 1.0
