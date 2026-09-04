"""Cari (vendor) domain servis katmanı — vade/durum güncelleme + finance_events senkron (HTTP'siz).

D1-2 (2026-06-22): Cari güncelleme mutasyon mantığı TEK kaynakta. Hem router endpoint'leri
(`cariler/vendors.py` → payment-days + status) hem onay executor handler'ı (`_handle_finance_cariler`)
AYNI fonksiyonu çağırır → router↔executor sapması (sessiz bug) yapısal olarak engellenir. Önceki
executor handler'ı router mantığını elle tekrarlıyordu (doğrulama yoktu; router değişse sessiz sapardı).

**Birebir taşıma (2026-09-02, yeniden yapılandırma — fingerprint-kapılı):** `cariler/vendors.py`
router'ındaki `get_vendors_summary` ve `get_vendor_detail` endpoint GÖVDELERİ hiçbir ifade
değiştirilmeden (`vendors_summary(db)` / `vendor_detail(db, vendor_id, page, page_size, sort_by,
sort_dir)`), `cariler/_helpers.py`'deki `_build_tx_response` ve `_build_dept_cat_user_maps` de
satırı satırına buraya taşındı. Parametre adları, sorgu/ifade sırası, yuvarlama ve guard'lar aynen
korunur; 404 (`HTTPException`, "Cari bulunamadı") taşınan gövdenin içinde olduğu için BİLEREK burada
kaldı (saflık yerine birebirlik — finansal parmak izi eski-kod/yeni-kod SIFIR fark vermelidir).
Router (`vendors.py`) endpoint'leri ince sarmalayıcıdır ve taşınan adları geriye uyumluluk için
modül düzeyinde yeniden dışa verir; `_helpers.py` de iki yardımcıyı yeniden dışa verir
(`services/audit_finance_invariants.py` endpoint fonksiyonlarını router yolundan çağırır).
"""
import math
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.budget import BudgetCategory
from app.models.department import Department
from app.models.exchange_rate import ExchangeRate
from app.models.user import User
from app.models.vendor import STATUS_PAYMENT_BANNED, VENDOR_STATUS_CHOICES, Vendor
from app.models.vendor_transaction import VendorTransaction
from app.parsers.vendor_parser import calculate_payment_friday
from app.schemas.vendor import VendorDetailResponse, VendorTransactionResponse
from app.services.finance_event_service import finance_event_svc
from app.services.sync_vendor_fifo import sync_vendor_finance_events
from app.services.vendor_fifo import calculate_fifo_amounts, calculate_overdue_by_vendor


def _build_tx_response(tx, dept_map, cat_map, user_map):
    """VendorTransaction → dict (departman bilgileriyle)."""
    return VendorTransactionResponse(
        id=tx.id,
        vendor_id=tx.vendor_id,
        date=tx.date,
        evrak_no=tx.evrak_no,
        transaction_type=tx.transaction_type,
        fis_no=tx.fis_no,
        description=tx.description,
        borc=float(tx.borc),
        alacak=float(tx.alacak),
        bakiye=float(tx.bakiye) if tx.bakiye is not None else None,
        payment_due_date=tx.payment_due_date,
        match_number=tx.match_number,
        payment_method=tx.payment_method,
        department_id=tx.department_id,
        department_name=dept_map.get(tx.department_id) if tx.department_id else None,
        budget_category_id=tx.budget_category_id,
        budget_category_name=cat_map.get(tx.budget_category_id) if tx.budget_category_id else None,
        dept_status=tx.dept_status,
        dept_assigned_by_name=user_map.get(tx.dept_assigned_by) if tx.dept_assigned_by else None,
        dept_assigned_at=str(tx.dept_assigned_at) if tx.dept_assigned_at else None,
        dept_rejection_note=tx.dept_rejection_note,
    ).model_dump()


def _build_dept_cat_user_maps(db: Session, transactions):
    """İşlem listesi için departman, kategori ve kullanıcı adı map'lerini oluştur."""
    dept_ids = list(set(tx.department_id for tx in transactions if tx.department_id))
    dept_map = {}
    if dept_ids:
        depts = db.query(Department).filter(Department.id.in_(dept_ids)).all()
        dept_map = {d.id: d.name for d in depts}

    cat_ids = list(set(tx.budget_category_id for tx in transactions if tx.budget_category_id))
    cat_map = {}
    if cat_ids:
        cats = db.query(BudgetCategory).filter(BudgetCategory.id.in_(cat_ids)).all()
        cat_map = {c.id: c.name for c in cats}

    assigned_ids = list(set(tx.dept_assigned_by for tx in transactions if tx.dept_assigned_by))
    user_map = {}
    if assigned_ids:
        users = db.query(User).filter(User.id.in_(assigned_ids)).all()
        user_map = {u.id: u.full_name for u in users}

    return dept_map, cat_map, user_map


