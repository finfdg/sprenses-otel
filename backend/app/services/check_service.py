"""Çek domain servis katmanı — durum güncelleme + iptal kademesi + finance_event tazeleme (HTTP'siz).

D1-2 (2026-06-22): Çek durum güncelleme mutasyon mantığı TEK kaynakta. Hem router endpoint'i
(`checks.py::update_check_status`) hem onay executor handler'ı (`_handle_finance_checks`) AYNI
fonksiyonu çağırır → router↔executor sapması (sessiz bug) yapısal olarak engellenir. Özellikle
**iptal kademesi** (eşleşmiş çek iptal → cari + banka eşleşmesini kaldır) iki yerde elle
tekrarlanıyordu; router değişse executor sessizce saparak yetim/yanlış eşleşme bırakabilirdi.
"""
from sqlalchemy.orm import Session

from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.vendor_transaction import VendorTransaction
from app.utils.finance_event_service import finance_event_svc


def apply_check_status(db: Session, check: Check, new_status: str) -> None:
    """Çek durumunu güncelle. İptal ise eşleşmeyi (cari + banka) kaldır, sonra finance_event tazele.

    HTTP'siz, commit'siz (çağıran commit eder). Router (`update_check_status`) ve onay executor'ı
    (`_handle_finance_checks`) ORTAK çağırır → davranış birebir.
    """
    # Eşleştirilmiş çekin iptal edilmesi → eşleşmeyi de kaldır
    if new_status == "cancelled":
        # Cari eşleşmesi (match_number ile direkt bul)
        if check.match_number:
            matched_vtx = db.query(VendorTransaction).filter(
                VendorTransaction.match_number == check.match_number,
            ).first()
            if matched_vtx:
                matched_vtx.match_number = None
                matched_vtx.payment_method = None
            check.match_number = None
            check.matched_vendor_id = None

        # Banka eşleşmesini de kaldır
        if check.bank_transaction_id:
            btx = db.query(BankTransaction).filter(BankTransaction.id == check.bank_transaction_id).first()
            if btx:
                btx.match_number = None
            check.bank_transaction_id = None

    check.status = new_status

    # finance_events'i güncelle (eşleşmişse banka hareketiyle birlikte)
    bank_tx = None
    if check.bank_transaction_id:
        bank_tx = db.query(BankTransaction).filter(BankTransaction.id == check.bank_transaction_id).first()
    finance_event_svc.upsert_check(db, check, bank_tx)
