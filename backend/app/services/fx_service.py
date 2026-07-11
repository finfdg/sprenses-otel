"""Kur servisi — Sedna-eşdeğer defter kuru + kur farkı kayıtları + aylık değerleme.

Canlı doğrulama (2026-07-11 Sedna incelemesi):
- Sedna fiş kurları ve ay sonu değerlemesi TCMB **döviz ALIŞ (Buying)** kullanır.
- Tarih semantiği 1 gün kayık: Sedna ExchangeRate(G).Buying == bizim exchange_rates(G−1).
  forex_buying (Sedna "geçerlilik", biz "yayın" tarihi — tüm Temmuz satırlarında birebir).
→ `ledger_rate(value_date)` = bizim (value_date − 1 gün) satırının forex_buying'i (yoksa en
yakın ÖNCEKİ gün — hafta sonu taşıması Sedna ile aynı hizaya gelir).

Kur farkı kayıtları (`fx_differences`) Sedna 646 (kambiyo karı) / 656 (zararı) eşleniğidir;
**finance_events'e kalem YAZILMAZ** (nakit hareketi değil — kullanıcı kararı 2026-07-11,
aylık değerleme RAPOR katmanında kalır).
"""
import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.models import BankAccount, BankTransaction
from app.models.event_match import FxDifference
from app.models.exchange_rate import ExchangeRate

logger = logging.getLogger(__name__)

# fx_differences.source değerleri (DB-saklı)
FX_SOURCE_MATCH = "match"            # çapraz-para eşleşmeden doğan fark
FX_SOURCE_REVALUATION = "revaluation"  # aylık değerleme kaydı

_SEDNA_TO_LOCAL_CCY = {"TL": "TRY"}


