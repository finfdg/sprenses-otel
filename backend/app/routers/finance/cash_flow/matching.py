"""Nakit akım eşleştirme — cari, kredi kartı, kredi taksit eşleştirme/kaldırma."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.advance import Advance
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
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
from app.utils.sync_vendor_fifo import sync_vendor_finance_events
from app.utils.matching_service import (
    apply_advance_bank_match,
    apply_check_bank_match,
    apply_credit_bank_match,
    apply_vendor_bank_match,
)
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

    # Uygulama TEK kaynakta: apply_vendor_bank_match (otomatik matcher + öneri-Onayla
    # + bu endpoint ORTAK — D1-2). Sequence numara + sync_tag + EventMatch izi +
    # yarış koruması orada; is_matched'a dokunulmaz (cari kuralı).
    match_number = apply_vendor_bank_match(db, vtx, btx, method="manual",
                                           actor_id=current_user.id)
    if match_number is None:
        raise HTTPException(status_code=409,
                            detail="Kayıt bu sırada başka bir eşleşme aldı — sayfayı yenileyin")
    vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
    vendor_name = vendor.hesap_adi if vendor else ""

    log_action(
        db, current_user.id, "update", "bank_transaction",
        entity_id=btx.id,
        details=f"Manuel cari eşleştirme [#{match_number}] | Cari: {vendor_name} | Banka: {btx.date} ₺{abs(float(btx.amount)):,.2f}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    # Cari bacağı: eşleşme FIFO kalanını değiştirir → vendor_payment FE'leri yeniden yazılır
    sync_vendor_finance_events(db)
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
    background_tasks: BackgroundTasks,
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

    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "match")
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
    background_tasks: BackgroundTasks,
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
    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "unmatch")

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


@router.post("/cash-flow/rematch")
def rematch_all(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Otomatik etiketleme + 4 eşleştiriciyi elle tetikle (R1 2026-07-11).

    Ekstre yüklemesi/banka API senkronuyla AYNI orkestratör (`run_post_ingest_processing`).
    Onaydan MUAF — operasyonel eşleştirme (dosya-yükleme istisnası sınıfı,
    docs/modules/onay-akisi.md kapsam listesi); audit'li + WS yayınlı.
    """
    from app.utils.matching_service import run_post_ingest_processing

    results = run_post_ingest_processing(db)
    log_action(
        db, current_user.id, "update", "bank_transaction", None,
        "Yeniden eşleştirme: " + (", ".join(f"{k}={v}" for k, v in results.items()) or "eşleşme yok"),
        get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "match")
    if results.get("advances_matched"):
        broadcast_finance_update(background_tasks, BroadcastModule.ADVANCES, "match")
    return results


# ─── Eşleşme Önerileri (Faz 1 #9 — event_matches method='suggestion') ────────


