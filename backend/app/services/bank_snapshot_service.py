"""Anlık banka nakdi + tarih bazlı kur okuma — `cash_flow/_helpers.py`'den BİREBİR çıkarım (2026-09-02).

Yeniden yapılandırma (katman yönü: router → service → model). Bu modüldeki `_get_eur_rate`,
`_get_fx_buying`, `_latest_buying` ve `bank_snapshot` gövdeleri
`app/routers/finance/cash_flow/_helpers.py`'den satırı satırına, DEĞİŞTİRİLMEDEN taşındı
(finansal parmak izi kapısı: eski-kod/yeni-kod 41 değişmez sıfır fark vermelidir — hiçbir
varsayılan, yuvarlama, guard ya da sorgu sırası değiştirilmedi). `_helpers.py` bu adları
geriye uyumluluk için yeniden dışa verir (runway / chart / t_account `from ._helpers import ...`
ve testler o yoldan çözmeye devam eder).

`CROSS_EUR_CURRENCIES` tek kaynağı `app/services/fx_rates.py` — buradan da yeniden dışa verilir.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.exchange_rate import ExchangeRate
from app.services.fx_rates import CROSS_EUR_CURRENCIES  # noqa: F401 — re-export (tek kaynak services/fx_rates)


def _get_eur_rate(db: Session, target_date) -> float:
    """Belirli tarih için EUR/TRY alış kuru."""
    rate = (
        db.query(ExchangeRate.forex_buying)
        .filter(ExchangeRate.currency_code == "EUR", ExchangeRate.date <= target_date)
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    return float(rate[0]) if rate and rate[0] else 1.0


# EUR'a çapraz kurla çevrilen dövizler (amount × {code} alış / EUR alış) — TCMB üçü
# için de günlük kur çeker; amount_try'a BAKILMAZ. USD 2026-07-19 kararı; GBP
# 2026-08-14'te ilk GBP hesabı (Halkbank 2A000897) canlıya girince aynı yola alındı.
# t_account._event_eur + runway._event_eur/_compute_start_eur + eur_balances.to_eur
# dördü de bu kümeyi kullanır (tek sayı kuralı).
# Tanım `utils/fx_rates.py`'de (2026-09-01): HTTP'siz servisler (agency_finance) router paketinden
# import edemez (katman yönü kuralı) → tek kaynak utils'e taşındı, buradan yeniden dışa verilir;
# t_account / runway / eur_balances / chart `from ._helpers import CROSS_EUR_CURRENCIES` değişmez.


def _get_fx_buying(db: Session, code: str, target_date) -> float:
    """Belirli tarih için {code}/TRY alış kuru (<= en yakın gün); yoksa 1.0.

    Çağıran 1.0'ı "kur yok" sinyali olarak ele almalı (1:1 varsayımı yapılmaz).
    """
    rate = (
        db.query(ExchangeRate.forex_buying)
        .filter(ExchangeRate.currency_code == code, ExchangeRate.date <= target_date)
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    return float(rate[0]) if rate and rate[0] else 1.0



def _latest_buying(db: Session, currency_code: str) -> Optional[float]:
    """EN SON yayınlanan (birim başına) TCMB alış kuru; hiç yoksa None.

    `_get_fx_buying`'den farkı TARİH FİLTRESİ YOKLUĞUDUR: "bugünkü bakiye"
    değerlemesi ileri tarihli bir gün için de en son yayınlanan kuru kullanır
    (hafta sonu/tatilde dünkü kur). 1.0 fallback YOK — çağıran None'ı
    "kur bilinmiyor" olarak ele alır (1 TL = 1 EUR saçmalığı engellenir).
    """
    row = (
        db.query(ExchangeRate.forex_buying, ExchangeRate.unit)
        .filter(
            ExchangeRate.currency_code == currency_code,
            ExchangeRate.forex_buying.isnot(None))
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    if row and row.forex_buying:
        return float(row.forex_buying) / float(row.unit or 1)
    return None


def bank_snapshot(db: Session) -> dict:
    """ANLIK banka nakdi — hesap bazında son bakiye + toplam EUR karşılığı.

    `runway._compute_start_eur`'ün TEK KAYNAĞIdır (o fonksiyon buraya delege eder,
    2026-08-19): "Bankadaki Nakit" başlığı, runway `start_eur` ve Nakit Akım
    grafiğinin hesap şeridi aynı sayıyı gösterir. Daha önce yalnız TOPLAM
    hesaplanıyordu; grafik hesap KIRILIMI istediğinden hesaplama buraya taşındı
    ve satır satır döner (matematik birebir aynı — `total_eur` değişmedi).

    "Son bakiye" = (date, id) sırasına göre son satır — max(id) DEĞİL: sonradan
    eklenen (backfill/devir) ESKİ tarihli satır tabloda en yüksek id'yi alır ve
    bayat bakiyeyi "güncel" sanırdı (2026-07-19 bulgusu; canlı hesap 9/10'da 57
    çelişkili satır). DISTINCT ON (PostgreSQL).

    EUR çevrimi: TRY → /eurRate, EUR → aynen, USD/GBP → (bakiye × fxRate)/eurRate
    (çapraz kur, `CROSS_EUR_CURRENCIES`), diğer para birimleri → /eurRate.
    Kur yoksa hesap toplama KATILMAZ (`balance_eur=None`) — 1:1 varsayılmaz.

    HAREKETSİZ hesaplar (hiç banka işlemi yok) listede `last_balance=None` ile
    görünür ama toplama girmez — eski `_compute_start_eur` davranışıyla birebir
    (o da yalnız son-bakiyesi olan hesaplar üzerinde döngü kurardı).
    """
    accounts = db.query(BankAccount).order_by(BankAccount.bank_name, BankAccount.id).all()

    last_rows = (
        db.query(
            BankTransaction.account_id,
            BankTransaction.balance,
            BankTransaction.date)
        .filter(BankTransaction.balance.isnot(None))
        .distinct(BankTransaction.account_id)
        .order_by(
            BankTransaction.account_id,
            BankTransaction.date.desc(),
            BankTransaction.id.desc())
        .all()
    )
    last_bal = {r.account_id: float(r.balance) for r in last_rows}
    last_date = {r.account_id: r.date for r in last_rows}

    eur_rate = _latest_buying(db, "EUR")
    cross_rates = {code: _latest_buying(db, code) for code in CROSS_EUR_CURRENCIES}

    items = []
    total_eur = 0.0
    for acc in accounts:
        currency = (acc.currency or "TRY").upper()
        blocked = float(acc.blocked_amount) if acc.blocked_amount else 0.0
        raw = last_bal.get(acc.id)
        effective = None if raw is None else raw - blocked

        balance_eur = None
        if effective is not None:
            if currency == "EUR":
                balance_eur = effective
            elif currency in CROSS_EUR_CURRENCIES:
                fx_rate = cross_rates.get(currency)
                if fx_rate and eur_rate:
                    balance_eur = (effective * fx_rate) / eur_rate
            elif eur_rate:
                balance_eur = effective / eur_rate
        if balance_eur is not None:
            total_eur += balance_eur

        items.append({
            "id": acc.id,
            "bank_name": acc.bank_name,
            "account_no": acc.account_no,
            # IBAN'ın yalnız son 4 hanesi (tam IBAN grafik şeridinde gerekmez)
            "iban_tail": (acc.iban or "")[-4:] or None,
            "currency": currency,
            "is_active": bool(acc.is_active),
            "last_balance": None if raw is None else round(raw, 2),
            "blocked_amount": round(blocked, 2),
            "effective_balance": None if effective is None else round(effective, 2),
            "balance_eur": None if balance_eur is None else round(balance_eur, 2),
            "last_movement_date": last_date[acc.id].isoformat() if acc.id in last_date else None,
        })

    return {
        "accounts": items,
        "total_eur": round(total_eur, 2),
        "eur_rate": eur_rate,
    }
