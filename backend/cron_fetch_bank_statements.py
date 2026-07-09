"""Zamanlanmış görev: Yapı Kredi hesapları için hesap hareketlerini API'den çek.

Repodaki cron_fetch_exchange_rates.py deseninde çalışır. Her aktif Yapı Kredi banka
hesabı için son N günün hareketlerini Account Transaction List API'sinden çeker ve
mevcut ekstre içe-aktarma akışına (_process_statement + _post_upload_processing)
besler. Böylece dedup (tx_hash), finance_event upsert ve otomatik eşleştirme mantığı
aynen yeniden kullanılır.

Kullanım (crontab örneği — her gün 07:00):
    0 7 * * * cd /path/backend && python cron_fetch_bank_statements.py

Ortam değişkenleri (.env): YKB_CLIENT_ID, YKB_CLIENT_SECRET, YKB_TOKEN_URL, YKB_SCOPE
"""
import asyncio
import logging
import os
import sys
from datetime import date, timedelta
from typing import Optional

from fastapi import BackgroundTasks

from app.database import SessionLocal
from app.models.bank_account import BankAccount
from app.models.user import User
from app.routers.finance.bank_statement_import import (
    _post_upload_processing,
    _process_statement,
)
from app.utils.yapikredi_api import fetch_yapikredi_statement

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cron_fetch_bank_statements")

# Kaç günlük geriye dönük hareket çekilsin (çakışan günler tx_hash ile deduplike edilir)
LOOKBACK_DAYS = int(os.getenv("YKB_LOOKBACK_DAYS", "7"))
# Bu banka adına sahip hesaplar API'den çekilir
YKB_BANK_NAME = os.getenv("YKB_BANK_NAME", "Yapı Kredi")


class _ApiFile:
    """_process_statement, file.filename bekler; API kaynağı için sahte dosya nesnesi."""

    def __init__(self, filename: str):
        self.filename = filename


def _system_user(db) -> User:
    """İçe-aktarmayı yürütecek sistem kullanıcısı (ilk aktif kullanıcı)."""
    user = (
        db.query(User)
        .filter(User.is_active == True)  # noqa: E712
        .order_by(User.id)
        .first()
    )
    if not user:
        raise RuntimeError("Aktif kullanıcı bulunamadı — içe-aktarma için gerekli.")
    return user


def _ykb_ccy(currency: Optional[str]) -> str:
    """Sistem para birimini YKB API biçimine çevir (YKB Türk Lirası için 'TL' bekler)."""
    c = (currency or "").upper()
    return "TL" if c in ("TL", "TRY", "") else c


def _fetch_account(db, acc: BankAccount, user: User) -> bool:
    """Tek bir hesap için hareketleri çek ve içe aktar. account_no yoksa atlar (False döner)."""
    if not (acc.account_no or "").strip():
        # YKB API IBAN değil HESAP NUMARASI ister → numarasız hesap senkronlanamaz.
        logger.warning("Hesap %s (IBAN …%s): account_no boş → atlandı.", acc.iban, acc.iban[-4:])
        return False

    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    logger.info("Hesap %s (%s) çekiliyor: %s..%s", acc.iban, acc.currency, start, end)

    parsed = fetch_yapikredi_statement(
        account_no=acc.account_no.strip(),
        ccy=_ykb_ccy(acc.currency),
        start=start,
        end=end,
        iban=acc.iban,
    )
    if not parsed.transactions:
        logger.info("Hesap %s: yeni hareket yok.", acc.iban)
        return True

    api_file = _ApiFile(f"ykb_{acc.iban}_{start:%Y%m%d}_{end:%Y%m%d}.api")
    virtual_path = f"api://yapikredi/{acc.iban}/{start:%Y%m%d}-{end:%Y%m%d}"

    result = _process_statement(
        db=db,
        acc=acc,
        parsed=parsed,
        file=api_file,
        file_path=virtual_path,
        file_type="api",
        unique_name=api_file.filename,
        current_user=user,
        ip_address="cron",
    )

    asyncio.run(
        _post_upload_processing(
            db=db,
            acc=acc,
            result=result,
            current_user=user,
            background_tasks=BackgroundTasks(),
        )
    )
    logger.info("Hesap %s içe aktarıldı: %s", acc.iban, result)
    return True


def main() -> int:
    db = SessionLocal()
    errors = 0
    try:
        user = _system_user(db)
        accounts = (
            db.query(BankAccount)
            .filter(BankAccount.bank_name.ilike(f"%{YKB_BANK_NAME}%"))
            .all()
        )
        if not accounts:
            logger.warning("'%s' adına eşleşen banka hesabı yok.", YKB_BANK_NAME)
            return 0

        for acc in accounts:
            try:
                _fetch_account(db, acc, user)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                errors += 1
                logger.exception("Hesap %s çekilirken hata.", acc.iban)
    finally:
        db.close()

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
