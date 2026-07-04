"""Nakit Akım T Hesap Cetveli — dönem bazlı giriş/çıkış gruplaması (EUR).

Panel yeniden tasarımındaki T-hesap görünümü için: seçilen dönemdeki
(gün/hafta/ay/yıl) eşleşmemiş finance_events kayıtları giriş (direction=+1)
ve çıkış (direction=-1) sütunlarına ayrılır, kaynak/kategori bazında
gruplanır ve tüm tutarlar o günkü TCMB EUR satış kuruyla EUR'a çevrilir.

Transfer kategorileri (Virman / Döviz Satım / İade) frontend `groupByMonth`
ile aynı kuralla tamamen hariç tutulur — bunlar hesaplar arası iç hareket
olduğundan gerçek giriş/çıkış değildir.
"""

import calendar
from datetime import date as date_cls
from datetime import timedelta
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import RateLimiter
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    SOURCE_BANK,
    FinanceEvent,
)
from app.models.user import User
from app.utils.finance_helpers import MIN_DATE

# Transfer kategorileri — frontend groupByMonth (TRANSFER_CATEGORIES) ile birebir aynı
TRANSFER_CATEGORIES = ("Virman", "Döviz Satım", "İade")

# Grup başına yanıtta dönecek en fazla kalem (item_count gerçek sayıyı taşır)
MAX_ITEMS_PER_GROUP = 100

# Banka dışı kaynaklar için sabit Türkçe grup etiketleri
# (bank → category_name ile gruplanır, bilinmeyen kaynak → source_type)
SOURCE_LABELS = {
    "check": "Verilen Çekler",
    "credit": "Kredi / Leasing Taksitleri",
    "cc_payment": "KK Borç Ödemeleri",
    "vendor_payment": "Cari Ödemeleri",
    "advance": "Avanslar",
    "tax": "Vergiler",
    "recurring": "Düzenli Ödemeler",
    "salary": "Maaş",
    "withholding": "Stopaj",
    "sgk": "SGK",
    "dividend": "Temettü",
    "rent_expense": "Verilen Kiralar",
    "rent_income": "Alınan Kiralar",
}

UNTAGGED_LABEL = "Etiketsiz"

# Tarih gezgini ok tıklamaları art arda istek üretir — heavy_limiter (10/dk) gezinmeyi
# boğuyordu (12 ay geriye = 12 istek); okuma-ağırlıklı bu endpoint için daha geniş pencere
taccount_limiter = RateLimiter(max_requests=30, window_seconds=60)

router = APIRouter()


def _period_range(period: str, offset: int, today: date_cls) -> Tuple[date_cls, date_cls]:
    """Dönem başlangıç/bitiş tarihleri — Europe/Istanbul bugününe göre.

    offset=0 içinde bulunulan dönem; negatif değer dönem birimi kadar geçmiş.
    weekly: Pazartesi–Pazar; monthly: takvim ayı (calendar.monthrange).
    """
    if period == "daily":
        d = today + timedelta(days=offset)
        return d, d
    if period == "weekly":
        monday = today - timedelta(days=today.weekday())
        start = monday + timedelta(weeks=offset)
        return start, start + timedelta(days=6)
    if period == "monthly":
        total = today.year * 12 + (today.month - 1) + offset
        year, month0 = divmod(total, 12)
        month = month0 + 1
        last_day = calendar.monthrange(year, month)[1]
        return date_cls(year, month, 1), date_cls(year, month, last_day)
    # yearly
    year = today.year + offset
    return date_cls(year, 1, 1), date_cls(year, 12, 31)


def _eur_rate_for(db: Session, dt: date_cls, cache: Dict[date_cls, Optional[float]]) -> Optional[float]:
    """dt tarihindeki (<= en yakın) TCMB EUR satış kuru; hiç kur yoksa None.

    Tek istekte en çok birkaç yüz farklı tarih olduğundan basit sorgu + dict
    cache yeterli (eur_balances'taki bisect-cache burada gereksiz karmaşıklık).
    """
    if dt not in cache:
        row = (
            db.query(ExchangeRate.forex_selling, ExchangeRate.unit)
            .filter(
                ExchangeRate.currency_code == "EUR",
                ExchangeRate.date <= dt,
                ExchangeRate.forex_selling.isnot(None),
            )
            .order_by(ExchangeRate.date.desc())
            .first()
        )
        if row and row.forex_selling:
            cache[dt] = float(row.forex_selling) / float(row.unit or 1)
        else:
            cache[dt] = None
    return cache[dt]