def apply_vendor_update(db: Session, vendor: Vendor, update_data: dict) -> int:
    """Cari alanlarını (vade/durum) uygula → vade değiştiyse işlem ödeme tarihlerini yeniden
    hesapla (+ finance_event upsert) → finance_events senkronla. Döner: yeniden hesaplanan işlem sayısı.

    HTTP'siz, commit'siz (çağıran commit eder). Router (payment-days/status endpoint'leri) ve
    onay executor'ı AYNI bunu çağırır. Geçersiz durum/negatif vade → ValueError.
    """
    if "status" in update_data and update_data["status"] not in VENDOR_STATUS_CHOICES:
        raise ValueError(f"Geçersiz durum: {update_data['status']}")
    if "payment_days" in update_data and (update_data["payment_days"] or 0) < 0:
        raise ValueError("Ödeme vadesi negatif olamaz")

    for key, value in update_data.items():
        setattr(vendor, key, value)

    updated_count = 0
    if "payment_days" in update_data:
        invoice_txs = (
            db.query(VendorTransaction)
            .filter(
                VendorTransaction.vendor_id == vendor.id,
                VendorTransaction.alacak > 0,
                VendorTransaction.date.isnot(None),
            )
            .all()
        )
        for tx in invoice_txs:
            tx.payment_due_date = calculate_payment_friday(tx.date, vendor.payment_days)
            updated_count += 1
            finance_event_svc.upsert_vendor_tx(db, tx, vendor, float(tx.alacak))

    db.flush()
    # Vade/durum değişimi nakit akıma yansısın (yasaklı→sil, normal→yeniden oluştur, vade→tarih güncelle)
    sync_vendor_finance_events(db)
    return updated_count


# ─── Cari Özet (get_vendors_summary gövdesi — birebir) ───────────────

def vendors_summary(db: Session):
    """Tüm carilerin toplam borç/alacak/bakiye özetini getir."""
    totals = (
        db.query(
            func.coalesce(func.sum(VendorTransaction.borc), 0),
            func.coalesce(func.sum(VendorTransaction.alacak), 0),
        )
        .first()
    )
    total_borc = float(totals[0])
    total_alacak = float(totals[1])

    vendor_count = db.query(func.count(Vendor.id)).scalar() or 0
    banned_count = db.query(func.count(Vendor.id)).filter(Vendor.status == STATUS_PAYMENT_BANNED).scalar() or 0

    balance_rows = (
        db.query(
            Vendor.id,
            (func.coalesce(func.sum(VendorTransaction.borc), 0) - func.coalesce(func.sum(VendorTransaction.alacak), 0)).label("bakiye"),
        )
        .outerjoin(VendorTransaction, Vendor.id == VendorTransaction.vendor_id)
        .group_by(Vendor.id)
        .all()
    )
    negative_count = 0
    negative_total = 0.0
    nonzero_count = 0
    for row in balance_rows:
        b = float(row.bakiye)
        if b < 0:
            negative_count += 1
            negative_total += b
        if abs(b) > 0.004:
            nonzero_count += 1

    # Vadesi geçmiş — detay kartı / Ödeme Planı ile AYNI net FIFO kaynağı
    overdue_map = calculate_overdue_by_vendor(db)
    overdue_total = round(sum(amt for amt, _cnt in overdue_map.values()), 2)
    overdue_invoice_count = sum(cnt for _amt, cnt in overdue_map.values())
    overdue_vendor_count = len(overdue_map)

    bakiye = total_borc - total_alacak
    negative_total_eur = None
    latest_date = db.query(func.max(ExchangeRate.date)).scalar()
    if latest_date:
        eur_obj = db.query(ExchangeRate).filter(
            ExchangeRate.date == latest_date,
            ExchangeRate.currency_code == "EUR",
        ).first()
        if eur_obj and eur_obj.forex_buying and float(eur_obj.forex_buying) > 0:
            negative_total_eur = round(abs(float(negative_total)) / float(eur_obj.forex_buying), 2)

    return {
        "total_borc": total_borc,
        "total_alacak": total_alacak,
        "bakiye": bakiye,
        "vendor_count": vendor_count,
        "negative_count": negative_count,
        "negative_total": negative_total,
        "negative_total_eur": negative_total_eur,
        "banned_count": banned_count,
        "nonzero_count": nonzero_count,
        "overdue_total": overdue_total,
        "overdue_invoice_count": overdue_invoice_count,
        "overdue_vendor_count": overdue_vendor_count,
    }


# ─── Cari Detay (get_vendor_detail gövdesi — birebir) ────────────────

