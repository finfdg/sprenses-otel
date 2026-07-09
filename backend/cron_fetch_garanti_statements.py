"""Zamanlanmış görev: Garanti BBVA hesapları için hesap hareketlerini API'den çek.

`cron_fetch_qnb_statements.py` deseninde. Her aktif Garanti hesabı için son N günün (max 30)
hareketlerini Account Transactions API'sinden çeker ve mevcut ekstre içe-aktarma akışına
(`_process_statement` + `_post_upload_processing`) besler → dedup + finance_event + otomatik
eşleştirme yeniden kullanılır. IBAN ile sorgulanır.

Kullanım (crontab örneği — her gün 07:30):
    30 7 * * * cd /path/backend && python cron_fetch_garanti_statements.py

Ortam değişkenleri (.env): GARANTI_CLIENT_ID, GARANTI_CLIENT_SECRET, GARANTI_CONSENT_ID.
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
from app.utils.garanti_api import fetch_garanti_statement, garanti_configured

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cron_fetch_garanti_statements")

LOOKBACK_DAYS = min(int(os.getenv("GARANTI_LOOKBACK_DAYS", "30")), 30)  # banka limiti max 30
GARANTI_BANK_NAME = os.getenv("GARANTI_BANK_NAME", "Garanti")


class _ApiFile:
    def __init__(self, filename: str):
        self.filename = filename


def _system_user(db) -> User:
    user = db.query(User).filter(User.is_active == True).order_by(User.id).first()  # noqa: E712
    if not user:
        raise RuntimeError("Aktif kullanıcı bulunamadı — içe-aktarma için gerekli.")
    return user


def _fetch_account(db, acc: BankAccount, user: User) -> bool:
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    logger.info("Garanti hesap %s (%s) çekiliyor: %s..%s", acc.iban, acc.currency, start, end)

    parsed = fetch_garanti_statement(start=start, end=end, iban=acc.iban,
                                     account_no=acc.account_no, currency=acc.currency)
    if not parsed.transactions:
        logger.info("Garanti hesap %s: yeni hareket yok.", acc.iban)
        return True

    api_file = _ApiFile(f"garanti_{acc.iban}_{start:%Y%m%d}_{end:%Y%m%d}.api")
    virtual_path = f"api://garanti/{acc.iban}/{start:%Y%m%d}-{end:%Y%m%d}"

    result = _process_statement(
        db=db, acc=acc, parsed=parsed, file=api_file, file_path=virtual_path,
        file_type="api", unique_name=api_file.filename, current_user=user, ip_address="cron",
    )
    asyncio.run(_post_upload_processing(
        db=db, acc=acc, result=result, current_user=user, background_tasks=BackgroundTasks(),
    ))
    logger.info("Garanti hesap %s içe aktarıldı: %s", acc.iban, result)
    return True


def main() -> int:
    if not garanti_configured():
        logger.warning("Garanti yapılandırılmamış (GARANTI_CLIENT_ID/SECRET/CONSENT_ID) — atlanıyor.")
        return 0
    db = SessionLocal()
    errors = 0
    try:
        user = _system_user(db)
        accounts = (
            db.query(BankAccount)
            .filter(BankAccount.bank_name.ilike(f"%{GARANTI_BANK_NAME}%"), BankAccount.is_active.is_(True))
            .all()
        )
        if not accounts:
            logger.warning("'%s' adına eşleşen aktif banka hesabı yok.", GARANTI_BANK_NAME)
            return 0
        for acc in accounts:
            try:
                _fetch_account(db, acc, user)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                errors += 1
                logger.exception("Garanti hesap %s çekilirken hata.", acc.iban)
    finally:
        db.close()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
