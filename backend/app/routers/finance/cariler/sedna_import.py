"""Cari hareketlerini Sedna SQL Server'dan (ters SSH tüneli üzerinden) içe aktar.

Excel yükleme ile **AYNI** upsert mantığı: VendorUpload kaydı + vendor upsert + tx_hash
dedup + payment_due + finance_events + silme adayları. tx_hash `compute_vendor_tx_hash`
ile üretildiğinden Excel/Sedna arası **MÜKERRER OLMAZ** (aynı işlem aynı hash).

Özel/operasyonel içe-aktarma endpoint'i (dosya yükleme gibi) — onay akışından muaf, audit'li.
Tünel kapalıysa 503 döner; uygulamanın geri kalanı etkilenmez.
"""
import logging
from datetime import datetime

import pytz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload
from app.schemas.vendor import VendorUploadResult
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.sedna_client import SednaUnavailable, fetch_cari_transactions, sedna_configured
from app.utils.sync_vendor_fifo import sync_vendor_finance_events
from app.utils.vendor_parser import (
    ParsedVendorTransaction,
    calculate_payment_friday,
    compute_vendor_tx_hash,
)

from .uploads import _compute_removal_candidates  # Excel ile aynı silme-adayı mantığı

logger = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Istanbul")
router = APIRouter()


def _f(v) -> float:
    return float(v) if v is not None else 0.0


@router.get("/sedna-status")
def sedna_status(_: User = Depends(require_permission("finance.cariler", "view"))):
    """Sedna içe aktarma etkin mi (buton gösterimi için)."""
    return {"configured": sedna_configured()}


@router.post("/sedna-import")
def sedna_import(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Sedna'dan (320 satıcılar) cari hareketlerini çek + Excel ile aynı upsert ile içe aktar."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        rows = fetch_cari_transactions()
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Sedna içe aktarma sorgu hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Sedna verisi alınamadı. Lütfen tekrar deneyin.")

    if not rows:
        raise HTTPException(status_code=400, detail="Sedna'dan cari hareket alınamadı (0 satır).")

    # Sedna satırları → ParsedVendorTransaction (Excel ile aynı yapı + hash)
    parsed: list = []
    vendor_names: dict = {}
    vendor_payday: dict = {}
    running: dict = {}  # hesap_kodu → yürüyen bakiye (devir + borç - alacak)
    for r in rows:
        code = (r.get("hesap_kodu") or "").strip()
        if not code:
            continue
        borc = _f(r.get("borc"))
        alacak = _f(r.get("alacak"))
        d = r.get("tarih")
        name = (r.get("hesap_adi") or "").strip()
        evrak = (r.get("evrak_no") or None)
        fis_raw = r.get("fis_no")
        running[code] = round(running.get(code, 0.0) + borc - alacak, 2)
        parsed.append(ParsedVendorTransaction(
            hesap_kodu=code,
            hesap_adi=name,
            date=d,
            evrak_no=evrak,
            transaction_type=(r.get("islem_tipi") or None),
            fis_no=(str(fis_raw) if fis_raw is not None else None),
            description=(r.get("aciklama") or None),
            borc=borc,
            alacak=alacak,
            bakiye=running[code],
            tx_hash=compute_vendor_tx_hash(code, d, evrak, borc, alacak),
        ))
        if code not in vendor_names and name:
            vendor_names[code] = name
        if code not in vendor_payday:
            pd = r.get("pay_day")
            vendor_payday[code] = int(pd) if pd else 0

    vendor_codes = sorted({tx.hesap_kodu for tx in parsed})
    if not vendor_codes:
        raise HTTPException(status_code=400, detail="Geçerli cari kodu bulunamadı.")

    try:
        upload = VendorUpload(
            file_name=f"Sedna içe aktarma · {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}",
            file_url="sedna://import",  # gerçek dosya yok (delete'te path kontrolü güvenli)
            uploaded_by=current_user.id,
        )
        db.add(upload)
        db.flush()

        # Cari kartları upsert (yeni cariye ad + ödeme günü; mevcut cari Excel gibi DOKUNULMAZ)
        vendor_map = {}
        for code in vendor_codes:
            vendor = db.query(Vendor).filter(Vendor.hesap_kodu == code).first()
            if not vendor:
                pd = vendor_payday.get(code) or 0
                vendor = Vendor(
                    hesap_kodu=code,
                    hesap_adi=vendor_names.get(code, ""),
                    payment_days=pd if pd > 0 else 90,
                )
                db.add(vendor)
                db.flush()
            vendor_map[code] = vendor

        # Mevcut hash'ler (vendor bazlı) → dedup
        existing = set()
        vids = [v.id for v in vendor_map.values()]
        if vids:
            for vid, h in (
                db.query(VendorTransaction.vendor_id, VendorTransaction.tx_hash)
                .filter(VendorTransaction.vendor_id.in_(vids))
                .all()
            ):
                existing.add((vid, h))

        new_count = 0
        skipped = 0
        for tx in parsed:
            vendor = vendor_map[tx.hesap_kodu]
            key = (vendor.id, tx.tx_hash)
            if key in existing:
                skipped += 1
                continue
            payment_due = None
            if tx.alacak > 0 and tx.date:
                payment_due = calculate_payment_friday(tx.date, vendor.payment_days)
            vtx = VendorTransaction(
                vendor_id=vendor.id, upload_id=upload.id, date=tx.date,
                evrak_no=tx.evrak_no, transaction_type=tx.transaction_type, fis_no=tx.fis_no,
                description=tx.description, borc=tx.borc, alacak=tx.alacak, bakiye=tx.bakiye,
                tx_hash=tx.tx_hash, payment_due_date=payment_due,
            )
            db.add(vtx)
            db.flush()
            if payment_due:
                finance_event_svc.upsert_vendor_tx(db, vtx, vendor, float(tx.alacak))
            existing.add(key)
            new_count += 1

        upload.total_vendors = len(vendor_codes)
        upload.total_transactions = len(parsed)
        upload.new_transactions = new_count
        upload.skipped_transactions = skipped

        removal_candidates = _compute_removal_candidates(db, vendor_map, parsed)

        details = f"Sedna içe aktarma: {new_count} yeni, {skipped} mükerrer"
        if removal_candidates:
            details += f", {len(removal_candidates)} silme adayı"
        log_action(
            db, current_user.id, "create", "vendor_upload", entity_id=upload.id,
            details=details, ip_address=get_client_ip(request),
        )
        db.commit()
        sync_vendor_finance_events(db)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("Sedna içe aktarma DB hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="İçe aktarma sırasında veritabanı hatası oluştu.")

    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "upload")

    return VendorUploadResult(
        upload_id=upload.id,
        file_name=upload.file_name,
        total_vendors=upload.total_vendors,
        total_transactions=upload.total_transactions,
        new_transactions=new_count,
        skipped_transactions=skipped,
        removal_candidates=removal_candidates,
    ).model_dump()
