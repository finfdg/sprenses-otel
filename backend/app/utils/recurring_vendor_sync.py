"""Düzenli ödeme (recurring) ↔ cari (satıcı) senkronizasyonu.

Cari'ye bağlı (`ScheduledDefinition.vendor_id`) düzenli ödeme tanımlarının aylık
girişlerini, ilgili carinin GERÇEK aylık faturası (alacak) + FIFO ödeme durumuyla
senkronlar. Örnek: "2026 Elektrik" → CK AKDENİZ ELEKTRİK, "2026 Su" → ASAT.

NAKİT AKIM TEMSİLİ — DÜZENLİ ÖDEME TARAFI (2026-07-07, kullanıcı kararı — ESKİNİN TERSİ):
Cari-bağlı tanımlarda nakit akımı HER ZAMAN **recurring finance_event** temsil eder;
carinin `vendor_payment` FE'leri hiç üretilmez (bkz. `sync_vendor_fifo` — bağlı cariler
atlanır). Eski tasarım faturalı ayda cari FE'yi bırakıp recurring FE'yi siliyordu; bu,
(a) kalemin nakit akımda "Cari Ödemeleri" altında görünmesine (kullanıcı Düzenli
Ödemeler'den takip etmek istiyor), (b) FE'yi yeniden yazan diğer akışlarla (generate/
regenerate/entry update) yarışıp ÇİFT SAYIMA (ör. Su Haziran 2026: hem recurring hem
vendor FE) yol açıyordu.

Senkron kuralları (fatura ayı = tüketim ayı + `billing_offset_months`):
  - **Fatura ayı KAPANMIŞ** (bugün fatura ayından sonraki ayda/ötesinde) veya gelen
    faturalar tahmini AŞMIŞSA → ``entry.amount`` = gerçek fatura toplamı,
    ``entry.is_paid`` = FIFO'ya göre tamamı kapandı mı.
  - **Fatura ayı AÇIK + gelen toplam tahminin ALTINDA** (ara/ek fatura — ör. Temmuz
    başında gelen 1.029 TL'lik ek elektrik faturası) → tahmin KORUNUR (aylık plan
    çökertilmez); FE tutarı = FIFO kalanı + (tahmin − gelen) → projeksiyon plan
    seviyesinde kalır, gelen kısmın ödenen bölümü düşer.
  - **FE zorlaması her turda (idempotent):** ödendi → FE silinir (banka hareketi
    gerçeği temsil eder); ödenmedi → FE upsert (tutar = yukarıdaki kalan). Başka bir
    akış FE'yi yeniden yaratsa/silse bile bir sonraki senkron durumu düzeltir.
  - Faturası gelmemiş ay **tahmini** kalır (FE = tahmin, `entry_generator` üretimi);
    daha önce senkronlanmış ay faturasını kaybederse tahmine döner.
"""
import json
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.models.vendor_transaction import VendorTransaction
from app.utils.audit import log_action
from app.utils.finance_event_service import finance_event_svc
from app.utils.vendor_fifo import calculate_fifo_amounts

logger = logging.getLogger(__name__)

_EPS = 0.01


