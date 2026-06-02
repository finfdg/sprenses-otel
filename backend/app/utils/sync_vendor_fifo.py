"""finance_events tablosundaki vendor_payment kayıtlarını FIFO ile senkronize et.

FIFO sonrası tam ödenmiş faturalar → finance_event silinir
Kısmi ödenmiş faturalar → tutarı güncellenir
Ödenmemişler → olduğu gibi kalır
Vadesi geçmiş faturalar → sonraki Cuma'ya kaydırılır
"""
import logging

from sqlalchemy.orm import Session

from app.models.finance_event import FinanceEvent
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.utils.vendor_fifo import calculate_fifo_amounts, effective_due_date

logger = logging.getLogger(__name__)


def sync_vendor_finance_events(db: Session) -> dict:
    """FIFO tutarları ile finance_events'i güncelle.

    Returns:
        {"created": int, "updated": int, "removed": int}
    """
    fifo = calculate_fifo_amounts(db)

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

    # 1) FIFO'da olan faturalar → oluştur veya güncelle
    for vtx_id, fifo_amount in fifo.items():
        fe = existing_map.pop(vtx_id, None)
        vtx_info = vtx_map.get(vtx_id)

        if fe:
            # Mevcut — tutarı güncelle
            if abs(float(fe.amount) - fifo_amount) > 0.01:
                fe.amount = fifo_amount
                updated += 1
            # is_matched = False (ödenmemiş)
            if fe.is_matched:
                fe.is_matched = False
                updated += 1
            # Vadesi geçmiş → sonraki Cuma'ya kaydır
            if vtx_info:
                vtx_obj = vtx_info[0]
                eff_date = effective_due_date(vtx_obj.payment_due_date)
                if fe.event_date != eff_date:
                    fe.event_date = eff_date
                    updated += 1
        elif vtx_info:
            # Yeni — oluştur (vadesi geçmişse sonraki Cuma'ya kaydır)
            vtx, hesap_adi, hesap_kodu = vtx_info
            eff_date = effective_due_date(vtx.payment_due_date)
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

    return {"created": created, "updated": updated, "removed": removed}
