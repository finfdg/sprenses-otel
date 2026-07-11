"""Banka hesabı domain servis katmanı — CRUD (HTTP'siz, yan etkisiz).

D1-2 (2026-06-22): Router (banks.py accounts) ve onay executor (_handle_finance_banks) ORTAK çağırır.
"""
from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount


def create_account(db: Session, data: dict, actor_id) -> BankAccount:
    acc = BankAccount(
        bank_name=data.get("bank_name", ""),
        branch_name=data.get("branch_name"),
        account_no=data.get("account_no"),
        iban=data.get("iban"),
        currency=data.get("currency", "TRY"),
        holder_name=data.get("holder_name"),
        blocked_amount=data.get("blocked_amount", 0),
        created_by=actor_id,
    )
    db.add(acc)
    return acc


def apply_account_update(db: Session, acc: BankAccount, update_data: dict) -> None:
    for key, value in update_data.items():
        if key.startswith("_"):
            continue
        if hasattr(acc, key):
            setattr(acc, key, value)


def delete_account(db: Session, acc: BankAccount) -> None:
    """Hesabı eşleşme/FE temizliğiyle sil (Faz 3 #24 — denetim C5 kapatıldı).

    Eskiden yalnız db.delete: cascade işlemleri silerken çek/taksit/avans 'bankasız
    ödendi' kalıyor, source_type='bank' FE'leri orphan kalıyordu. Router + onay
    executor'ı bu fonksiyonu ORTAK kullandığından iki yol da temiz.
    """
    from app.services.bank_release_service import delete_account_with_cleanup

    totals = delete_account_with_cleanup(db, acc)
    if totals.get("needs_vendor_sync"):
        from app.utils.sync_vendor_fifo import sync_vendor_finance_events
        sync_vendor_finance_events(db)
