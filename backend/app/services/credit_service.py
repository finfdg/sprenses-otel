"""Kredi domain servis katmanı — ürün/ödeme CRUD mutasyonları + BCH/KMH ödeme planı (HTTP'siz).

D1-2 (2026-06-22): Kredi mutasyon mantığı TEK kaynakta. Hem router endpoint'leri
(`products.py`/`payments.py`) hem onay executor handler'ı (`_handle_finance_krediler`)
AYNI fonksiyonları çağırır → router↔executor sapması (sessiz bug) yapısal olarak engellenir.
Kapatılan sapmalar (2026-06-21 denetim D2-4): executor `product_id` (yanlış kolon — model
`credit_product_id`) → AttributeError 500; onaylanan create/update'te BCH/KMH ödeme planı +
finance_events ÜRETİLMİYORDU (router üretiyordu) → onaylı kredi sessizce plansız/nakit-akımsız oluşuyordu.

Okuma yolları — BİREBİR çıkarım (2026-09-02, yeniden yapılandırma; katman yönü router → service → model):
`_build_product_response` + `_batch_payment_stats` (`krediler/_helpers.py`), `list_products` gövdesi
(`krediler/products.py::list_products`), `summary_by_type` (`krediler/summary.py::credit_summary` gövdesi)
ve `upcoming_payments` (`krediler/summary.py::upcoming_payments` gövdesi) bu modüle satırı satırına,
DEĞİŞTİRİLMEDEN taşındı — finansal parmak izi kapısı (eski-kod/yeni-kod 41 değişmez, sıfır fark):
hiçbir varsayılan (`date.today()` dahil), yuvarlama, guard, sorgu sırası ya da lazy import değiştirilmedi.
Geriye uyumluluk: `krediler/_helpers.py` iki helper'ı, `krediler/summary.py` `summary_by_type`'ı modül
düzeyinde yeniden dışa verir; `credit_summary`/`upcoming_payments`/`list_products` router endpoint'leri
aynı adla kalır ve buradaki fonksiyonu aynı argümanlarla çağıran ince sarmalayıcılardır
(`services/audit_finance_invariants.py` parmak izi o router yolundan çağırmaya devam eder).
"""
import json
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import case as sa_case
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.credit_product import (
    CREDIT_PRODUCT_TYPES,
    CREDIT_TYPE_LABELS,
    CreditPayment,
    CreditProduct,
)
from app.schemas.credit import CreditProductResponse, CreditSummaryItem
from app.services.finance_event_service import finance_event_svc
from app.utils.pagination import page_meta
from app.utils.sql_search import like_pattern

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


def close_product(db: Session, product: CreditProduct, closed_date) -> int:
    """Krediyi kapat: status='closed' + closed_date + ödenmemiş taksit finance_events'lerini
    invalidate (nakit akımdan çıkar). Döner: çıkarılan ödenmemiş taksit sayısı.

    Router (close_product endpoint) ve onay executor (_handle_finance_krediler action='close')
    ORTAK çağırır — böylece onaylı kapatma da status'ü GERÇEKTEN değiştirir + FE'leri invalidate eder
    (eski executor `action` alanını okumuyordu → onaylı kapatma sessizce çalışmıyordu)."""
    product.status = "closed"
    product.closed_date = _coerce_date(closed_date)
    unpaid = (
        db.query(CreditPayment)
        .filter(CreditPayment.credit_product_id == product.id, CreditPayment.is_paid.is_(False))
        .all()
    )
    for pay in unpaid:
        finance_event_svc.invalidate(db, "credit", pay.id)
    return len(unpaid)


def reopen_product(db: Session, product: CreditProduct) -> int:
    """Kapalı krediyi yeniden aç: status='active' + closed_date=None + ödenmemiş taksit
    finance_events'lerini re-upsert (nakit akıma geri getir). Döner: geri eklenen taksit sayısı.
    Router ve onay executor ORTAK çağırır."""
    product.status = "active"
    product.closed_date = None
    unpaid = (
        db.query(CreditPayment)
        .filter(CreditPayment.credit_product_id == product.id, CreditPayment.is_paid.is_(False))
        .all()
    )
    for pay in unpaid:
        finance_event_svc.upsert_credit_payment(db, pay, product)
    return len(unpaid)


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


# ─── Okuma yolları — router endpoint'lerinden / _helpers'tan BİREBİR çıkarım (2026-09-02) ───


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


def list_products(
    db: Session,
    page: int,
    page_size: int,
    type_filter: Optional[str],
    status_filter: Optional[str],
    search: Optional[str],
) -> dict:
    """Kredi ürünlerini listele — `products.py::list_products` endpoint gövdesi BİREBİR (2026-09-02)."""
    query = db.query(CreditProduct)

    if type_filter and type_filter in CREDIT_PRODUCT_TYPES:
        query = query.filter(CreditProduct.type == type_filter)
    if status_filter:
        query = query.filter(CreditProduct.status == status_filter)
    if search:
        s = like_pattern(search, max_len=100)
        query = query.filter(
            (CreditProduct.name.ilike(s, escape="\\")) |
            (CreditProduct.bank_name.ilike(s, escape="\\"))
        )

    total = query.count()
    products = (
        query
        .options(joinedload(CreditProduct.creator))   # N+1 engeli
        .order_by(CreditProduct.type, CreditProduct.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Ödeme istatistiklerini toplu hesapla (N+1 engeli)
    product_ids = [p.id for p in products]
    stats = _batch_payment_stats(db, product_ids)

    return page_meta([_build_product_response(p, stats) for p in products], total, page, page_size)


def summary_by_type(db: Session) -> list:
    """Tip bazlı kredi özeti — EUR karşılığı dahil. `summary.py::credit_summary` gövdesi BİREBİR (2026-09-02)."""
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


def upcoming_payments(db: Session, days: int, include_paid: bool) -> list:
    """Yaklaşan ödemeler (aktif krediler) — `summary.py::upcoming_payments` gövdesi BİREBİR (2026-09-02).

    `date.today()` ifadesi olduğu gibi korunur (parmak izi: sonuç güne bağlıdır — kasıtlı).
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
