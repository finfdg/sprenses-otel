"""Cari (vendor) domain servis katmanı — vade/durum güncelleme + finance_events senkron (HTTP'siz).

D1-2 (2026-06-22): Cari güncelleme mutasyon mantığı TEK kaynakta. Hem router endpoint'leri
(`cariler/vendors.py` → payment-days + status) hem onay executor handler'ı (`_handle_finance_cariler`)
AYNI fonksiyonu çağırır → router↔executor sapması (sessiz bug) yapısal olarak engellenir. Önceki
executor handler'ı router mantığını elle tekrarlıyordu (doğrulama yoktu; router değişse sessiz sapardı).
"""
from sqlalchemy.orm import Session

from app.models.vendor import VENDOR_STATUS_CHOICES, Vendor
from app.models.vendor_transaction import VendorTransaction
from app.utils.finance_event_service import finance_event_svc
from app.utils.sync_vendor_fifo import sync_vendor_finance_events
from app.utils.vendor_parser import calculate_payment_friday


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