def ledger_rate(db: Session, value_date: date, currency: str) -> Optional[float]:
    """Sedna-eşdeğer defter kuru: (value_date − 1) tarihli TCMB döviz ALIŞ (yoksa en yakın önceki).

    TRY/TL → 1.0. Kur bulunamazsa None (çağıran karar verir — sessiz 0 üretme).
    """
    ccy = _SEDNA_TO_LOCAL_CCY.get((currency or "TRY").upper(), (currency or "TRY").upper())
    if ccy == "TRY":
        return 1.0
    row = (
        db.query(ExchangeRate.forex_buying, ExchangeRate.unit)
        .filter(
            ExchangeRate.currency_code == ccy,
            ExchangeRate.date <= value_date - timedelta(days=1),
            ExchangeRate.forex_buying.isnot(None),
        )
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    if not row or not row.forex_buying:
        return None
    return float(row.forex_buying) / float(row.unit or 1)


def record_match_fx_diff(
    db: Session,
    *,
    event_match_id: Optional[int],
    period: date,
    direction: int,
    fx_amount: float,
    fx_currency: str,
    estimate_date: date,
    realized_try: float,
    description: Optional[str] = None,
) -> Optional[FxDifference]:
    """Çapraz-para eşleşmede kur farkı kaydı (646/656 eşleniği; FE'ye YAZILMAZ).

    amount_try işaretli: + = kambiyo KARI, − = ZARARI.
    Gider (direction=-1): beklenenden AZ TL ödemek kar. Gelir (+1): FAZLA TL almak kar.
    Kur/veri eksikse None döner (eşleşmeyi asla bozmaz).
    """
    try:
        rate_est = ledger_rate(db, estimate_date, fx_currency)
        if not rate_est or fx_amount <= 0 or realized_try <= 0:
            return None
        expected_try = round(fx_amount * rate_est, 2)
        realized_try = round(realized_try, 2)
        if direction < 0:
            amount_try = round(expected_try - realized_try, 2)
        else:
            amount_try = round(realized_try - expected_try, 2)
        rec = FxDifference(
            event_match_id=event_match_id,
            period=period,
            amount_try=amount_try,
            rate_estimate=rate_est,
            rate_realized=round(realized_try / fx_amount, 6),
            expected_try=expected_try,
            realized_try=realized_try,
            source=FX_SOURCE_MATCH,
            description=(description or "")[:300] or None,
        )
        db.add(rec)
        db.flush()
        return rec
    except Exception as e:  # kur farkı kaydı eşleşmeyi asla düşürmesin
        logger.error("Kur farkı kaydı yazılamadı: %s", e)
        return None


def compute_monthly_revaluation(
    db: Session,
    year: int,
    month: int,
    fetch_valuation: Optional[Callable[[List[str], int, int], dict]] = None,
) -> dict:
    """Aylık kur değerlemesi raporu — bizim hesap ↔ Sedna Type=4 fişi yan yana.

    Kapsam: Sedna koduna eşlenmiş (onaylı) DÖVİZ banka hesapları. Her hesap için:
    - our_fx_balance: ay sonundaki son ekstre bakiyesi (hesap para biriminde)
    - expected_try: our_fx_balance × ay sonu ledger_rate (Sedna formülü: döviz × TCMB ALIŞ)
    - Sedna canlı: TL bakiye / döviz bakiye (ay sonuna kadar) + o ayın Type=4 değerleme satırı
    Durum: 'mutabik' (fark ≤ %0.5 veya 100 TL) / 'sapma' / 'sedna_bekliyor' (Type=4 fişi yok).
    Deftere/finance_events'e YAZMAZ — salt rapor.
    """
    if fetch_valuation is None:
        from app.utils.sedna_client import fetch_bank_fx_valuation
        fetch_valuation = fetch_bank_fx_valuation

    month_end = date(year, month, monthrange(year, month)[1])
    accounts = (
        db.query(BankAccount)
        .filter(BankAccount.is_active == True,  # noqa: E712
                BankAccount.sedna_account_code.isnot(None),
                BankAccount.sedna_code_confirmed == True,  # noqa: E712
                BankAccount.currency != "TRY")
        .all()
    )
    if not accounts:
        return {"year": year, "month": month, "items": [], "note": "Eşlenmiş döviz hesabı yok"}

    sedna = fetch_valuation([a.sedna_account_code for a in accounts], year, month)

    items = []
    for acc in accounts:
        last_tx = (
            db.query(BankTransaction)
            .filter(BankTransaction.account_id == acc.id,
                    BankTransaction.date <= month_end,
                    BankTransaction.balance.isnot(None))
            .order_by(BankTransaction.date.desc(), BankTransaction.id.desc())
            .first()
        )
        our_fx = float(last_tx.balance) if last_tx else None
        rate = ledger_rate(db, month_end + timedelta(days=1), acc.currency)  # ay sonu günü kuru
        expected_try = round(our_fx * rate, 2) if (our_fx is not None and rate) else None

        s = sedna.get(acc.sedna_account_code) or {}
        sedna_tl = s.get("tl_balance")
        sedna_fx = s.get("fx_balance")
        valuation_tl = s.get("valuation_tl")  # o ayın Type=4 düzeltme satırı toplamı (None = fiş yok)

        if valuation_tl is None:
            status = "sedna_bekliyor"  # Sedna kapanışı 1-3 ay gecikebilir — sapma SAYILMAZ
        elif expected_try is None or sedna_tl is None:
            status = "veri_eksik"
        else:
            diff = abs(expected_try - float(sedna_tl))
            status = "mutabik" if diff <= max(abs(expected_try) * 0.005, 100.0) else "sapma"

        items.append({
            "account_id": acc.id,
            "bank_name": acc.bank_name,
            "currency": acc.currency,
            "sedna_code": acc.sedna_account_code,
            "our_fx_balance": our_fx,
            "sedna_fx_balance": float(sedna_fx) if sedna_fx is not None else None,
            "rate": rate,
            "expected_try": expected_try,
            "sedna_tl_balance": float(sedna_tl) if sedna_tl is not None else None,
            "sedna_valuation_tl": float(valuation_tl) if valuation_tl is not None else None,
            "status": status,
        })

    return {"year": year, "month": month, "month_end": month_end.isoformat(), "items": items}
