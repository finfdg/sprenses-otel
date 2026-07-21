"""Planlı gelir/gider (scheduled) domain servis katmanı — tanım/giriş mutasyonları (HTTP'siz).

D1-2 (2026-06-22): 8 modülün (vergi/düzenli-ödeme/kira×2/temettü/maaş/stopaj/sgk) planlı
tanım+giriş mutasyon mantığı TEK kaynakta. Hem fabrika router'ı (`scheduled_base.create_scheduled_router`)
hem onay executor handler'ı (`_handle_scheduled`) AYNI fonksiyonları çağırır → sapma engellenir.

Kapatılan sapma: eski executor `create` yolu **`sync_recurring_from_vendors`'u atlıyordu** (router
çağırıyordu) → onaylanan cari-bağlı düzenli ödeme gerçek faturayla senkronlanmıyordu; ayrıca fallback
build'i `vendor_id`/`billing_offset_months`'u set etmiyordu.
"""
from sqlalchemy.orm import Session

from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.utils.entry_generator import _build_description, generate_entries, regenerate_entries
from app.utils.finance_event_service import finance_event_svc
from app.utils.recurring_vendor_sync import sync_recurring_from_vendors

# Bu alanlar değişince planlı girişler yeniden üretilir (yeni entry_date/tutar)
_REGEN_FIELDS = ("amount", "frequency", "payment_day", "start_month", "pay_next_month")


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
    if "currency" in changes:
        # Para birimi tanımın TÜM girişlerine yayılır (girişler tanım biriminde üretilir;
        # regenerate yalnız ödenmemişleri yeniden kurar, ödenmişler burada güncellenir).
        # Tutarlar DEĞİŞMEZ — sadece birim etiketi; TRY karşılığı FE/nakit-akım katmanında
        # kur çevrimiyle hesaplanır.
        for entry in defn.entries.all():
            if entry.currency != defn.currency:
                entry.currency = defn.currency
            finance_event_svc.upsert_scheduled_entry(db, entry, direction=direction)
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
        # Varsayılan ödeme tarihi = PLANLI ödeme günü (entry_date), bugün DEĞİL.
        # Geçmiş ödemeleri sonradan toplu "Ödendi" işaretlerken hepsi "bugüne" yığılmasın;
        # kalem planlandığı ay/günde nakit akımda kalır (kullanıcı isterse elle düzeltir).
        entry.paid_date = entry.entry_date
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


# Banka kanıtının tutarı girişe yalnız TAM-ödeme bandındaysa yazılır (matcher'ın
# otomatik bandıyla aynı: 0.75 ≤ |btx|/tutar ≤ 1.30). Öneri-Onayla yolu r=0.5'e kadar
# KISMİ adaya izin verir — kısmi banka bacağı planlı TOPLAMI ezmemeli (2026-07-19:
# ₺2,79M stopaj girişine ₺1M taksit yazılıp ₺1,79M sessizce kaybolurdu).
_FULL_PAYMENT_RATIO_MIN = 0.75
_FULL_PAYMENT_RATIO_MAX = 1.30


def _is_full_payment(actual: float, planned: float) -> bool:
    """Banka tutarı planlı tutarın tam-ödeme bandında mı? (planlı ≤ 0 → tutar bilinmiyor, yaz)."""
    if planned <= 0:
        return True
    return _FULL_PAYMENT_RATIO_MIN <= actual / planned <= _FULL_PAYMENT_RATIO_MAX


def _btx_amount_for_entry(db: Session, entry: ScheduledEntry, btx):
    """Banka kanıtının girişe yazılabilir tutarı — yalnız para birimleri aynıysa (TRY↔TRY).

    Döviz hesabından çıkan ödeme girişin TRY tahminini ezmemeli (kur çevirisi bu
    katmanın işi değil); o durumda None döner ve tahmin korunur.
    """
    from app.models.bank_account import BankAccount

    entry_cur = (entry.currency or "TRY").upper()
    acc = db.query(BankAccount).filter(BankAccount.id == btx.account_id).first()
    acc_cur = ((acc.currency if acc else None) or "TRY").upper()
    norm = {"TL": "TRY"}
    if norm.get(entry_cur, entry_cur) != norm.get(acc_cur, acc_cur):
        return None
    return round(abs(float(btx.amount)), 2)


