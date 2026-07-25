#!/usr/bin/env python3
"""TRY finance_events kayıtlarındaki BAYAT amount_try'ı gerçek tutara hizalar (FIN-001).

Neden: hiçbir `upsert_*` metodu `amount_try` yazmıyordu → `_upsert`'in
`ON CONFLICT DO UPDATE SET` bloğu bu kolona hiç dokunmuyordu. Cari FIFO kırpması /
KK kısmi ödemesi `amount`'ı küçültünce `amount_try` ESKİ TAM TUTARDA donuyordu.
Okuyucular (t_account / runway / aging) `amount_try`'ı `amount`'a tercih ettiğinden
bayat değer yönetim raporlarına hayalet yükümlülük yazıyordu.

Canlı ölçüm (2026-07-24): 11 bayat TRY kaydı, toplam sapma ₺2.426.887,85 —
bunlardan 6'sı hâlâ AÇIK (is_matched=false AND is_realized=false) → Panel T-Hesap,
Nakit Koruma ve Yaşlananlar raporlarında ₺696.190,94 olmayan borç.

KOD DÜZELTMESİ AYRI VE ÖNCELİKLİDİR (bu script yalnız geçmiş veriyi temizler):
  - YAZICI : `finance_event_service._upsert` artık TRY'de amount_try = amount türetir
  - OKUYUCU: `t_account._event_eur` / `runway._event_eur` TRY dalını öne aldı
  - TEST   : `tests/test_amount_try_integrity.py` (7 test, iki katman da kanıtlandı)

Kural: TRY/TL kaleminde `amount` TANIMI GEREĞİ TL karşılığıdır → amount_try = amount.
Döviz kalemlere DOKUNULMAZ (TL karşılığı kur gerektirir; okuma anında çevrilir).

Kullanım:
  python fix_stale_amount_try.py            # KURU ÇALIŞMA — yalnız listeler, yazmaz
  python fix_stale_amount_try.py --apply    # Gerçekten yazar (tek commit)
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.finance_event import FinanceEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fix_stale_amount_try")

TOLERANCE = 0.01  # kuruş altı fark sapma sayılmaz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Gerçekten yaz (varsayılan: kuru çalışma)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = (
            db.query(FinanceEvent)
            .filter(
                FinanceEvent.currency.in_(("TRY", "TL")),
                FinanceEvent.amount_try.isnot(None),
            )
            .order_by(FinanceEvent.id)
            .all()
        )

        stale = [r for r in rows
                 if abs(float(r.amount_try) - float(r.amount)) > TOLERANCE]

        if not stale:
            logger.info("Bayat TRY kaydı YOK — veri temiz.")
            return 0

        total_drift = sum(abs(float(r.amount_try) - float(r.amount)) for r in stale)
        open_rows = [r for r in stale if not r.is_matched and not r.is_realized]
        phantom = sum(float(r.amount_try) - float(r.amount) for r in open_rows)

        logger.info("Bayat TRY kaydı: %d — toplam sapma ₺%s", len(stale), f"{total_drift:,.2f}")
        logger.info("Bunlardan AÇIK (rapora yansıyan): %d — hayalet tutar ₺%s",
                    len(open_rows), f"{phantom:,.2f}")
        logger.info("-" * 78)
        for r in stale:
            flag = "AÇIK " if (not r.is_matched and not r.is_realized) else "kapalı"
            logger.info(
                "  fe#%-6s %-16s %s  amount=%14s  amount_try=%14s  → %s",
                r.id, r.source_type, flag,
                f"{float(r.amount):,.2f}", f"{float(r.amount_try):,.2f}",
                f"{float(r.amount):,.2f}",
            )
        logger.info("-" * 78)

        if not args.apply:
            logger.info("KURU ÇALIŞMA — hiçbir şey yazılmadı. Uygulamak için: --apply")
            return 0

        for r in stale:
            r.amount_try = r.amount
        db.commit()
        logger.info("UYGULANDI: %d kayıt hizalandı (amount_try = amount).", len(stale))

        # Doğrulama — kapanış kriteri
        remaining = [
            r for r in db.query(FinanceEvent).filter(
                FinanceEvent.currency.in_(("TRY", "TL")),
                FinanceEvent.amount_try.isnot(None),
            ).all()
            if abs(float(r.amount_try) - float(r.amount)) > TOLERANCE
        ]
        if remaining:
            logger.error("DOĞRULAMA BAŞARISIZ — hâlâ %d bayat kayıt var!", len(remaining))
            return 1
        logger.info("DOĞRULAMA: bayat TRY kaydı 0 ✔ (kapanış kriteri sağlandı)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
