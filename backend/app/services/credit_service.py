"""Kredi domain servis katmanı — ürün/ödeme CRUD mutasyonları + BCH/KMH ödeme planı (HTTP'siz).

D1-2 (2026-06-22): Kredi mutasyon mantığı TEK kaynakta. Hem router endpoint'leri
(`products.py`/`payments.py`) hem onay executor handler'ı (`_handle_finance_krediler`)
AYNI fonksiyonları çağırır → router↔executor sapması (sessiz bug) yapısal olarak engellenir.
Kapatılan sapmalar (2026-06-21 denetim D2-4): executor `product_id` (yanlış kolon — model
`credit_product_id`) → AttributeError 500; onaylanan create/update'te BCH/KMH ödeme planı +
finance_events ÜRETİLMİYORDU (router üretiyordu) → onaylı kredi sessizce plansız/nakit-akımsız oluşuyordu.
"""
import json
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.credit_product import (
    CREDIT_PRODUCT_TYPES,
    CreditPayment,
    CreditProduct,
)
from app.utils.finance_event_service import finance_event_svc

# BCH/KMH yeniden hesap tetikleyen alanlar (update'te plan yenilenir)
RECALC_FIELDS = {
    "start_date", "end_date", "interest_rate", "total_amount",
    "remaining_amount", "bsmv_rate", "commission_rate",
}


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


# ─── Ortak CRUD mutasyonları (router endpoint'i + onay executor'ı AYNI bunları çağırır) ───


def _coerce_date(v):
    """Onay yolu payload_json'ı tarihleri string yapar (json.dumps default=str);
    router yolu date objesi geçirir. Her ikisini de date'e normalize et (regeneratör
    tarih aritmetiği yapar → string olamaz)."""
    if isinstance(v, str) and v:
        return date.fromisoformat(v[:10])
    return v


def _regenerate_plan(db: Session, product: CreditProduct) -> int:
    """BCH/KMH ürününün ödeme planını üret (tip + gerekli alanlar doluysa). Döner: taksit sayısı."""
    if product.type not in ("bch", "kmh"):
        return 0
    if not (product.start_date and product.end_date and product.interest_rate):
        return 0
    if product.type == "kmh":
        return _regenerate_kmh_payments(db, product)
    return _regenerate_bch_payments(db, product)


def create_product(db: Session, data: dict, actor_id) -> tuple:
    """Kredi ürünü oluştur (+ BCH/KMH ödeme planı + finance_events). Döner: (product, taksit_sayısı).

    Geçersiz tip → ValueError (router 400'e, executor rollback'e çevirir).
    """
    ptype = data.get("type", "")
    if ptype not in CREDIT_PRODUCT_TYPES:
        raise ValueError(f"Geçersiz ürün tipi: {ptype}")
    name = (data.get("name") or "").strip()
    bank_name = data.get("bank_name")
    company = data.get("company")
    details = data.get("details")
    product = CreditProduct(
        type=ptype,
        name=name,
        bank_name=bank_name.strip() if bank_name else None,
        company=company.strip() if company else None,
        currency=data.get("currency") or "TRY",
        total_amount=data.get("total_amount", 0),
        remaining_amount=data.get("remaining_amount", 0),
        interest_rate=data.get("interest_rate"),
        bsmv_rate=data.get("bsmv_rate"),
        commission_rate=data.get("commission_rate"),
        start_date=_coerce_date(data.get("start_date")),
        end_date=_coerce_date(data.get("end_date")),
        details=json.dumps(details, ensure_ascii=False) if details else None,
        notes=data.get("notes"),
        created_by=actor_id,
    )
    db.add(product)
    db.flush()
    count = _regenerate_plan(db, product)
    return product, count


def apply_product_update(db: Session, product: CreditProduct, update_data: dict) -> int:
    """Ürün alanlarını uygula + BCH/KMH plan gerekiyorsa yenile. Döner: yeniden üretilen taksit (0=yok)."""
    needs_recalc = product.type in ("bch", "kmh") and bool(RECALC_FIELDS & set(update_data.keys()))
    data = dict(update_data)
    for _dk in ("start_date", "end_date"):
        if _dk in data:
            data[_dk] = _coerce_date(data[_dk])
    if "details" in data:
        data["details"] = json.dumps(data["details"], ensure_ascii=False) if data["details"] else None
    for key, value in data.items():
        if key == "name" and value:
            value = value.strip()
        setattr(product, key, value)
    if needs_recalc:
        return _regenerate_kmh_payments(db, product) if product.type == "kmh" else _regenerate_bch_payments(db, product)
    return 0


def delete_product(db: Session, product: CreditProduct) -> None:
    """Ürünü sil — önce ödemelerin finance_events'ini invalidate et (CASCADE ödemeleri siler)."""
    payments = db.query(CreditPayment).filter(CreditPayment.credit_product_id == product.id).all()
    for p in payments:
        finance_event_svc.invalidate(db, "credit", p.id)
    db.delete(product)


def apply_payment_update(db: Session, payment: CreditPayment, update_data: dict) -> None:
    """Ödeme alanlarını uygula + finance_event tazele + ödendi değişiminde kalan borcu ayarla."""
    was_paid = payment.is_paid
    will_change_paid = "is_paid" in update_data and update_data["is_paid"] != was_paid
    for key, value in update_data.items():
        setattr(payment, key, value)
    db.flush()
    product = db.query(CreditProduct).filter(CreditProduct.id == payment.credit_product_id).first()
    if product:
        finance_event_svc.upsert_credit_payment(db, payment, product)
        # principal yoksa bakiyeye dokunma (faiz/komisyon ayrımı bilinemez)
        if will_change_paid and payment.principal:
            reduction = float(payment.principal)
            if payment.is_paid:
                product.remaining_amount = max(0, float(product.remaining_amount) - reduction)
            else:
                product.remaining_amount = float(product.remaining_amount) + reduction
            db.flush()


def delete_payment(db: Session, payment: CreditPayment) -> None:
    """Ödemeyi sil + finance_event invalidate."""
    finance_event_svc.invalidate(db, "credit", payment.id)
    db.delete(payment)
