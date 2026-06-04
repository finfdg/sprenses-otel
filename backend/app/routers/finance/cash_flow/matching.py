"""Nakit akım eşleştirme — cari, kredi kartı, kredi taksit eşleştirme/kaldırma."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.bank_transaction import BankTransaction
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.finance_event import SOURCE_BANK, SOURCE_CREDIT
from app.models.transaction_category import TransactionCategory
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.utils.audit import log_action
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Manuel Cari Eşleştirme ──────────────────────────────


class MatchVendorTxRequest(BaseModel):
    bank_transaction_id: int
    vendor_transaction_id: int
    vendor_id: int


@router.post("/cash-flow/match-vendor-tx")
def match_vendor_tx(
    data: MatchVendorTxRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Banka işlemini cari işlemiyle manuel eşleştir.

    Cariler sayfasından 'Eşleştir' tıklanıp nakit akımda banka işlemi seçildiğinde çağrılır.
    """
    btx = db.query(BankTransaction).filter(BankTransaction.id == data.bank_transaction_id).first()
    if not btx:
        raise HTTPException(status_code=404, detail="Banka işlemi bulunamadı")

    vtx = db.query(VendorTransaction).filter(VendorTransaction.id == data.vendor_transaction_id).first()
    if not vtx:
        raise HTTPException(status_code=404, detail="Cari işlemi bulunamadı")

    # Eşleştirme numarası al (mevcut max + 1)
    max_bank = db.query(func.max(BankTransaction.match_number)).scalar() or 0
    max_vendor = db.query(func.max(VendorTransaction.match_number)).scalar() or 0
    match_number = max(max_bank, max_vendor) + 1

    # "Cari" kategorisini bul ve ata
    cari_cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Cari").first()

    # Banka işlemine yaz
    btx.vendor_id = data.vendor_id
    btx.match_number = match_number
    btx.payment_method = btx.payment_method or "havale_eft"
    btx.tag_source = "manual"
    if cari_cat:
        btx.category_id = cari_cat.id

    # Cari işlemine yaz
    vtx.match_number = match_number
    vtx.payment_method = btx.payment_method

    vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
    vendor_name = vendor.hesap_adi if vendor else ""

    if not btx.tag_note:
        btx.tag_note = vendor_name

    log_action(
        db, current_user.id, "update", "bank_transaction",
        entity_id=btx.id,
        details=f"Manuel cari eşleştirme [#{match_number}] | Cari: {vendor_name} | Banka: {btx.date} ₺{abs(float(btx.amount)):,.2f}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "match")

    return {"ok": True, "match_number": match_number}


# ─── Kredi Kartı Borç Ödeme Eşleştirme ───────────────────


class MatchCCPaymentRequest(BaseModel):
    bank_transaction_id: int
    statement_id: int


@router.post("/cash-flow/match-cc-payment")
def match_cc_payment(
    data: MatchCCPaymentRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Banka işlemini kredi kartı ekstresiyle eşleştir.

    Banka işlemi tutarı kadar kredi kartı borcundan düşülür (kısmi ödeme destekli).
    Borç tamamen ödenirse ekstre 'is_paid=True' olur.
    """
    logger.info(f"match-cc-payment called: btx_id={data.bank_transaction_id}, stmt_id={data.statement_id}")

    btx = db.query(BankTransaction).filter(BankTransaction.id == data.bank_transaction_id).first()
    if not btx:
        logger.error(f"BankTransaction not found: id={data.bank_transaction_id}")
        raise HTTPException(status_code=404, detail="Banka işlemi bulunamadı")

    stmt = db.query(CreditCardStatement).filter(CreditCardStatement.id == data.statement_id).first()
    if not stmt:
        logger.error(f"CreditCardStatement not found: id={data.statement_id}")
        raise HTTPException(status_code=404, detail="Kredi kartı ekstresi bulunamadı")

    product = db.query(CreditProduct).filter(CreditProduct.id == stmt.credit_product_id).first()

    payment_amount = abs(float(btx.amount))
    current_paid = float(stmt.paid_amount or 0)
    total_borc = float(stmt.toplam_borc)

    # Ödeme ekle
    new_paid = current_paid + payment_amount
    stmt.paid_amount = min(new_paid, total_borc)

    # Tamamen ödendiyse is_paid = True
    if new_paid >= total_borc - 0.01:  # Kuruş toleransı
        stmt.is_paid = True
        stmt.paid_date = btx.date

    # "Kredi Kartı Borç Ödeme" kategorisini bul
    kk_cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Kredi Kartı Borç Ödeme").first()

    # Banka işlemini etiketle
    btx.category_id = kk_cat.id if kk_cat else None
    btx.tag_source = "manual"
    btx.tag_note = f"{product.name}" if product else None
    btx.payment_method = "kredi_karti"

    card_name = product.name if product else "?"

    # finance_events güncelle — banka işlemi etiket sync
    finance_event_svc.sync_tag(
        db, btx.id,
        category_id=btx.category_id,
        category_name=kk_cat.name if kk_cat else None,
        category_color=kk_cat.color if kk_cat else None,
        tag_note=btx.tag_note,
        tag_source=btx.tag_source,
        payment_method=btx.payment_method,
        match_number=None,
        vendor_id=None,
    )

    # CC finance_event'i güncelle — kalan tutarı yansıt veya tamamen ödendiyse gizle
    finance_event_svc.upsert_cc_statement(db, stmt, product)

    log_action(
        db, current_user.id, "update", "bank_transaction",
        entity_id=btx.id,
        details=f"KK borç ödeme | {card_name} | Ekstre: {stmt.kesim_tarihi} | Ödenen: ₺{payment_amount:,.2f} | Kalan: ₺{max(total_borc - new_paid, 0):,.2f}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "match")

    return {
        "ok": True,
        "paid_amount": payment_amount,
        "total_paid": float(stmt.paid_amount),
        "remaining": max(total_borc - new_paid, 0),
        "is_fully_paid": stmt.is_paid,
        "card_name": card_name,
    }


# ─── Kredi Taksit Ödeme Eşleştirme ────────────────────────


class MatchCreditPaymentRequest(BaseModel):
    bank_transaction_id: int
    payment_id: int


@router.post("/cash-flow/match-credit-payment")
def match_credit_payment(
    data: MatchCreditPaymentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Banka işlemini kredi taksiti ile manuel eşleştir.

    Erken ödeme, farklı tutar veya tarih farkı olan durumlarda
    otomatik eşleştirme çalışmadığında kullanılır.
    """
    btx = db.query(BankTransaction).filter(BankTransaction.id == data.bank_transaction_id).first()
    if not btx:
        raise HTTPException(status_code=404, detail="Banka işlemi bulunamadı")

    payment = db.query(CreditPayment).filter(CreditPayment.id == data.payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Kredi taksiti bulunamadı")

    product = db.query(CreditProduct).filter(CreditProduct.id == payment.credit_product_id).first()

    try:
        # Taksiti ödenmiş olarak işaretle
        payment.is_paid = True
        payment.paid_date = btx.date
        payment.bank_transaction_id = btx.id

        # Banka işlemini etiketle
        kredi_cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Kredi").first()
        btx.category_id = kredi_cat.id if kredi_cat else None
        btx.tag_source = "manual"
        btx.payment_method = product.type if product else "kredi"

        product_name = product.name if product else "?"
        btx.tag_note = product_name

        # finance_events senkronizasyonu — kredi taksitini güncelle ve eşleştir
        finance_event_svc.upsert_credit_payment(db, payment, product)
        finance_event_svc.match(db, SOURCE_BANK, btx.id, SOURCE_CREDIT, payment.id)

        # Banka tarafı etiket sync
        finance_event_svc.sync_tag(
            db, btx.id,
            category_id=btx.category_id,
            category_name=kredi_cat.name if kredi_cat else None,
            category_color=kredi_cat.color if kredi_cat else None,
            tag_note=btx.tag_note,
            tag_source=btx.tag_source,
            payment_method=btx.payment_method,
            match_number=None,
            vendor_id=None,
        )

        log_action(
            db, current_user.id, "update", "bank_transaction",
            entity_id=btx.id,
            details=f"Kredi taksit ödeme | {product_name} | Taksit #{payment.installment_no} | Banka: {btx.date} | €{abs(float(btx.amount)):,.2f}",
            ip_address=get_client_ip(request),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Kredi eşleştirme sırasında hata oluştu")

    return {
        "ok": True,
        "product_name": product_name,
        "installment_no": payment.installment_no,
        "payment_amount": float(payment.amount),
        "bank_amount": abs(float(btx.amount)),
    }


@router.get("/cash-flow/credit-payments-unpaid")
def list_unpaid_credit_payments(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Ödenmemiş kredi taksitlerini listele (manuel eşleştirme için)."""
    payments = (
        db.query(CreditPayment)
        .options(joinedload(CreditPayment.credit_product))
        .filter(
            CreditPayment.is_paid == False,
            CreditPayment.bank_transaction_id.is_(None),
        )
        .order_by(CreditPayment.due_date)
        .all()
    )
    return [
        {
            "id": p.id,
            "product_name": p.credit_product.name if p.credit_product else "?",
            "product_type": p.credit_product.type if p.credit_product else "?",
            "bank_name": p.credit_product.bank_name if p.credit_product else "?",
            "currency": p.credit_product.currency if p.credit_product else "TRY",
            "due_date": p.due_date,
            "amount": float(p.amount),
            "installment_no": p.installment_no,
        }
        for p in payments
    ]


@router.post("/cash-flow/unmatch-cc-payment")
def unmatch_cc_payment(
    data: MatchCCPaymentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Kredi kartı borç ödeme eşleştirmesini iptal et.

    Banka işlemindeki etiketi kaldırır ve ekstre paid_amount'u geri düşer.
    """
    btx = db.query(BankTransaction).filter(BankTransaction.id == data.bank_transaction_id).first()
    if not btx:
        raise HTTPException(status_code=404, detail="Banka işlemi bulunamadı")

    stmt = db.query(CreditCardStatement).filter(CreditCardStatement.id == data.statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Kredi kartı ekstresi bulunamadı")

    payment_amount = abs(float(btx.amount))
    current_paid = float(stmt.paid_amount or 0)

    # Ödemeyi düş
    stmt.paid_amount = max(current_paid - payment_amount, 0)
    stmt.is_paid = False
    stmt.paid_date = None

    # Banka etiketini temizle
    btx.category_id = None
    btx.tag_source = None
    btx.tag_note = None
    btx.payment_method = None

    product = db.query(CreditProduct).filter(CreditProduct.id == stmt.credit_product_id).first()
    card_name = product.name if product else "?"

    # finance_events güncelle — etiket temizlendi
    finance_event_svc.sync_tag(
        db, btx.id,
        category_id=None, category_name=None, category_color=None,
        tag_note=None, tag_source=None, payment_method=None,
        match_number=None, vendor_id=None,
    )

    # CC finance_event'i güncelle — kalan tutarı yansıt ve tekrar görünür yap
    finance_event_svc.upsert_cc_statement(db, stmt, product)

    log_action(
        db, current_user.id, "update", "bank_transaction",
        entity_id=btx.id,
        details=f"KK borç ödeme iptali | {card_name} | ₺{payment_amount:,.2f}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return {"ok": True, "card_name": card_name}


@router.get("/cash-flow/cc-statements-unpaid")
def list_unpaid_cc_statements(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Ödenmemiş kredi kartı ekstrelerini listele (eşleştirme için)."""
    stmts = (
        db.query(CreditCardStatement)
        .options(joinedload(CreditCardStatement.product))
        .filter(CreditCardStatement.is_paid == False)
        .order_by(CreditCardStatement.son_odeme_tarihi)
        .all()
    )
    return [
        {
            "id": s.id,
            "card_name": s.product.name if s.product else "?",
            "bank_name": s.product.bank_name if s.product else "?",
            "kesim_tarihi": s.kesim_tarihi,
            "son_odeme_tarihi": s.son_odeme_tarihi,
            "toplam_borc": float(s.toplam_borc),
            "paid_amount": float(s.paid_amount or 0),
            "remaining": float(s.toplam_borc) - float(s.paid_amount or 0),
        }
        for s in stmts
    ]
