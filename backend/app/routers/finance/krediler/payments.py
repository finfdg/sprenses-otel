"""Kredi ödeme planı CRUD + banka eşleştirme."""

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.finance_event_service import finance_event_svc

router = APIRouter()


@router.post("/{product_id}/payments", status_code=status.HTTP_201_CREATED)
def add_payments(
    product_id: int,
    data: CreditPaymentBulkCreate,
    request: Request,
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

    # Ödendi durumu değişecek mi kontrol et (bakiye güncellemesi için)
    was_paid = payment.is_paid
    update_data = data.model_dump(exclude_unset=True)
    will_change_paid = "is_paid" in update_data and update_data["is_paid"] != was_paid

    for key, value in update_data.items():
        setattr(payment, key, value)

    log_action(
        db, current_user.id, "update", "credit_payment",
        entity_id=payment_id,
        details="Ödeme güncellendi",
        ip_address=get_client_ip(request),
    )
    db.flush()
    product = db.query(CreditProduct).filter(CreditProduct.id == payment.credit_product_id).first()
    if product:
        finance_event_svc.upsert_credit_payment(db, payment, product)

        # Ödendi durumu değiştiyse ve anapara (principal) bilgisi varsa kalan borcu güncelle
        # principal yoksa bakiyeye dokunma (faiz/komisyon ayrımı bilinemez)
        if will_change_paid and payment.principal:
            reduction = float(payment.principal)
            if update_data["is_paid"]:
                # Ödendi → bakiyeyi azalt
                product.remaining_amount = max(0, float(product.remaining_amount) - reduction)
            else:
                # Geri alındı → bakiyeyi artır
                product.remaining_amount = float(product.remaining_amount) + reduction
            db.flush()

    db.commit()
    db.refresh(payment)

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

    db.delete(payment)
    finance_event_svc.invalidate(db, "credit", payment_id)

    log_action(
        db, current_user.id, "delete", "credit_payment",
        entity_id=payment_id,
        ip_address=get_client_ip(request),
    )
    db.commit()


# ─── Kredi-Banka Otomatik Eşleştirme ─────────────────────


def _match_credits_to_bank(db: Session) -> dict:
    """Ödenmemiş kredi taksitlerini banka işlemleriyle otomatik eşleştir.

    Ekstre yüklendiğinde çağrılır. Banka işlemi ile kredi taksiti arasında
    tutar + tarih (±3 gün) + banka adı eşleşmesi yapılır.

    Eşleşen taksitler is_paid=True + bank_transaction_id set edilir.
    """
    from app.models.bank_account import BankAccount
    from app.models.bank_transaction import BankTransaction

    # Ödenmemiş ve banka eşleşmesi olmayan taksitler
    unpaid = (
        db.query(CreditPayment)
        .filter(
            CreditPayment.is_paid == False,
            CreditPayment.bank_transaction_id.is_(None),
        )
        .all()
    )
    if not unpaid:
        return {"matched": 0, "total_unpaid": 0}

    # Kredi ürün bilgilerini cache'le
    product_cache = {}
    for p in unpaid:
        if p.credit_product_id not in product_cache:
            prod = db.query(CreditProduct).filter(CreditProduct.id == p.credit_product_id).first()
            product_cache[p.credit_product_id] = prod

    # Zaten eşleşmiş banka işlem ID'leri
    already_matched = set(
        r[0] for r in
        db.query(CreditPayment.bank_transaction_id)
        .filter(CreditPayment.bank_transaction_id.isnot(None))
        .all()
    )

    # Banka gider işlemleri (hesap bilgisiyle)
    bank_expenses = (
        db.query(BankTransaction, BankAccount)
        .join(BankAccount, BankTransaction.account_id == BankAccount.id)
        .filter(BankTransaction.type == "expense")
        .all()
    )

    # Tutar bazlı index (tek işlem)
    btx_by_amount = defaultdict(list)
    for tx, acc in bank_expenses:
        if tx.id not in already_matched:
            btx_by_amount[round(abs(float(tx.amount)), 2)].append((tx, acc))

    # Aynı gün + aynı banka + aynı para birimi toplamları (faiz+vergi ayrı satır durumu)
    # (tarih, banka_adı, para_birimi) → (toplam_tutar, [tx_listesi])
    daily_bank_totals = defaultdict(lambda: {"total": 0.0, "txs": []})
    for tx, acc in bank_expenses:
        if tx.id not in already_matched:
            key = (tx.date, acc.bank_name, acc.currency)
            daily_bank_totals[key]["total"] += abs(float(tx.amount))
            daily_bank_totals[key]["txs"].append((tx, acc))

    matched_count = 0
    used_btx_ids = set()

    for payment in unpaid:
        product = product_cache.get(payment.credit_product_id)
        if not product:
            continue

        amt = round(float(payment.amount), 2)

        # 1. Önce tek işlem eşleşmesi dene
        candidates = btx_by_amount.get(amt, [])
        best_match = None
        best_score = 0

        for tx, acc in candidates:
            if tx.id in used_btx_ids:
                continue

            score = 0
            date_diff = abs((tx.date - payment.due_date).days)

            if date_diff > 3:
                continue
            if date_diff == 0:
                score += 50
            elif date_diff <= 1:
                score += 40
            else:
                score += 20

            if product.bank_name and acc.bank_name:
                if product.bank_name.lower() in acc.bank_name.lower() or acc.bank_name.lower() in product.bank_name.lower():
                    score += 30

            prod_currency = product.currency or "TRY"
            if prod_currency == acc.currency:
                score += 20

            if score > best_score:
                best_score = score
                best_match = tx

        if best_match and best_score >= 40:
            payment.is_paid = True
            payment.paid_date = best_match.date
            payment.bank_transaction_id = best_match.id
            used_btx_ids.add(best_match.id)
            matched_count += 1
            # Anapara varsa kalan borcu düşür
            if payment.principal and product:
                product.remaining_amount = max(0, float(product.remaining_amount) - float(payment.principal))
            db.flush()
            finance_event_svc.match(db, "bank", best_match.id, "credit", payment.id)
            continue

        # 2. Tek işlem eşleşmedi → aynı gün toplamıyla dene (faiz+vergi ayrı satır)
        prod_currency = product.currency or "TRY"
        for date_offset in range(4):  # ±3 gün
            for sign in [0, 1, -1]:
                check_date = payment.due_date + timedelta(days=date_offset * sign) if sign else payment.due_date
                if date_offset == 0 and sign != 0:
                    continue

                key = (check_date, product.bank_name, prod_currency)
                group = daily_bank_totals.get(key)
                if not group:
                    continue

                # Kullanılmış işlemleri çıkar
                available_total = round(sum(
                    abs(float(tx.amount)) for tx, acc in group["txs"] if tx.id not in used_btx_ids
                ), 2)

                if abs(available_total - amt) < 0.02:  # Kuruş toleransı
                    # Eşleşti! İlk işlemi ana eşleşme olarak kullan
                    first_tx = None
                    for tx, acc in group["txs"]:
                        if tx.id not in used_btx_ids:
                            if first_tx is None:
                                first_tx = tx
                            used_btx_ids.add(tx.id)

                    if first_tx:
                        payment.is_paid = True
                        payment.paid_date = check_date
                        payment.bank_transaction_id = first_tx.id
                        matched_count += 1
                        # Anapara varsa kalan borcu düşür
                        if payment.principal and product:
                            product.remaining_amount = max(0, float(product.remaining_amount) - float(payment.principal))
                        db.flush()
                        finance_event_svc.match(db, "bank", first_tx.id, "credit", payment.id)
                    break
            else:
                continue
            break

    if matched_count > 0:
        db.flush()

    return {"matched": matched_count, "total_unpaid": len(unpaid)}
