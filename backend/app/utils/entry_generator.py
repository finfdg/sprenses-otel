"""Planlı gider giriş üretici — tanımdan aylık/dönemsel girişler oluşturur.

Kullanım:
    from app.utils.entry_generator import generate_entries, regenerate_entries

    entries = generate_entries(db, definition)
    regenerate_entries(db, definition)  # ödenmemiş eski girişleri sil, yeniden üret
"""
import logging
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.utils.finance_event_service import finance_event_svc

logger = logging.getLogger(__name__)

# Açıklama ön ekleri
DESC_PREFIX = {
    "tax": "Vergi",
    "recurring": "Düzenli Ödeme",
    "salary": "Maaş",
    "withholding": "Stopaj",
    "rent_income": "Alınan Kira",
    "rent_expense": "Verilen Kira",
    "sgk": "SGK",
    "dividend": "Temettü",
}

# Türkçe ay isimleri (period_month 1-12 için)
MONTH_NAMES_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def _build_description(source_type: str, defn_name: str, category: Optional[str], period_month: int, period_year: int) -> str:
    """Nakit akımda görünen açıklama — dönem bilgisi dahil."""
    prefix = DESC_PREFIX.get(source_type, "Gider")
    period = f"{MONTH_NAMES_TR[period_month - 1]} {period_year}"
    category_part = f" - {category}" if category else ""
    return f"[{prefix}] {period} — {defn_name}{category_part}"

# Bu kaynak tipler için: dönemin ödemesi bir sonraki ayın ilgili gününde yapılır
# (ör. Nisan maaşı 5 Mayıs'ta ödenir). period_month dönemin ayıdır,
# entry_date ise +1 ay kaymış gerçek ödeme tarihidir.
SHIFT_NEXT_MONTH_SOURCES = {"salary", "sgk", "withholding"}


def _payment_date(source_type: str, period_year: int, period_month: int, payment_day: int,
                  pay_next_month: bool = False) -> date:
    """Dönem ay/yıl ve payment_day'den gerçek ödeme tarihini hesapla.

    salary/sgk/withholding kaynak-bazlı VEYA tanımın `pay_next_month` bayrağı True ise +1 ay
    kaydırılır (ör. Ocak dönemi → 10 Şubat); aksi halde aynı ay kullanılır.
    """
    day = min(payment_day, 28)
    if pay_next_month or source_type in SHIFT_NEXT_MONTH_SOURCES:
        if period_month == 12:
            return date(period_year + 1, 1, day)
        return date(period_year, period_month + 1, day)
    return date(period_year, period_month, day)


def _period_months(
    frequency: str,
    start_month: int,
) -> List[int]:
    """Verilen frekans ve başlangıç ayına göre dönem aylarını hesapla."""
    if frequency == "monthly":
        return list(range(start_month, 13))
    if frequency == "quarterly":
        months = []
        m = start_month
        while m <= 12:
            months.append(m)
            m += 3
        return months
    if frequency == "yearly":
        return [start_month]
    return []


def generate_entries(
    db: Session,
    defn: ScheduledDefinition,
    direction: int = -1,
) -> List[ScheduledEntry]:
    """Tanımdan girişler oluştur ve finance_events'e yaz.

    Args:
        direction: -1 (gider) veya +1 (gelir). finance_events'e yazılır.

    Returns:
        Oluşturulan ScheduledEntry listesi.
    """
    period_months = _period_months(defn.frequency, defn.start_month)

    entries = []
    for m in period_months:
        pay_date = _payment_date(defn.source_type, defn.year, m, defn.payment_day, defn.pay_next_month)
        entry = ScheduledEntry(
            definition_id=defn.id,
            source_type=defn.source_type,
            entry_date=pay_date,
            period_month=m,
            period_year=defn.year,
            amount=defn.amount,
            currency=defn.currency,
            description=_build_description(defn.source_type, defn.name, defn.category, m, defn.year),
            is_paid=False,
        )
        db.add(entry)
        db.flush()

        finance_event_svc.upsert_scheduled_entry(db, entry, direction=direction)
        entries.append(entry)

    return entries


def regenerate_entries(
    db: Session,
    defn: ScheduledDefinition,
    direction: int = -1,
) -> List[ScheduledEntry]:
    """Ödenmemiş girişleri sil, yeniden oluştur. Ödenmişlere dokunma.

    Args:
        direction: -1 (gider) veya +1 (gelir). finance_events'e yazılır.

    Returns:
        Yeni oluşturulan ScheduledEntry listesi.
    """
    unpaid = (
        db.query(ScheduledEntry)
        .filter(
            ScheduledEntry.definition_id == defn.id,
            ScheduledEntry.is_paid == False,  # noqa: E712
        )
        .all()
    )
    for entry in unpaid:
        finance_event_svc.invalidate(db, entry.source_type, entry.id)
        db.delete(entry)

    db.flush()

    # Ödenen girişlerin dönemlerini al (tekrar oluşturmamak için)
    paid_periods = set(
        (py, pm) for (py, pm) in db.query(ScheduledEntry.period_year, ScheduledEntry.period_month)
        .filter(
            ScheduledEntry.definition_id == defn.id,
            ScheduledEntry.is_paid == True,  # noqa: E712
        )
        .all()
    )

    period_months = _period_months(defn.frequency, defn.start_month)

    entries = []
    for m in period_months:
        if (defn.year, m) in paid_periods:
            continue

        pay_date = _payment_date(defn.source_type, defn.year, m, defn.payment_day, defn.pay_next_month)
        entry = ScheduledEntry(
            definition_id=defn.id,
            source_type=defn.source_type,
            entry_date=pay_date,
            period_month=m,
            period_year=defn.year,
            amount=defn.amount,
            currency=defn.currency,
            description=_build_description(defn.source_type, defn.name, defn.category, m, defn.year),
            is_paid=False,
        )
        db.add(entry)
        db.flush()
        finance_event_svc.upsert_scheduled_entry(db, entry, direction=direction)
        entries.append(entry)

    return entries