def vendor_detail(
    db: Session,
    vendor_id: int,
    page: int,
    page_size: int,
    sort_by: Optional[str],
    sort_dir: Optional[str],
):
    """Cari detayını ve işlemlerini getir.

    Varsayılan sıralama tarih DESC (en yeni üstte). `sort_by` whitelist'li kolon
    sıralaması sunar; `bakiye` sıralaması kronolojik kümülatif bakiye kolonuna göredir.
    """
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")

    totals = (
        db.query(
            func.coalesce(func.sum(VendorTransaction.borc), 0),
            func.coalesce(func.sum(VendorTransaction.alacak), 0),
        )
        .filter(VendorTransaction.vendor_id == vendor_id)
        .first()
    )
    total_borc = float(totals[0])
    total_alacak = float(totals[1])

    running_balance = func.sum(VendorTransaction.borc - VendorTransaction.alacak).over(
        order_by=[VendorTransaction.date.asc(), VendorTransaction.id.asc()]
    ).label("running_balance")

    total_count = (
        db.query(func.count(VendorTransaction.id))
        .filter(VendorTransaction.vendor_id == vendor_id)
        .scalar()
        or 0
    )
    # Kolon sıralaması (whitelist) — bakiye = pencere fonksiyonuyla hesaplanan kümülatif kolon
    tx_sort_map = {
        "date": VendorTransaction.date,
        "evrak_no": VendorTransaction.evrak_no,
        "transaction_type": VendorTransaction.transaction_type,
        "borc": VendorTransaction.borc,
        "alacak": VendorTransaction.alacak,
        "bakiye": running_balance,
    }
    if sort_by and sort_by in tx_sort_map:
        order_col = tx_sort_map[sort_by]
        primary = desc(order_col) if sort_dir == "desc" else order_col
        order_exprs = [primary, VendorTransaction.date.desc(), VendorTransaction.id.desc()]
    else:
        order_exprs = [VendorTransaction.date.desc(), VendorTransaction.id.desc()]

    rows = (
        db.query(VendorTransaction, running_balance)
        .filter(VendorTransaction.vendor_id == vendor_id)
        .order_by(*order_exprs)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    transactions = [row[0] for row in rows]

    dept_map, cat_map, user_map = _build_dept_cat_user_maps(db, transactions)

    # Fatura satırı durum çipleri (Kapandı / Gecikti / Vade) için FIFO kalanları —
    # Ödeme Planı ile aynı kaynak. Tam ödenmiş faturalar haritada yer almaz (kalan=0).
    fifo_map = calculate_fifo_amounts(db)

    items = []
    for tx, rb in rows:
        item = _build_tx_response(tx, dept_map, cat_map, user_map)
        item["bakiye"] = float(rb) if rb is not None else None
        if float(tx.alacak) > 0:
            item["fifo_remaining"] = round(float(fifo_map.get(tx.id, 0.0)), 2)
        items.append(item)

    # ── Özet kart metrikleri (tasarım: Vadesi Geçmiş / Son Ödeme) ──
    # Vadesi geçmiş = NET ödenmemiş, vadesi dolmuş fatura payı (Ödeme Planı ile aynı FIFO
    # kaynağından). Brüt fatura toplamı DEĞİL — ödemeler en eski faturalardan düşülür, kalan
    # gecikmiş kısım net borçla sınırlıdır. (Eski brüt hesap net bakiyeden kat kat büyük
    # çıkabiliyordu; ör. net −558K'ya karşı brüt 1.57M.)
    overdue_map = calculate_overdue_by_vendor(db, vendor_ids=[vendor_id])
    overdue, overdue_count = overdue_map.get(vendor_id, (0.0, 0))

    # Son ödeme = en yeni borç (ödeme) kaydı.
    last_pay = (
        db.query(VendorTransaction)
        .filter(
            VendorTransaction.vendor_id == vendor_id,
            VendorTransaction.borc > 0,
        )
        .order_by(VendorTransaction.date.desc(), VendorTransaction.id.desc())
        .first()
    )

    return {
        "vendor": VendorDetailResponse(
            id=vendor.id,
            hesap_kodu=vendor.hesap_kodu,
            hesap_adi=vendor.hesap_adi,
            payment_days=vendor.payment_days,
            status=vendor.status,
            total_borc=total_borc,
            total_alacak=total_alacak,
            bakiye=total_borc - total_alacak,
            contact_person=vendor.contact_person,
            phone=vendor.phone,
            email=vendor.email,
            overdue=overdue,
            overdue_count=overdue_count,
            last_payment_amount=float(last_pay.borc) if last_pay else None,
            last_payment_date=last_pay.date if last_pay else None,
        ).model_dump(),
        "transactions": {
            "items": items,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "pages": math.ceil(total_count / page_size) if total_count > 0 else 1,
        },
    }
