"""Düzenli ödeme (recurring) ↔ cari (satıcı) senkronizasyonu.

Cari'ye bağlı (`ScheduledDefinition.vendor_id`) düzenli ödeme tanımlarının aylık
girişlerini, ilgili carinin GERÇEK aylık faturası (alacak) + FIFO ödeme durumuyla
senkronlar. Örnek: "2026 Elektrik" → CK AKDENİZ ELEKTRİK, "2026 Su" → ASAT.

Senkronlanan ay (carinin o ay faturası var) için:
  - ``entry.amount``           = carinin o aydaki toplam faturası (tahminin yerine GERÇEK)
  - ``entry.is_paid``          = cari net-borç FIFO'ya göre o ayın faturası tamamen kapandıysa True
  - ``entry.synced_from_cari`` = True
  - **recurring finance_event SİLİNİR** — cari ``vendor_payment`` olayı zaten nakit akımı
    temsil ettiğinden, recurring tahminini de bırakmak ÇİFT SAYIM olur.

Faturası gelmemiş (gelecek) aylar **tahmini** kalır; finance_event'leri korunur (nakit
akım projeksiyonu). Daha önce senkronlanmış bir ay faturasını kaybederse tahmine döner.
"""
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.models.vendor_transaction import VendorTransaction
from app.utils.audit import log_action
from app.utils.finance_event_service import finance_event_svc
from app.utils.vendor_fifo import calculate_fifo_amounts

logger = logging.getLogger(__name__)

_EPS = 0.01


def sync_recurring_from_vendors(db: Session, source_type: str = "recurring") -> dict:
    """Cari-bağlı düzenli ödeme girişlerini cari gerçek fatura + ödeme durumuyla senkronla.

    Commit ETMEZ — çağıran commit eder. ``db.flush()`` ile değişiklikler oturuma yazılır.
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
    fifo_unpaid = calculate_fifo_amounts(db)  # dict[vtx_id → ödenmemiş tutar]

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
        month_map = {}  # (year, month) → {"total": fatura, "unpaid": ödenmemiş}
        for vtx_id, dt, alacak in rows:
            key = (dt.year, dt.month)
            m = month_map.setdefault(key, {"total": 0.0, "unpaid": 0.0})
            m["total"] += float(alacak or 0)
            m["unpaid"] += float(fifo_unpaid.get(vtx_id, 0.0))

        synced = 0
        for entry in defn.entries.all():
            actual = month_map.get((entry.period_year, entry.period_month))
            if actual and actual["total"] > _EPS:
                # Faturası gelmiş ay → GERÇEK tutara + cari ödeme durumuna senkronla
                new_amount = round(actual["total"], 2)
                is_paid = actual["unpaid"] < _EPS  # o ayın tüm faturaları kapandıysa ödendi
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
                    # Cari nakit akımı temsil eder → recurring FE'yi kaldır (çift sayım önleme)
                    finance_event_svc.invalidate(db, entry.source_type, entry.id)
                    synced += 1
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
