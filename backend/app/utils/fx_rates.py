"""TCMB kur defteri — tarih bazlı EUR çevrimi için ortak teknik yardımcı (tek sorgu + bisect).

Neden: Acente Finans raporu binlerce hareketi kendi tarihindeki kurla çevirir; satır başına DB
sorgusu (`cash_flow/_helpers._get_fx_buying`) ağır, `eur_balances.compute_eur_balances`
içindeki inline bisect kapanışları ise yeniden kopyalanamaz (FIN-001 sınıfı drift). `RateBook`
seçilen dövizlerin TÜM geçmişini tek sorguda yükler; `rate(code, dt)` dt'ye eşit veya ÖNCEKİ
son yayını verir (hafta sonu/tatil → önceki iş günü). Kur yoksa **None** — 1 TL = 1 EUR
varsayımı YAPILMAZ; çağıran kalemi atlar ve sayar (`skipped_no_rate` deseni).

`CROSS_EUR_CURRENCIES` (USD, GBP): EUR'a ÇAPRAZ kurla çevrilen dövizler — amount × {kur} /
EUR kuru; amount_try'a bakılmaz (2026-07-19 USD kararı, 2026-08-14 GBP). Tanım burada;
`routers/finance/cash_flow/_helpers.py` yeniden dışa verir (services/ router paketinden
import edemez — katman yönü kuralı).
"""
import bisect
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.exchange_rate import ExchangeRate

CROSS_EUR_CURRENCIES = ("USD", "GBP")
_TL_CODES = ("TL", "TRY")


class RateBook:
    """Döviz kodu → tarih sıralı (tarih, birim başına TL alış) serileri; bisect ile arama."""

    def __init__(self, series: Dict[str, List[Tuple[date, float]]]):
        self._dates: Dict[str, List[date]] = {}
        self._values: Dict[str, List[float]] = {}
        for code, rows in series.items():
            rows = sorted(rows, key=lambda r: r[0])
            self._dates[code] = [r[0] for r in rows]
            self._values[code] = [r[1] for r in rows]

    @classmethod
    def load(cls, db: Session, codes: Optional[Iterable[str]] = None) -> "RateBook":
        """Seçilen dövizlerin (varsayılan: EUR + çapraz küme) tüm geçmişini tek sorguda yükle."""
        wanted = tuple(codes) if codes else ("EUR",) + CROSS_EUR_CURRENCIES
        rows = (
            db.query(ExchangeRate.currency_code, ExchangeRate.date,
                     ExchangeRate.forex_buying, ExchangeRate.unit)
            .filter(ExchangeRate.currency_code.in_(wanted),
                    ExchangeRate.forex_buying.isnot(None))
            .order_by(ExchangeRate.date)
            .all()
        )
        series: Dict[str, List[Tuple[date, float]]] = {code: [] for code in wanted}
        for code, dt, buying, unit in rows:
            value = float(buying or 0)
            if value <= 0:
                continue
            series[code].append((dt, value / float(unit or 1)))
        return cls(series)

    def rate(self, code: str, dt: date) -> Optional[float]:
        """{code}/TL alış kuru (birim başına), dt'ye eşit veya önceki son yayın; yoksa None."""
        dates = self._dates.get(code)
        if not dates:
            return None
        idx = bisect.bisect_right(dates, dt) - 1
        return self._values[code][idx] if idx >= 0 else None

    def eur(self, dt: date) -> Optional[float]:
        return self.rate("EUR", dt)

    def to_eur(self, amount: float, currency: Optional[str], dt: date) -> Optional[float]:
        """Native tutarı dt tarihindeki kurla EUR'a çevir.

        EUR → aynen · TL/TRY → amount / EUR(dt) · USD/GBP (ve yüklenmiş diğer dövizler) →
        amount × kur(dt) / EUR(dt) · gerekli kur yoksa None.
        """
        cur = (currency or "TL").strip().upper() or "TL"
        if cur == "EUR":
            return float(amount)
        eur = self.eur(dt)
        if not eur:
            return None
        if cur in _TL_CODES:
            return float(amount) / eur
        fx = self.rate(cur, dt)
        if not fx:
            return None
        return float(amount) * fx / eur