def _event_eur(db: Session, fe: FinanceEvent, cache: Dict[date_cls, Optional[float]]) -> Optional[float]:
    """Kalemi EUR'a çevir; çevrilemiyorsa None (çağıran skipped_no_rate sayar).

    EUR kalem → amount aynen; diğerleri → TRY değeri / o tarihteki EUR kuru.
    TRY değeri: amount_try, yoksa currency TRY ise amount. Kur ya da TRY
    değeri bilinemiyorsa kalem 1 TL = 1 EUR gibi saçma bir varsayımla
    ÇEVRİLMEZ — dışarıda bırakılır.
    """
    currency = (fe.currency or "TRY").upper()
    if currency == "EUR":
        return float(fe.amount)

    if fe.amount_try is not None:
        try_value = float(fe.amount_try)
    elif currency in ("TRY", "TL"):
        try_value = float(fe.amount)
    else:
        return None  # döviz kalem, TRY karşılığı bilinmiyor

    rate = _eur_rate_for(db, fe.event_date, cache)
    if not rate:
        return None
    return try_value / rate


def _group_label(fe: FinanceEvent) -> str:
    """Grup etiketi: banka → kategori adı (yoksa Etiketsiz), diğerleri sabit etiket."""
    if fe.source_type == SOURCE_BANK:
        return fe.category_name or UNTAGGED_LABEL
    return SOURCE_LABELS.get(fe.source_type, fe.source_type)


def _item_name(fe: FinanceEvent) -> str:
    """Kalem adı: açıklama → banka adı → çek no → kaynak etiketi."""
    return (
        (fe.description or "").strip()
        or (fe.bank_name or "").strip()
        or (fe.check_no or "").strip()
        or _group_label(fe)
    )


@router.get("/cash-flow/t-account")
def t_account(
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|yearly)$"),
    offset: int = Query(0, le=0, ge=-120, description="0=bu dönem, negatif=geçmiş dönem"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Dönem bazlı T hesap cetveli — giriş/çıkış grupları, EUR karşılıklarıyla."""
    taccount_limiter.check(f"cashflow-taccount-{current_user.id}")

    start, end = _period_range(period, offset, date_cls.today())

    events = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.is_matched == False,
            FinanceEvent.event_date >= MIN_DATE,
            FinanceEvent.event_date >= start,
            FinanceEvent.event_date <= end,
            # NULL kategori NOT IN'de UNKNOWN döner → or_ ile açıkça dahil edilir
            or_(
                FinanceEvent.category_name.is_(None),
                ~FinanceEvent.category_name.in_(TRANSFER_CATEGORIES),
            ),
        )
        .order_by(FinanceEvent.event_date.asc(), FinanceEvent.id.asc())
        .all()
    )

    groups = {DIRECTION_INCOME: {}, DIRECTION_EXPENSE: {}}
    totals = {DIRECTION_INCOME: 0.0, DIRECTION_EXPENSE: 0.0}
    skipped_no_rate = 0
    rate_cache: Dict[date_cls, Optional[float]] = {}

    for fe in events:
        if fe.direction not in groups:
            continue
        eur = _event_eur(db, fe, rate_cache)
        if eur is None:
            skipped_no_rate += 1
            continue

        label = _group_label(fe)
        group = groups[fe.direction].setdefault(
            label, {"label": label, "total_eur": 0.0, "item_count": 0, "items": []}
        )
        group["total_eur"] += eur
        group["item_count"] += 1
        if len(group["items"]) < MAX_ITEMS_PER_GROUP:
            group["items"].append({
                "name": _item_name(fe),
                "date": fe.event_date.isoformat(),
                "amount_eur": round(eur, 2),
            })
        totals[fe.direction] += eur

    def _finalize(direction: int) -> list:
        result = list(groups[direction].values())
        for g in result:
            g["total_eur"] = round(g["total_eur"], 2)
        result.sort(key=lambda g: g["total_eur"], reverse=True)
        return result

    total_in = round(totals[DIRECTION_INCOME], 2)
    total_out = round(totals[DIRECTION_EXPENSE], 2)

    return {
        "period": period,
        "offset": offset,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "giris": _finalize(DIRECTION_INCOME),
        "cikis": _finalize(DIRECTION_EXPENSE),
        "total_in_eur": total_in,
        "total_out_eur": total_out,
        "net_eur": round(total_in - total_out, 2),
        "skipped_no_rate": skipped_no_rate,
    }