def _shift_period(d, offset_months: int):
    """Fatura tarihini `offset_months` ay GERİYE kaydırıp (yıl, ay) döner.

    Tüketim ayı = fatura ayı − gecikme. Su faturası ay başında gelir (önceki ay tüketimi) → offset=1:
    3 Haz faturası → (2026, 5) Mayıs. Elektrik ay sonu faturalanır → offset=0: aynı ay.
    """
    idx = d.year * 12 + (d.month - 1) - (offset_months or 0)
    return (idx // 12, idx % 12 + 1)


def sync_recurring_from_vendors(
    db: Session,
    source_type: str = "recurring",
    fifo: Optional[dict] = None,
    today: Optional[date] = None,
) -> dict:
    """Cari-bağlı düzenli ödeme girişlerini cari gerçek fatura + ödeme durumuyla senkronla.

    Commit ETMEZ — çağıran commit eder. ``db.flush()`` ile değişiklikler oturuma yazılır.
    ``fifo``: hazır FIFO sonucu (``calculate_fifo_amounts``) — ``sync_vendor_finance_events``
    zincirinden çağrılırken yeniden hesaplamamak için. ``today``: test edilebilirlik.
    """
    defs = (
        db.query(ScheduledDefinition)
        .filter(
            ScheduledDefinition.source_type == source_type,
            ScheduledDefinition.vendor_id.isnot(None),
            ScheduledDefinition.is_active.is_(True),
        )
        .all()
    )
    if not defs:
        return {"definitions": 0, "entries_synced": 0, "details": []}

    # Carinin her faturasının (vtx) FIFO sonrası ödenmemiş tutarı — ödeme durumu için.
    if fifo is None:
        fifo = calculate_fifo_amounts(db)  # dict[vtx_id → ödenmemiş tutar]
    today = today or date.today()
    today_idx = today.year * 12 + (today.month - 1)

    details = []
    total_synced = 0
    for defn in defs:
        # Carinin aylık faturaları (alacak) + o aydaki ödenmemiş (FIFO) toplam
        rows = (
            db.query(VendorTransaction.id, VendorTransaction.date, VendorTransaction.alacak)
            .filter(
                VendorTransaction.vendor_id == defn.vendor_id,
                VendorTransaction.alacak > 0,
                VendorTransaction.date.isnot(None),
            )
            .all()
        )
        # Fatura → TÜKETİM ayı (gecikme kadar geri kaydır). Su: ay başı faturası = önceki ay tüketimi.
        offset = defn.billing_offset_months or 0
        estimate = float(defn.amount)
        month_map = {}  # (year, month) tüketim dönemi → {"total": fatura, "unpaid": ödenmemiş}
        for vtx_id, dt, alacak in rows:
            key = _shift_period(dt, offset)
            m = month_map.setdefault(key, {"total": 0.0, "unpaid": 0.0})
            m["total"] += float(alacak or 0)
            m["unpaid"] += float(fifo.get(vtx_id, 0.0))

        synced = 0
        for entry in defn.entries.all():
            actual = month_map.get((entry.period_year, entry.period_month))
            if actual and actual["total"] > _EPS:
                invoiced = round(actual["total"], 2)
                unpaid = round(actual["unpaid"], 2)
                # Fatura ayı (tüketim + offset) bitti mi? Bitmeden gelen ve tahmini aşmayan
                # toplam = ara/ek fatura → aylık plan korunur (tahmin çökertilmez).
                period_idx = entry.period_year * 12 + (entry.period_month - 1)
                bill_month_open = today_idx <= period_idx + offset
                if bill_month_open and invoiced < estimate - _EPS:
                    new_amount = estimate
                    fe_amount = round(unpaid + (estimate - invoiced), 2)
                    is_paid = False
                else:
                    new_amount = invoiced
                    fe_amount = unpaid
                    is_paid = unpaid < _EPS
                changed = (
                    abs(float(entry.amount) - new_amount) > _EPS
                    or bool(entry.is_paid) != is_paid
                    or not entry.synced_from_cari
                )
                if changed:
                    entry.amount = new_amount
                    entry.is_paid = is_paid
                    entry.paid_date = entry.entry_date if is_paid else None
                    entry.synced_from_cari = True
                    synced += 1
                # FE durumu HER turda zorlanır (idempotent): başka akışlar (generate/
                # regenerate/entry update) FE'yi yeniden yazabilir — senkron düzeltir.
                if is_paid:
                    # Ödenen ayın nakit akımını banka hareketi temsil eder → FE kalkar
                    finance_event_svc.invalidate(db, entry.source_type, entry.id)
                else:
                    fe = finance_event_svc.upsert_scheduled_entry(db, entry, direction=-1)
                    if fe is not None and abs(float(fe.amount) - fe_amount) > _EPS:
                        fe.amount = fe_amount  # kalan borç (entry.amount değil)
            elif entry.synced_from_cari:
                # Önceden senkronlanmış ama faturası artık yok (silinmiş) → tahmine geri dön
                entry.amount = float(defn.amount)
                entry.is_paid = False
                entry.paid_date = None
                entry.synced_from_cari = False
                finance_event_svc.upsert_scheduled_entry(db, entry, direction=-1)
                synced += 1

        total_synced += synced
        details.append({
            "definition_id": defn.id,
            "name": defn.name,
            "vendor_id": defn.vendor_id,
            "vendor_name": defn.vendor.hesap_adi if defn.vendor else None,
            "synced": synced,
        })

    db.flush()
    return {"definitions": len(defs), "entries_synced": total_synced, "details": details}


def run_recurring_vendor_sync(db: Session, current_user, ip: Optional[str] = None) -> dict:
    """Servis sarmalı — merkezi Sedna sync adımı + elle endpoint çağırır. Commit eder, audit'ler."""
    result = sync_recurring_from_vendors(db)
    if result["entries_synced"]:
        log_action(
            db, current_user.id, "update", "recurring_vendor_sync", None,
            json.dumps({
                "definitions": result["definitions"],
                "entries_synced": result["entries_synced"],
                "details": result["details"],
            }, ensure_ascii=False),
            ip,
        )
    db.commit()
    return result