@router.get("/cash-flow/match-suggestions")
def list_match_suggestions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Otomatik eşiğin altında kalan eşleşme adayları (insan onayı bekler).

    Otomatik matcher'lar yüksek skoru doğrudan uygular; orta bandı buraya yazar
    (çapraz-para adayları dahil). Onayla → gerçek eşleşme kurulur; Reddet → silinir.
    """
    import math as _math

    from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch

    q = (db.query(EventMatch)
         .filter(EventMatch.method == MATCH_METHOD_SUGGESTION)
         .order_by(EventMatch.score.desc(), EventMatch.id.desc()))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for m in rows:
        btx = db.query(BankTransaction).filter(BankTransaction.id == m.bank_source_id).first()
        target_desc, target_date = None, None
        t, tid = m.target_source_type, m.target_source_id
        if t == "check":
            c = db.query(Check).filter(Check.id == tid).first()
            if c:
                target_desc = f"Çek {c.check_no} · {c.vendor_name}"
                target_date = c.due_date
        elif t == "credit":
            cp = db.query(CreditPayment).filter(CreditPayment.id == tid).first()
            if cp:
                prod = db.query(CreditProduct).filter(CreditProduct.id == cp.credit_product_id).first()
                target_desc = f"{prod.name if prod else 'Kredi'} · Taksit #{cp.installment_no}"
                target_date = cp.due_date
        elif t == "advance":
            a = db.query(Advance).filter(Advance.id == tid).first()
            if a:
                target_desc = f"Avans · {a.agency_name}"
                target_date = a.advance_date
        elif t == "vendor_payment":
            v = db.query(VendorTransaction).filter(VendorTransaction.id == tid).first()
            if v:
                ven = db.query(Vendor).filter(Vendor.id == v.vendor_id).first()
                target_desc = f"Cari · {ven.hesap_adi if ven else v.vendor_id}"
                target_date = v.payment_due_date or v.date
        elif t in ("tax", "sgk", "withholding", "salary", "rent_expense"):
            from app.models.scheduled import ScheduledEntry
            e = db.query(ScheduledEntry).filter(ScheduledEntry.id == tid).first()
            if e:
                target_desc = e.description or f"Planlı gider · {e.source_type}"
                target_date = e.entry_date
        items.append({
            "id": m.id,
            "score": m.score,
            "target_source_type": t,
            "target_source_id": tid,
            "target_description": target_desc,
            "target_date": target_date.isoformat() if target_date else None,
            "amount": float(m.amount or 0),
            "currency": m.currency,
            "bank_transaction_id": m.bank_source_id,
            "bank_date": btx.date.isoformat() if btx else None,
            "bank_amount": float(btx.amount) if btx else None,
            "bank_description": btx.description if btx else None,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, _math.ceil(total / page_size))}


@router.post("/cash-flow/match-suggestions/{suggestion_id}/accept")
def accept_match_suggestion(
    suggestion_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Öneriyi onayla → türe uygun apply_* ile gerçek eşleşme kurulur (onaydan muaf —
    operasyonel eşleştirme, kapsam listesi docs/modules/onay-akisi.md)."""
    from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch

    sug = db.query(EventMatch).filter(EventMatch.id == suggestion_id,
                                      EventMatch.method == MATCH_METHOD_SUGGESTION).first()
    if not sug:
        raise HTTPException(status_code=404, detail="Öneri bulunamadı")
    btx = db.query(BankTransaction).filter(BankTransaction.id == sug.bank_source_id).first()
    if not btx:
        db.delete(sug)
        db.commit()
        raise HTTPException(status_code=409, detail="Banka işlemi artık yok — öneri kaldırıldı")

    t, tid = sug.target_source_type, sug.target_source_id
    ok = False
    if t == "check":
        c = db.query(Check).filter(Check.id == tid).first()
        ok = bool(c) and apply_check_bank_match(db, c, btx, method="manual",
                                                score=sug.score, actor_id=current_user.id)
    elif t == "credit":
        cp = db.query(CreditPayment).filter(CreditPayment.id == tid).first()
        prod = db.query(CreditProduct).filter(CreditProduct.id == cp.credit_product_id).first() if cp else None
        ok = bool(cp) and apply_credit_bank_match(db, cp, prod, btx, method="manual",
                                                  score=sug.score, actor_id=current_user.id)
    elif t == "advance":
        a = db.query(Advance).filter(Advance.id == tid).first()
        ok = bool(a) and apply_advance_bank_match(db, a, btx, method="manual",
                                                  score=sug.score, actor_id=current_user.id)
    elif t == "vendor_payment":
        v = db.query(VendorTransaction).filter(VendorTransaction.id == tid).first()
        ok = bool(v) and apply_vendor_bank_match(db, v, btx, method="manual",
                                                 score=sug.score, actor_id=current_user.id) is not None
    elif t in ("tax", "sgk", "withholding", "salary", "rent_expense"):
        from app.models.scheduled import ScheduledEntry
        from app.services.scheduled_service import link_entry_to_bank
        # link: açık girişi kapatır; elle-ödendi ama eşleşmemiş girişi de bağlar
        # (çift-sayım temizliği, 2026-07-18)
        e = db.query(ScheduledEntry).filter(ScheduledEntry.id == tid).first()
        ok = bool(e) and link_entry_to_bank(db, e, btx)

    db.delete(sug)  # kabul edildi ya da bayatladı — öneri her durumda düşer
    if not ok:
        db.commit()
        raise HTTPException(status_code=409,
                            detail="Hedef bu arada eşleşmiş/kapanmış — öneri kaldırıldı")

    log_action(
        db, current_user.id, "update", "bank_transaction", btx.id,
        f"Eşleşme önerisi onaylandı [#{suggestion_id}] {t}#{tid} skor={sug.score}",
        get_client_ip(request),
    )
    db.commit()
    if t == "vendor_payment":
        sync_vendor_finance_events(db)
        db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "match")
    return {"ok": True, "target_source_type": t, "target_source_id": tid}


