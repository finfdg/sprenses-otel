"""Planlı gelir/gider (scheduled) domain servis katmanı — tanım/giriş mutasyonları (HTTP'siz).

D1-2 (2026-06-22): 8 modülün (vergi/düzenli-ödeme/kira×2/temettü/maaş/stopaj/sgk) planlı
tanım+giriş mutasyon mantığı TEK kaynakta. Hem fabrika router'ı (`scheduled_base.create_scheduled_router`)
hem onay executor handler'ı (`_handle_scheduled`) AYNI fonksiyonları çağırır → sapma engellenir.

Kapatılan sapma: eski executor `create` yolu **`sync_recurring_from_vendors`'u atlıyordu** (router
çağırıyordu) → onaylanan cari-bağlı düzenli ödeme gerçek faturayla senkronlanmıyordu; ayrıca fallback
build'i `vendor_id`/`billing_offset_months`'u set etmiyordu.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.utils.entry_generator import _build_description, generate_entries, regenerate_entries
from app.utils.finance_event_service import finance_event_svc
from app.utils.recurring_vendor_sync import sync_recurring_from_vendors

# Bu alanlar değişince planlı girişler yeniden üretilir
_REGEN_FIELDS = ("amount", "frequency", "payment_day", "start_month")


def post_create(db: Session, defn: ScheduledDefinition, direction: int) -> list:
    """Tanım eklenip flush'landıktan SONRA: girişleri üret + cari-bağlıysa gerçek faturayla senkronla.
    Döner: üretilen girişler. Router (create_definition) ve executor (create) ORTAK çağırır."""
    entries = generate_entries(db, defn, direction=direction)
    if defn.vendor_id:
        sync_recurring_from_vendors(db)
    return entries


def apply_definition_update(db: Session, defn: ScheduledDefinition, update_data: dict, direction: int) -> dict:
    """Tanım alanlarını uygula → tutar/dönem değiştiyse girişleri yeniden üret → cari-bağlıysa senkronla.
    Döner: changes sözlüğü ({field: {old, new}}); boşsa yan etki yapılmaz (router erken döner)."""
    changes: dict = {}
    need_regenerate = False
    for field, value in update_data.items():
        if field.startswith("_"):
            continue
        if field == "vendor_id" and not value:
            value = None  # 0/None → cari bağlantısını kaldır
        if not hasattr(defn, field):
            continue
        old_val = getattr(defn, field)
        if old_val != value:
            changes[field] = {"old": str(old_val), "new": str(value)}
            setattr(defn, field, value)
            if field in _REGEN_FIELDS:
                need_regenerate = True
    if not changes:
        return changes
    if need_regenerate:
        regenerate_entries(db, defn, direction=direction)
    if defn.vendor_id:
        sync_recurring_from_vendors(db)
    return changes


def apply_entry_update(db: Session, entry: ScheduledEntry, update_data: dict, direction: int) -> dict:
    """Giriş alanlarını uygula + ödendi→paid_date + dönem değişince açıklamayı yeniden üret + finance_event.
    Döner: changes sözlüğü; boşsa yan etki yapılmaz."""
    changes: dict = {}
    for field, value in update_data.items():
        if field.startswith("_"):
            continue
        old_val = getattr(entry, field)
        if old_val != value:
            changes[field] = {"old": str(old_val), "new": str(value)}
            setattr(entry, field, value)
    if not changes:
        return changes
    if update_data.get("is_paid") and not entry.paid_date:
        entry.paid_date = date.today()
    if "period_month" in changes or "period_year" in changes:
        entry.description = _build_description(
            entry.source_type, entry.definition.name, entry.definition.category,
            entry.period_month, entry.period_year,
        )
    finance_event_svc.upsert_scheduled_entry(db, entry, direction=direction)
    return changes


def delete_definition(db: Session, defn: ScheduledDefinition) -> None:
    """Tanımın tüm girişlerinin finance_event'lerini invalidate et + tanımı sil (CASCADE girişleri siler)."""
    for entry in defn.entries.all():
        finance_event_svc.invalidate(db, entry.source_type, entry.id)
    db.delete(defn)
