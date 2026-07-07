"""finance_events tablosundaki vendor_payment kayıtlarını FIFO ile senkronize et.

FIFO sonrası tam ödenmiş faturalar → finance_event silinir
Kısmi ödenmiş faturalar → tutarı güncellenir
Ödenmemişler → olduğu gibi kalır
Vadesi geçen faturalar → ORİJİNAL tarihinde kalır (Cuma roll-over kaldırıldı 2026-07-04);
yalnız KALICI ÖTELEME (payment_deferrals) varsa ertelenmiş tarihe çekilir.

CARİ-BAĞLI DÜZENLİ ÖDEME İSTİSNASI (2026-07-07): Aktif bir düzenli ödeme tanımına
bağlı carilerin (`ScheduledDefinition.vendor_id` — ör. ASAT=su, CK Elektrik=elektrik)
nakit akımını **recurring finance_event** temsil eder → bu carilere `vendor_payment`
FE'si ÜRETİLMEZ, mevcutları silinir (çift sayım önleme; kullanıcı takibi Düzenli
Ödemeler'den yapar). Ayrıca FIFO her değiştiğinde (ödeme eşleşmesi, içe aktarma,
vade güncellemesi) bağlı recurring girişlerinin durumu/kalanı da AYNI FIFO ile
güncellenir (`sync_recurring_from_vendors`) — durum Sedna sync'i beklemez.

NOT: Bu fonksiyon FinanceEvent'i ORM ile DOĞRUDAN yazar (upsert_vendor_tx üzerinden
DEĞİL) → merkezî `_upsert` deferral override'ı BURADA çalışmaz; öteleme bu yüzden
`effective_due_date(..., deferral_map)` ile burada da uygulanır.
"""
import logging

from sqlalchemy.orm import Session

from app.models.finance_event import FinanceEvent
from app.models.scheduled import ScheduledDefinition
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.services.deferral_service import get_deferral_map
from app.utils.recurring_vendor_sync import sync_recurring_from_vendors
from app.utils.vendor_fifo import calculate_fifo_amounts, effective_due_date

logger = logging.getLogger(__name__)


def sync_vendor_finance_events(db: Session) -> dict:
    """FIFO tutarları ile finance_events'i güncelle.

    Returns:
        {"created": int, "updated": int, "removed": int}
    """
    fifo = calculate_fifo_amounts(db)
    deferral_map = get_deferral_map(db)

    # Aktif düzenli ödeme tanımına bağlı cariler — nakit akımı recurring FE temsil eder
    # → vendor_payment FE üretilmez / varsa silinir (modül docstring'ine bkz.)
    linked_vendor_ids = {
        vid for (vid,) in db.query(ScheduledDefinition.vendor_id).filter(
            ScheduledDefinition.vendor_id.isnot(None),
            ScheduledDefinition.is_active.is_(True),
        )
    }

    # Mevcut vendor_payment finance_events
    existing_fes = (
        db.query(FinanceEvent)
        .filter(FinanceEvent.source_type == "vendor_payment")
        .all()
    )
    existing_map = {fe.source_id: fe for fe in existing_fes}

    # Tüm alacak faturalarını (vendor bilgisi ile) cache'le
    all_vtx = (
        db.query(VendorTransaction, Vendor.hesap_adi, Vendor.hesap_kodu)
        .join(Vendor, VendorTransaction.vendor_id == Vendor.id)
        .filter(
            VendorTransaction.alacak > 0,
            VendorTransaction.payment_due_date.isnot(None),
        )
        .all()
    )
    vtx_map = {vtx.id: (vtx, hesap_adi, hesap_kodu) for vtx, hesap_adi, hesap_kodu in all_vtx}

    created = 0
    updated = 0
    removed = 0

    # 0) Bağlı carilerin eski FE'lerini temizle (FE'nin kendi vendor_id'sinden — vtx durumundan bağımsız)
    for vtx_id in list(existing_map):
        if existing_map[vtx_id].vendor_id in linked_vendor_ids:
            db.delete(existing_map.pop(vtx_id))
            removed += 1

    # 1) FIFO'da olan faturalar → oluştur veya güncelle
    for vtx_id, fifo_amount in fifo.items():
        fe = existing_map.pop(vtx_id, None)
        vtx_info = vtx_map.get(vtx_id)

        # Bağlı cariye yeni FE üretilmez (0. adım mevcutları temizledi)
        if vtx_info and vtx_info[0].vendor_id in linked_vendor_ids:
            continue

        if fe:
            # Mevcut — tutarı güncelle
            if abs(float(fe.amount) - fifo_amount) > 0.01:
                fe.amount = fifo_amount
                updated += 1
            # is_matched = False (ödenmemiş)
            if fe.is_matched:
                fe.is_matched = False
                updated += 1
            # Öteleme varsa ertelenmiş tarih; yoksa orijinal vade (Cuma roll-over yok)
            if vtx_info:
                vtx_obj = vtx_info[0]
                eff_date = effective_due_date(
                    vtx_obj.payment_due_date, vtx_id=vtx_id, deferral_map=deferral_map
                )
                if fe.event_date != eff_date:
                    fe.event_date = eff_date
                    updated += 1
        elif vtx_info:
            # Yeni — oluştur (öteleme varsa ertelenmiş tarihe çek)
            vtx, hesap_adi, hesap_kodu = vtx_info
            eff_date = effective_due_date(
                vtx.payment_due_date, vtx_id=vtx_id, deferral_map=deferral_map
            )
            new_fe = FinanceEvent(
                source_type="vendor_payment",
                source_id=vtx_id,
                event_date=eff_date,
                amount=fifo_amount,
                direction=-1,
                currency="TRY",
                description=hesap_adi,
                payment_method="cari",
                vendor_id=vtx.vendor_id,
                vendor_code=hesap_kodu,
                tag_note=vtx.evrak_no,
                is_matched=False,
                is_realized=False,
            )
            db.add(new_fe)
            created += 1

    # 2) FIFO'da olmayan (tam ödenmiş) faturalar → sil
    for vtx_id, fe in existing_map.items():
        db.delete(fe)
        removed += 1

    # 3) Bağlı recurring girişlerini AYNI FIFO ile güncelle (ödeme eşleşince
    # Düzenli Ödemeler durumu + nakit akım kalanı Sedna sync'i beklemeden tazelenir)
    recurring_synced = 0
    if linked_vendor_ids:
        recurring_synced = sync_recurring_from_vendors(db, fifo=fifo)["entries_synced"]

    return {"created": created, "updated": updated, "removed": removed,
            "recurring_synced": recurring_synced}
