#!/usr/bin/env python3
"""USD finance_events kayıtlarının NULL amount_try'ını geriye dönük doldurur.

Neden: `update_amount_try` yalnız EUR doldurur ve cron yalnız bugünün kayıtlarına
dokunur → geçmiş tarihli içe aktarılan USD banka satırlarının amount_try'ı NULL
kalıyordu (2026-07-19 canlı denetim: 11 kayıt). Panel/T-Hesap 2026-07-19 itibarıyla
USD'yi okuma anında USD/EUR çaprazıyla çevirir (amount_try'a bakmaz); bu script
amount_try tüketicileri (nakit akım liste yanıtı, aging toplamı, kur farkı izi)
için veri hijyenidir.

Kural: amount_try = amount × (event_date'teki <= en yakın TCMB USD forex_buying / unit).
Kur bulunamayan kayıt ATLANIR (1:1 varsayımı yapılmaz).

Kullanım:
  python backfill_usd_amount_try.py            # KURU ÇALIŞMA — yalnız listeler, yazmaz
  python backfill_usd_amount_try.py --apply    # Gerçekten yazar (tek commit)
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def usd_buying_at(db, dt):
    """dt tarihindeki (<= en yakın) TCMB USD alış kuru (birim başına); yoksa None."""
    row = (
        db.query(ExchangeRate.forex_buying, ExchangeRate.unit)
        .filter(
            ExchangeRate.currency_code == "USD",
            ExchangeRate.date <= dt,
            ExchangeRate.forex_buying.isnot(None),
        )
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    if row and row.forex_buying:
        return float(row.forex_buying) / float(row.unit or 1)
    return None


def main():
    parser = argparse.ArgumentParser(description="USD finance_events amount_try backfill")
    parser.add_argument("--apply", action="store_true",
                        help="Değişiklikleri gerçekten yaz (varsayılan: kuru çalışma)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        events = (
            db.query(FinanceEvent)
            .filter(FinanceEvent.currency == "USD", FinanceEvent.amount_try.is_(None))
            .order_by(FinanceEvent.event_date.asc())
            .all()
        )
        logger.info("USD + amount_try NULL kayıt sayısı: %d", len(events))

        filled, skipped = 0, 0
        for fe in events:
            rate = usd_buying_at(db, fe.event_date)
            if not rate:
                skipped += 1
                logger.warning("ATLANDI id=%s tarih=%s: USD kuru yok", fe.id, fe.event_date)
                continue
            new_try = round(float(fe.amount) * rate, 2)
            logger.info(
                "id=%-6s %s  %s/%s  %+.2f USD × %.4f → amount_try=%.2f%s",
                fe.id, fe.event_date, fe.source_type, fe.source_id,
                float(fe.amount) * (fe.direction or 1), rate, new_try,
                "" if args.apply else "  [KURU ÇALIŞMA]",
            )
            if args.apply:
                fe.amount_try = new_try
            filled += 1

        if args.apply:
            db.commit()
            logger.info("YAZILDI: %d kayıt güncellendi, %d atlandı", filled, skipped)
        else:
            db.rollback()
            logger.info("KURU ÇALIŞMA bitti: %d kayıt doldurulurdu, %d atlanırdı. "
                        "Yazmak için: --apply", filled, skipped)
    finally:
        db.close()


if __name__ == "__main__":
    main()
