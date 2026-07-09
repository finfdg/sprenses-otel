"""Zamanlanmış görev: QNB hesapları için hesap hareketlerini API'den çek.

`cron_fetch_bank_statements.py` (Yapı Kredi) deseninde. Her aktif QNB banka hesabı için son
N günün hareketlerini Account Statement V2 API'sinden çeker ve mevcut ekstre içe-aktarma
akışına (`_process_statement` + `_post_upload_processing`) besler → dedup (tx_hash),
finance_event upsert ve otomatik eşleştirme aynen yeniden kullanılır. QNB IBAN ile sorgulanır.

Kullanım (crontab örneği — her gün 07:15):
    15 7 * * * cd /path/backend && python cron_fetch_qnb_statements.py

Ortam değişkenleri (.env): QNB_CLIENT_ID, QNB_CLIENT_SECRET, QNB_REFRESH_TOKEN (ilk tohum),
QNB_TOKEN_URL, QNB_BASE_URL. ⚠️ refresh_token ROTATING → `.qnb_refresh_token` dosyasında saklanır.
"""
import asyncio
import logging
import os
import sys
from datetime import date, timedelta

from fastapi import BackgroundTasks

from app.database import SessionLocal
from app.models.bank_account import BankAccount
from app.models.user import User
from app.routers.finance.bank_statement_import import (
    _post_upload_processing,
    _process_statement,
)
from app.utils.qnb_api import fetch_qnb_statement, qnb_configured

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cron_fetch_qnb_statements")

LOOKBACK_DAYS = int(os.getenv("QNB_LOOKBACK_DAYS", "7"))
QNB_BANK_NAME = os.getenv("QNB_BANK_NAME", "QNB")


class _ApiFile:
    """_process_statement file.filename bekler; API kaynağı için sahte dosya nesnesi."""

    def __init__(self, filename: str):
        self.filename = filename


def _system_user(db) -> User:
    user = db.query(User).filter(User.is_active == True).order_by(User.id).first()  # noqa: E712
    if not user:
        raise RuntimeError("Aktif kullanıcı bulunamadı — içe-aktarma için gerekli.")
    return user


def _fetch_account(db, acc: BankAccount, user: User) -> bool:
    """Tek bir QNB hesabı için hareketleri çek + içe aktar. IBAN ile sorgulanır."""
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    logger.info("QNB hesap %s (%s) çekiliyor: %s..%s", acc.iban, acc.currency, start, end)

    parsed = fetch_qnb_statement(start=start, end=end, iban=acc.iban,
                                 account_no=acc.account_no, currency=acc.currency)
    if not parsed.transactions:
        logger.info("QNB hesap %s: yeni hareket yok.", acc.iban)
        return True

    api_file = _ApiFile(f"qnb_{acc.iban}_{start:%Y%m%d}_{end:%Y%m%d}.api")
    virtual_path = f"api://qnb/{acc.iban}/{start:%Y%m%d}-{end:%Y%m%d}"

    result = _process_statement(
        db=db, acc=acc, parsed=parsed, file=api_file, file_path=virtual_path,
        file_type="api", unique_name=api_file.filename, current_user=user, ip_address="cron",
    )
    asyncio.run(_post_upload_processing(
        db=db, acc=acc, result=result, current_user=user, background_tasks=BackgroundTasks(),
    ))
    logger.info("QNB hesap %s içe aktarıldı: %s", acc.iban, result)
    return True


def main() -> int:
    if not qnb_configured():
        logger.warning("QNB yapılandırılmamış (QNB_CLIENT_ID/SECRET/REFRESH_TOKEN) — atlanıyor.")
        return 0
    db = SessionLocal()
    errors = 0
    try:
        user = _system_user(db)
        accounts = (
            db.query(BankAccount)
            .filter(BankAccount.bank_name.ilike(f"%{QNB_BANK_NAME}%"), BankAccount.is_active.is_(True))
            .all()
        )
        if not accounts:
            logger.warning("'%s' adına eşleşen aktif banka hesabı yok.", QNB_BANK_NAME)
            return 0
        for acc in accounts:
            try:
                _fetch_account(db, acc, user)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                errors += 1
                logger.exception("QNB hesap %s çekilirken hata.", acc.iban)
    finally:
        db.close()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