def close_entry_via_bank(db: Session, entry: ScheduledEntry, btx, direction: int = -1) -> bool:
    """Banka hareketi kanıtıyla planlı girişi kapat (Faz 1 #11 köprüsü).

    Etiketleme (Vergi/SGK · Personel · Kira) banka bacağına match_number verirken
    scheduled_entry açık kalıyordu → aynı dönemde tahmin + gerçekleşen ÇİFT sayılıyordu.
    Sıra: önce upsert (FE alanları tazelenir; is_matched artık event_matches izinden
    türetilir — 2026-07-19), SONRA match (is_matched=True + event_matches izi). Yarış-korumalı.

    2026-07-18: banka kanıtı girişin TAHMİNİ tutarını da GERÇEK tutara çeker (aynı
    para birimiyse VE tam-ödeme bandındaysa — kısmi banka bacağı planlı toplamı ezmez).
    """
    from app.utils.finance_event_service import finance_event_svc

    locked = (db.query(ScheduledEntry)
              .filter(ScheduledEntry.id == entry.id, ScheduledEntry.is_paid == False)  # noqa: E712
              .with_for_update(skip_locked=True).first())
    if locked is None:
        return False
    locked.is_paid = True
    locked.paid_date = btx.date
    actual = _btx_amount_for_entry(db, locked, btx)
    if actual and actual > 0 and _is_full_payment(actual, float(locked.amount or 0)):
        locked.amount = actual
    db.flush()
    finance_event_svc.upsert_scheduled_entry(db, locked, direction=direction)
    finance_event_svc.match(db, "bank", btx.id, locked.source_type, locked.id, method="auto")
    return True


def attach_bank_to_paid_entry(db: Session, entry: ScheduledEntry, btx, direction: int = -1) -> bool:
    """Elle 'ödendi' işaretlenmiş ama bankayla EŞLEŞMEMİŞ girişi banka kanıtına bağla.

    Kullanıcı girişi UI'dan ödendi yapınca FE `is_realized=True, is_matched=False`
    kalır; banka bacağı da gerçekleşmiş olduğundan aynı ödeme ÇİFT sayılır (canlı:
    Mayıs–Temmuz maaşları). Bu fonksiyon eşleşmeyi kurar → planlı bacak toplamdan
    düşer, banka bacağı tek gerçek olur. Tutar/tarih banka kanıtına çekilir.
    """
    from app.models.finance_event import FinanceEvent
    from app.utils.finance_event_service import finance_event_svc

    locked = (db.query(ScheduledEntry)
              .filter(ScheduledEntry.id == entry.id, ScheduledEntry.is_paid == True)  # noqa: E712
              .with_for_update(skip_locked=True).first())
    if locked is None:
        return False
    fe = (db.query(FinanceEvent)
          .filter(FinanceEvent.source_type == locked.source_type,
                  FinanceEvent.source_id == locked.id).first())
    if fe is not None and fe.is_matched:
        return False  # zaten bir banka kanıtına bağlı
    locked.paid_date = btx.date
    actual = _btx_amount_for_entry(db, locked, btx)
    if actual and actual > 0 and _is_full_payment(actual, float(locked.amount or 0)):
        locked.amount = actual
    db.flush()
    finance_event_svc.upsert_scheduled_entry(db, locked, direction=direction)
    finance_event_svc.match(db, "bank", btx.id, locked.source_type, locked.id, method="auto")
    return True


def link_entry_to_bank(db: Session, entry: ScheduledEntry, btx, direction: int = -1) -> bool:
    """Girişi durumuna göre banka kanıtına bağla — açıksa kapat, ödenmişse eşle.

    Matcher (`_match_scheduled_to_bank`) ve öneri-Onayla yolu ORTAK çağırır.
    """
    if entry.is_paid:
        return attach_bank_to_paid_entry(db, entry, btx, direction=direction)
    return close_entry_via_bank(db, entry, btx, direction=direction)
