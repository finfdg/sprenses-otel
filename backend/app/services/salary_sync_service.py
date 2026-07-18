"""Maaş tahmini ↔ Sedna bordro (335) senkronu — domain servis katmanı (HTTP'siz çekirdek).

Kullanıcı isteği (2026-07-18): hr.salary planlı girişleri elle tahminle giriliyordu;
muhasebe bordroyu Sedna'ya işleyince tahmin OTOMATİK gerçek tahakkuka güncellensin.

Kural:
- Kaynak: Sedna 335 (Personele Borçlar) AYLIK TAHAKKUK toplamı (alacak) — o ayın
  gerçek personel maliyeti. Ödeme (borç) toplamı kullanılmaz; ödeme kanıtı banka
  eşleştirmesinden gelir (matching_service._match_scheduled_to_bank).
- Yalnız ÖDENMEMİŞ ve AYI TAMAMLANMIŞ dönemler güncellenir: gelecek ayların
  mevsimsel elle tahminlerine DOKUNULMAZ (kullanıcı yaz/kış farkını elle kurguladı);
  ödenmiş dönemlerin tutarı banka kanıtıyla zaten kesinleşmiştir.
- Kısmi-ay koruması: dönem bitmiş olsa da bordro fişi henüz işlenmemişse 335
  alacağı yalnız küçük kalemlerden (avans/icra) oluşur — tahakkuk mevcut tahminin
  %40'ının altındaysa "bordro işlenmemiş" sayılır, güncelleme atlanır (sonraki
  senkron koşusunda bordro işlenince güncellenir).

recurring_vendor_sync deseninin maaşa uyarlamasıdır (orada kaynak cari faturası,
burada Sedna 335 tahakkuku).
"""
import json
import logging
from calendar import monthrange
from datetime import date, datetime
from typing import Optional

import pytz
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.utils.audit import log_action
from app.utils.finance_event_service import finance_event_svc
from app.utils.sedna_client import SednaUnavailable, fetch_personnel_payroll

logger = logging.getLogger(__name__)

_TZ_ISTANBUL = pytz.timezone("Europe/Istanbul")

# Tahakkuk, mevcut tahminin bu oranının altındaysa bordro henüz işlenmemiş kabul edilir
# (ay ortası 335 alacağı yalnız avans/icra kalemleridir — canlı örnek: Temmuz ortasında
# 224K'lık kısmi alacak vs 12M'lik bordro).
MIN_ACCRUAL_RATIO = 0.4


def _period_complete(period_year: int, period_month: int, today: date) -> bool:
    """Dönem ayı bitti mi (İstanbul bugününe göre)."""
    last_day = monthrange(period_year, period_month)[1]
    return date(period_year, period_month, last_day) < today


def sync_salary_from_sedna(db: Session, payroll: Optional[list] = None,
                           today: Optional[date] = None) -> dict:
    """Ödenmemiş, ayı tamamlanmış maaş girişlerinin tutarını Sedna tahakkukuna çek.

    Commit ETMEZ — çağıran commit eder. ``payroll``: hazır fetch_personnel_payroll()
    sonucu (test edilebilirlik); ``today``: test edilebilirlik.
    """
    if payroll is None:
        payroll = fetch_personnel_payroll()
    today = today or datetime.now(_TZ_ISTANBUL).date()

    # {'2026-06': tahakkuk} — Decimal → float
    accruals = {}
    for row in payroll:
        ay = (row.get("ay") or "").strip()
        if ay:
            accruals[ay] = float(row.get("tahakkuk") or 0)

    entries = (
        db.query(ScheduledEntry)
        .join(ScheduledDefinition, ScheduledEntry.definition_id == ScheduledDefinition.id)
        .filter(
            ScheduledEntry.source_type == "salary",
            ScheduledEntry.is_paid.is_(False),
            ScheduledDefinition.is_active.is_(True),
        )
        .all()
    )

    updated, skipped_no_accrual, details = 0, 0, []
    for entry in entries:
        if not _period_complete(entry.period_year, entry.period_month, today):
            continue  # dönem sürüyor — elle tahmine dokunma
        accrual = accruals.get(f"{entry.period_year}-{entry.period_month:02d}", 0.0)
        old_amount = float(entry.amount or 0)
        if accrual <= 0 or (old_amount > 0 and accrual < old_amount * MIN_ACCRUAL_RATIO):
            skipped_no_accrual += 1
            continue  # bordro henüz işlenmemiş (yalnız avans/icra kalemleri)
        new_amount = round(accrual, 2)
        if abs(new_amount - old_amount) < 0.01:
            continue
        entry.amount = new_amount
        db.flush()
        finance_event_svc.upsert_scheduled_entry(db, entry, direction=-1)
        updated += 1
        details.append({
            "entry_id": entry.id,
            "period": f"{entry.period_year}-{entry.period_month:02d}",
            "old": old_amount,
            "new": new_amount,
        })
        logger.info("Maaş tahmini Sedna tahakkukuna güncellendi: dönem %s-%02d %s → %s",
                    entry.period_year, entry.period_month, old_amount, new_amount)

    return {
        "entries_checked": len(entries),
        "entries_updated": updated,
        "entries_skipped_no_accrual": skipped_no_accrual,
        "details": details,
    }


def run_salary_sedna_sync(db: Session, current_user, ip: Optional[str] = None) -> dict:
    """Servis sarmalı — merkezi Sedna sync adımı çağırır. Commit eder, audit'ler.

    Tünel kapalı/yapılandırılmamış → 503 (adım izolasyonu bilinen durum olarak ele alır).
    """
    try:
        result = sync_salary_from_sedna(db)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if result["entries_updated"]:
        log_action(
            db, current_user.id, "update", "salary_sedna_sync", None,
            json.dumps({
                "entries_updated": result["entries_updated"],
                "details": result["details"],
            }, ensure_ascii=False),
            ip,
        )
    db.commit()
    return result
