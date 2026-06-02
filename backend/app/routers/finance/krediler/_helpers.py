"""Krediler paketinde paylaşılan yardımcı fonksiyonlar."""

import json
from datetime import date

from sqlalchemy import case as sa_case
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.credit_product import (
    CREDIT_TYPE_LABELS,
    CreditPayment,
    CreditProduct,
)
from app.schemas.credit import CreditProductResponse
from app.utils.finance_event_service import finance_event_svc


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


def _regenerate_bch_payments(db: Session, product: "CreditProduct") -> int:
    """BCH hesabının ödeme planını vade/faiz bilgilerine göre yeniden oluştur.

    Dönemler: Mart, Haziran, Eylül, Aralık ay sonları + vade sonu.
    Faiz = Anapara × Yıllık Oran × Gün / 360
    BSMV = (Faiz + Komisyon) × BSMV oranı
    Komisyon = Faiz × Komisyon oranı
    """
    if not product.start_date or not product.end_date or not product.interest_rate:
        return 0

    # Ödenmemiş taksitleri sil (ödenmişlere dokunma) — önce finance_events temizle
    old_unpaid = db.query(CreditPayment.id).filter(
        CreditPayment.credit_product_id == product.id,
        CreditPayment.is_paid == False,
    ).all()
    for (pay_id,) in old_unpaid:
        finance_event_svc.invalidate(db, "credit", pay_id)
    db.query(CreditPayment).filter(
        CreditPayment.credit_product_id == product.id,
        CreditPayment.is_paid == False,
    ).delete(synchronize_session=False)
    db.flush()

    new_payments = []  # finance_event üretmek için oluşturulan taksitler

    amount = float(product.total_amount)
    rate = float(product.interest_rate) / 100
    bsmv_rate = float(product.bsmv_rate) / 100 if product.bsmv_rate else 0.05
    commission_rate = float(product.commission_rate) / 100 if product.commission_rate else 0
    start = product.start_date
    end = product.end_date

    # Çeyrek faiz dönem sonları (Mart, Haziran, Eylül, Aralık)
    quarter_ends = []
    for year in range(start.year, end.year + 1):
        for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            d = date(year, month, day)
            if start < d < end:
                quarter_ends.append(d)

    # Dönemleri oluştur: her dönem önceki dönem sonundan bu dönem sonuna
    prev = start
    installment = 1

    # Mevcut ödenmiş taksitlerin son numarasını bul
    max_paid = db.query(func.max(CreditPayment.installment_no)).filter(
        CreditPayment.credit_product_id == product.id,
        CreditPayment.is_paid == True,
    ).scalar() or 0
    installment = max_paid + 1

    for qe in quarter_ends:
        days = (qe - prev).days
        interest = round(amount * rate * days / 360, 2)
        komisyon = round(interest * commission_rate, 2)
        bsmv = round((interest + komisyon) * bsmv_rate, 2)
        total = round(interest + bsmv + komisyon, 2)

        pay = CreditPayment(
            credit_product_id=product.id,
            installment_no=installment,
            due_date=qe,
            amount=total,
            interest=interest,
            bsmv=bsmv,
            commission=komisyon,
            notes=f"Adat Faizi ({days} gün)",
        )
        db.add(pay)
        new_payments.append(pay)
        prev = qe
        installment += 1

    # Vade sonu: faiz + anapara
    days = (end - prev).days
    interest = round(amount * rate * days / 360, 2)
    komisyon = round(interest * commission_rate, 2)
    bsmv = round((interest + komisyon) * bsmv_rate, 2)
    total = round(interest + bsmv + komisyon + amount, 2)

    final_pay = CreditPayment(
        credit_product_id=product.id,
        installment_no=installment,
        due_date=end,
        amount=total,
        principal=amount,
        interest=interest,
        bsmv=bsmv,
        commission=komisyon,
        notes=f"Vade Sonu (Faiz + Anapara, {days} gün)",
    )
    db.add(final_pay)
    new_payments.append(final_pay)

    # Yeni taksitleri nakit akıma yaz (her para hareketi finance_events'e yazılmalı)
    db.flush()
    for pay in new_payments:
        finance_event_svc.upsert_credit_payment(db, pay, product)

    return installment


def _regenerate_kmh_payments(db: Session, product: "CreditProduct") -> int:
    """KMH hesabının ödeme planını yeniden oluştur.

    BCH ile aynı mantık ama dönemler aylık (her ay sonu).
    Faiz = Anapara × Yıllık Oran × Gün / 360
    """
    if not product.start_date or not product.end_date or not product.interest_rate:
        return 0

    db.query(CreditPayment).filter(
        CreditPayment.credit_product_id == product.id,
        CreditPayment.is_paid == False,
    ).delete(synchronize_session=False)
    db.flush()

    amount = float(product.total_amount)
    rate = float(product.interest_rate) / 100
    bsmv_rate = float(product.bsmv_rate) / 100 if product.bsmv_rate else 0.05
    commission_rate = float(product.commission_rate) / 100 if product.commission_rate else 0
    start = product.start_date
    end = product.end_date

    # Aylık dönem sonları
    month_ends = []
    y, m = start.year, start.month
    while True:
        # Bir sonraki ay sonu
        if m == 12:
            nm_y, nm_m = y + 1, 1
        else:
            nm_y, nm_m = y, m + 1
        from calendar import monthrange
        _, last_day = monthrange(y, m)
        me = date(y, m, last_day)
        if me > start and me < end:
            month_ends.append(me)
        if me >= end:
            break
        y, m = nm_y, nm_m

    max_paid = db.query(func.max(CreditPayment.installment_no)).filter(
        CreditPayment.credit_product_id == product.id,
        CreditPayment.is_paid == True,
    ).scalar() or 0
    installment = max_paid + 1

    prev = start
    for me in month_ends:
        days = (me - prev).days
        interest = round(amount * rate * days / 360, 2)
        komisyon = round(interest * commission_rate, 2)
        bsmv = round((interest + komisyon) * bsmv_rate, 2)
        total = round(interest + bsmv + komisyon, 2)

        db.add(CreditPayment(
            credit_product_id=product.id,
            installment_no=installment,
            due_date=me,
            amount=total,
            interest=interest,
            bsmv=bsmv,
            commission=komisyon,
            notes=f"Aylık Faiz ({days} gün)",
        ))
        prev = me
        installment += 1

    # Vade sonu: faiz + anapara
    days = (end - prev).days
    interest = round(amount * rate * days / 360, 2)
    komisyon = round(interest * commission_rate, 2)
    bsmv = round((interest + komisyon) * bsmv_rate, 2)
    total = round(interest + bsmv + komisyon + amount, 2)

    db.add(CreditPayment(
        credit_product_id=product.id,
        installment_no=installment,
        due_date=end,
        amount=total,
        principal=amount,
        interest=interest,
        bsmv=bsmv,
        commission=komisyon,
        notes=f"Vade Sonu (Faiz + Anapara, {days} gün)",
    ))

    return installment