@router.post("/cash-flow/match-suggestions/{suggestion_id}/reject")
def reject_match_suggestion(
    suggestion_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Öneriyi reddet (silinir — bir sonraki koşuda aynı çift yeniden önerilebilir)."""
    from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch

    sug = db.query(EventMatch).filter(EventMatch.id == suggestion_id,
                                      EventMatch.method == MATCH_METHOD_SUGGESTION).first()
    if not sug:
        raise HTTPException(status_code=404, detail="Öneri bulunamadı")
    log_action(db, current_user.id, "update", "bank_transaction", sug.bank_source_id,
               f"Eşleşme önerisi reddedildi [#{suggestion_id}] "
               f"{sug.target_source_type}#{sug.target_source_id}", get_client_ip(request))
    db.delete(sug)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "match")
    return {"ok": True}


# ─── Geri Alma (Faz 1 #10 — banka↔çek / banka↔kredi) ─────────────────────────


class UnmatchCheckRequest(BaseModel):
    check_id: int


@router.post("/cash-flow/unmatch-check")
def unmatch_check(
    data: UnmatchCheckRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Banka↔çek eşleşmesini geri al (yanlış otomatik eşleşmenin ucuz düzeltmesi).

    Çek 'pending'e döner; banka hareketi serbest kalır. event_matches izi silinir.
    """
    check = db.query(Check).filter(Check.id == data.check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Çek bulunamadı")
    if check.bank_transaction_id is None:
        raise HTTPException(status_code=400, detail="Çekin banka eşleşmesi yok")

    old_btx = check.bank_transaction_id
    check.bank_transaction_id = None
    if check.status == "paid":
        check.status = "pending"
    db.flush()
    finance_event_svc.unmatch(db, "check", check.id)  # FE açılır + EventMatch izi silinir
    finance_event_svc.upsert_check(db, check)

    log_action(db, current_user.id, "update", "check", check.id,
               f"Banka eşleşmesi geri alındı (btx={old_btx}) — çek yeniden bekliyor",
               get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CHECKS, "unmatch")
    return {"ok": True, "check_id": check.id, "status": check.status}


class UnmatchCreditPaymentRequest(BaseModel):
    payment_id: int


@router.post("/cash-flow/unmatch-credit-payment")
def unmatch_credit_payment(
    data: UnmatchCreditPaymentRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Banka↔kredi taksit eşleşmesini geri al (N-1 grup dahil).

    Taksit açılır, anapara geri eklenir; grup eşleşmesinde ortak match_number'lı
    TÜM banka satırları çözülür (event_matches izinden bulunur).
    """
    from app.models.event_match import EventMatch

    payment = db.query(CreditPayment).filter(CreditPayment.id == data.payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Taksit bulunamadı")
    if payment.bank_transaction_id is None and not payment.is_paid:
        raise HTTPException(status_code=400, detail="Taksitin banka eşleşmesi yok")

    product = db.query(CreditProduct).filter(CreditProduct.id == payment.credit_product_id).first()

    # Grup izi: bu taksite bağlı TÜM banka satırları (event_matches) + ortak match_number
    linked_btx_ids = [m.bank_source_id for m in db.query(EventMatch).filter(
        EventMatch.target_source_type == "credit",
        EventMatch.target_source_id == payment.id,
        EventMatch.bank_source_type == "bank",
    ).all()]
    if payment.bank_transaction_id and payment.bank_transaction_id not in linked_btx_ids:
        linked_btx_ids.append(payment.bank_transaction_id)
    for bid in linked_btx_ids:
        b = db.query(BankTransaction).filter(BankTransaction.id == bid).first()
        if b is not None and b.match_number is not None:
            b.match_number = None  # grup izi temizliği (yalnız grup eşleşmesi yazıyor)
        # NOT: banka FE'sine dokunulmaz — hareket bankada gerçekleşmiştir (realized kalır)

    payment.is_paid = False
    payment.paid_date = None
    payment.bank_transaction_id = None
    if payment.principal and product:
        product.remaining_amount = float(product.remaining_amount) + float(payment.principal)
    db.flush()
    finance_event_svc.unmatch(db, "credit", payment.id)  # FE açılır + EventMatch izleri silinir
    finance_event_svc.upsert_credit_payment(db, payment, product)

    log_action(db, current_user.id, "update", "credit_payment", payment.id,
               f"Banka eşleşmesi geri alındı ({len(linked_btx_ids)} banka satırı çözüldü)",
               get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "unmatch")
    return {"ok": True, "payment_id": payment.id, "released_bank_txs": linked_btx_ids}


# ─── Manuel 1-N Çek Eşleştirme (Faz 1 #12 — tek EFT → N çek) ─────────────────


class MatchChecksBatchRequest(BaseModel):
    bank_transaction_id: int
    check_ids: list


@router.post("/cash-flow/match-checks-batch")
def match_checks_batch(
    data: MatchChecksBatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Tek banka gideriyle birden çok çeki kapat (toplam ±0.02 doğrulamalı)."""
    if not data.check_ids or len(data.check_ids) > 20:
        raise HTTPException(status_code=400, detail="1-20 arası çek seçilmelidir")
    btx = db.query(BankTransaction).filter(BankTransaction.id == data.bank_transaction_id).first()
    if not btx:
        raise HTTPException(status_code=404, detail="Banka işlemi bulunamadı")
    checks = db.query(Check).filter(Check.id.in_(data.check_ids)).all()
    if len(checks) != len(set(data.check_ids)):
        raise HTTPException(status_code=404, detail="Çeklerden bazıları bulunamadı")
    for c in checks:
        if c.status != "pending" or c.bank_transaction_id is not None:
            raise HTTPException(status_code=400, detail=f"Çek {c.check_no} eşleştirmeye uygun değil")
    total = round(sum(float(c.amount_tl) for c in checks), 2)
    if abs(total - abs(float(btx.amount))) > 0.02:
        raise HTTPException(status_code=400,
                            detail=f"Toplam uyuşmuyor: çekler {total:,.2f} ₺, banka {abs(float(btx.amount)):,.2f} ₺")

    applied = 0
    for c in checks:
        if apply_check_bank_match(db, c, btx, method="manual", actor_id=current_user.id):
            applied += 1
    if applied != len(checks):
        db.rollback()
        raise HTTPException(status_code=409, detail="Çeklerden biri bu arada eşleşti — yenileyin")

    log_action(db, current_user.id, "update", "bank_transaction", btx.id,
               f"1-N çek eşleştirme: {applied} çek (toplam {total:,.2f} ₺)",
               get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CHECKS, "match")
    return {"ok": True, "matched_checks": applied}
