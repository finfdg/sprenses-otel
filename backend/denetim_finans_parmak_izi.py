#!/usr/bin/env python3
"""Finansal parmak izi — kod değişikliğinin SESSİZ tutar kaymasına yol açıp açmadığını ölçer.

NEDEN VAR
    Denetim otomasyonu bir bulguyu düzeltip testler yeşilse canlıya deploy ediyor. Ama
    test takımı ve `/api/health` yalnız **çökmeyi** yakalar; kodun bir finansal sayıyı
    yanlış hesaplamaya başlamasını GÖREMEZ. Denetimin FIN-001 bulgusu tam bu sınıftı:
    yönetim raporlarında ₺696.190,94 hayalet para, aylarca sessiz, hiçbir test kırmızı değil.

NASIL ÇALIŞIR
    Aynı veritabanı üzerinde ESKİ kodla ve YENİ kodla çalıştırılır; ürettiği sayılar
    karşılaştırılır. Kod dışı hiçbir şey değişmediği için sayılar da değişmemelidir.

    cron_denetim_auto.py üç ölçüm alır:
        A  = eski kod (master checkout)
        B  = yeni kod (worktree)
        A2 = eski kod, tekrar          ← KONTROL
    A != A2 ise ölçüm penceresinde canlı veri değişmiştir (Sedna senkronu, kullanıcı
    işlemi) → karşılaştırma anlamsızdır, atlanır. A == A2 iken B != A ise farkı ÜRETEN
    şey kodun kendisidir → deploy edilmez.

GÜVENLİK
    Ölçüm `SET TRANSACTION READ ONLY` içinde koşar ve sonunda rollback edilir. Denetimin
    API-003 bulgusuna göre bazı okuma yolları (cari payment-schedule) okurken
    `finance_events`'e YAZIYOR — bu tasarım o yazmayı üretime ulaşmadan reddeder;
    değişmez "hata" değeri üretir ve iki ölçümde de aynı hatayı verdiği için
    karşılaştırmayı bozmaz.

    Bu dosya `cron_denetim_auto.DEPLOY_BLOCKERS` listesindedir — otomasyon kendi
    kapısını değiştirip geçemez.

Kullanım:
    python denetim_finans_parmak_izi.py              # JSON stdout
    python denetim_finans_parmak_izi.py --pretty     # okunur biçim
"""
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402

# Ölçüm sırasında referans alınacak tarih — iki ölçüm arasında gün dönerse
# tarihe bağlı hesaplar kayar. Cron aynı değeri her üç ölçüme de geçirir.
REF_DATE_ENV = "DENETIM_PARMAK_IZI_REF_DATE"


def _round(value):
    """Para değerlerini kuruşa yuvarla — float gürültüsü yanlış alarm üretmesin."""
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


# ─── Değişmezler ─────────────────────────────────────────────
# Her giriş: (anahtar, açıklama, ölçüm fonksiyonu)
# Fonksiyon yalnız `db` (ve gerekiyorsa `ref_date`) alır ve sayı/sözlük döndürür.
# YENİ DEĞİŞMEZ EKLERKEN: salt-okunur olduğundan emin ol ve deterministik yaz.

def _invariants():
    """Ölçülecek değişmezleri döndür (liste: dict)."""
    from app.services import audit_finance_invariants as inv
    return inv.INVARIANTS


def measure(pretty: bool = False) -> dict:
    ref_date = os.environ.get(REF_DATE_ENV) or None
    out = {"_ref_date": ref_date, "_values": {}, "_errors": {}}

    db = SessionLocal()
    try:
        # Üretim verisine kazara yazmayı ŞEMA seviyesinde imkânsız kıl
        db.execute(text("SET TRANSACTION READ ONLY"))

        for item in _invariants():
            key = item["key"]
            try:
                value = item["fn"](db, ref_date)
                out["_values"][key] = _round(value)
            except Exception as e:
                # Hata da bir "değer"dir: iki ölçümde aynıysa karşılaştırmayı bozmaz.
                # Farklıysa zaten kodun davranışı değişmiş demektir → yakalanır.
                out["_errors"][key] = f"{type(e).__name__}: {str(e)[:200]}"
                out["_values"][key] = f"__hata__:{type(e).__name__}"
            finally:
                # Bir değişmezin açtığı transaction bir sonrakini etkilemesin
                try:
                    db.rollback()
                    db.execute(text("SET TRANSACTION READ ONLY"))
                except Exception:
                    pass
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Finansal parmak izi ölçümü")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    try:
        result = measure()
    except Exception:
        print(json.dumps({"_fatal": traceback.format_exc()[-2000:]}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                     indent=2 if args.pretty else None, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
