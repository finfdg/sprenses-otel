"""Tek-seferlik onarım: gerçek eşleşme izi olan planlı FE bacaklarının is_matched bayrağı.

2026-07-19 canlı denetimi: `event_matches`'te gerçek (method != 'suggestion') banka↔planlı
izi dururken hedef finance_event `is_matched=False` kalabiliyordu → t_account iki bacağı
da toplayıp geçmiş ay giderlerini ÇİFT sayıyordu. Kod tarafı kapatıldı
(`upsert_scheduled_entry` bayrağı artık izden türetir); bu script mevcut verideki
sürüklenmeyi raporlar ve İSTENİRSE onarır.

Kural (tek yönlü, muhafazakâr):
- Gerçek iz VAR + hedef FE is_matched=False  → is_matched=True + is_realized=True yapılır.
- İz olmayan FE'lere DOKUNULMAZ (Faz B öncesi eski eşleşmelerde iz olmayabilir — bayrak
  izsiz diye asla False'a çekilmez).
- vendor_payment hedefleri kapsam DIŞI (cari kuralı: eşleşme is_matched'ı değiştirmez).

Kullanım (worktree'den DEĞİL, canlı checkout'tan):
    cd /home/ec2-user/otel/backend && source venv/bin/activate
    python fix_scheduled_match_flags.py            # DRY-RUN: yalnız raporlar, yazmaz
    python fix_scheduled_match_flags.py --apply    # onarır (kullanıcı onayı alındıktan sonra)
"""
import sys

from app.database import SessionLocal
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.finance_event import FinanceEvent

# ScheduledEntry.source_type evreni (matcher şu an salary/sgk/withholding kullanıyor ama
# köprü/öneri yolları tüm planlı türlere açık — hepsi taransın)
SCHEDULED_SOURCE_TYPES = (
    "tax", "recurring", "salary", "withholding", "sgk",
    "rent_income", "rent_expense", "dividend",
)


def main(apply: bool) -> int:
    db = SessionLocal()
    try:
        matches = (db.query(EventMatch)
                   .filter(EventMatch.method != MATCH_METHOD_SUGGESTION,
                           EventMatch.target_source_type.in_(SCHEDULED_SOURCE_TYPES))
                   .order_by(EventMatch.id)
                   .all())
        print(f"Gerçek banka↔planlı eşleşme izi: {len(matches)} kayıt")

        drift = []
        for m in matches:
            fe = (db.query(FinanceEvent)
                  .filter(FinanceEvent.source_type == m.target_source_type,
                          FinanceEvent.source_id == m.target_source_id)
                  .first())
            if fe is None:
                print(f"  UYARI: event_match #{m.id} hedef FE yok "
                      f"({m.target_source_type}#{m.target_source_id}) — elle incele")
                continue
            if not fe.is_matched:
                drift.append((m, fe))

        if not drift:
            print("Sürüklenme yok — tüm iz sahibi planlı bacaklar is_matched=True. ✓")
            return 0

        print(f"\nSürüklenmiş {len(drift)} bacak (iz var, bayrak False):")
        seen_fe = set()
        for m, fe in drift:
            print(f"  event_match #{m.id}: bank#{m.bank_source_id} ↔ "
                  f"{m.target_source_type}#{m.target_source_id} "
                  f"(FE {fe.id}, tutar {float(fe.amount):,.2f}, tarih {fe.event_date})")
            seen_fe.add(fe.id)

        if not apply:
            print(f"\nDRY-RUN — veri DEĞİŞMEDİ. Onarmak için: python {sys.argv[0]} --apply")
            return 1

        for m, fe in drift:
            if fe.id in seen_fe:  # aynı FE'ye birden çok iz (1-N kısmi) → tek update yeter
                fe.is_matched = True
                fe.is_realized = True
                seen_fe.discard(fe.id)
        db.commit()
        print(f"\nOnarıldı: {len(drift)} iz / {len({fe.id for _, fe in drift})} FE bacağı "
              "is_matched=True + is_realized=True yapıldı.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv[1:]))
