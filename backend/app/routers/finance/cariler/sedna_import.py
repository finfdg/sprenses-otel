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
from app.models.vendor_bank_account import VendorBankAccount
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload
from app.schemas.vendor import VendorUploadResult
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.sedna_client import (
    SednaUnavailable,
    fetch_cari_deleted_rows,
    fetch_cari_transactions,
    fetch_vendor_ibans,
    sedna_configured,
)
from app.utils.sync_vendor_fifo import sync_vendor_finance_events
from app.utils.vendor_parser import (
    ParsedVendorTransaction,
    calculate_payment_friday,
    compute_vendor_tx_hash,
)

from .bank_accounts import _norm_iban  # IBAN normalize (tek kaynak)
from .uploads import _compute_removal_candidates  # Excel ile aynı silme-adayı mantığı

logger = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Istanbul")
router = APIRouter()


def _f(v) -> float:
    return float(v) if v is not None else 0.0


# Bayat-satır süpürmesi güvenlik tavanı — tek import'ta bundan fazla satır silinmeye
# çalışılırsa (olası mantık hatası / Sedna kısmi veri) süpürme İPTAL edilir, hepsi manuel adaya düşer.
_SWEEP_SAFETY_CAP = 200


def _evrak_digits(evrak) -> str:
    return "".join(c for c in (evrak or "") if c.isdigit())


def _sweep_stale_vendor_txns(db: Session, candidate_ids: list, vendor_map: dict,
                             parsed: list, deleted_rows: list) -> set:
    """Bayat adaylardan yalnız POZİTİF KANITLI olanları otomatik sil (emsal: `_sweep_stale_checks`).

    `candidate_ids` = `_compute_removal_candidates`'ın döndürdüğü, zaten guard'lanmış (eşleşmemiş,
    atanmamış, eşleşmiş-FE yok, kapsam-içi) bayat aday ID'leri. "Sadece Sedna'da yok" YETMEZ
    (legit/Excel-only'yi silmemek için) — yalnız Sedna'da-vardı-artık-yok kanıtı olanlar silinir:
      - **Sinyal A:** yerel tx_hash Sedna'nın `Deleted=1` hash kümesinde (soft-delete edilmiş).
      - **Sinyal B:** yerel (kod, tarih, evrak-rakam) Sedna AKTİF'te var ama tam hash farklı
        (evrak Sedna'da duruyor, tutarı düzeltilmiş → eski tutarlı satır bayat).
    Kanıtsız (hard-delete / elle-eklenmiş) satırlar SİLİNMEZ → manuel silme-adayı olarak kalır.

    Döner: silinen VendorTransaction id kümesi.
    """
    if not candidate_ids or not parsed:
        return set()

    id_to_code = {v.id: code for code, v in vendor_map.items()}
    active_hashes = {tx.tx_hash for tx in parsed}
    active_evrak = {
        (tx.hesap_kodu, str(tx.date), _evrak_digits(tx.evrak_no))
        for tx in parsed if tx.date and _evrak_digits(tx.evrak_no)
    }
    deleted_hashes = set()
    for r in deleted_rows:
        code = (r.get("hesap_kodu") or "").strip()
        if code:
            deleted_hashes.add(compute_vendor_tx_hash(
                code, r.get("tarih"), r.get("evrak_no"), _f(r.get("borc")), _f(r.get("alacak"))))
    deleted_hashes -= active_hashes  # Sedna'da silinip yeniden girilmiş olanı hariç tut

    rows = db.query(VendorTransaction).filter(VendorTransaction.id.in_(candidate_ids)).all()
    to_sweep = []
    for r in rows:
        if r.tx_hash in active_hashes:  # savunmacı: Sedna aktifte birebir var → koru
            continue
        code = id_to_code.get(r.vendor_id, "")
        ed = _evrak_digits(r.evrak_no)
        sig_a = r.tx_hash in deleted_hashes
        sig_b = bool(ed) and (code, str(r.date), ed) in active_evrak
        if sig_a or sig_b:
            to_sweep.append((r, "A" if sig_a else "B"))

    if len(to_sweep) > _SWEEP_SAFETY_CAP:
        logger.error(
            "Bayat cari süpürmesi İPTAL: %d aday güvenlik tavanını (%d) aştı → hepsi manuel adaya bırakıldı.",
            len(to_sweep), _SWEEP_SAFETY_CAP)
        return set()

    swept = set()
    for r, sig in to_sweep:
        finance_event_svc.invalidate(db, "vendor_payment", r.id)
        logger.warning(
            "Bayat cari satırı silindi (sinyal %s): id=%s cari=%s tarih=%s borç=%s alacak=%s evrak=%s",
            sig, r.id, id_to_code.get(r.vendor_id), r.date, r.borc, r.alacak, r.evrak_no)
        db.delete(r)
        swept.add(r.id)
    if swept:
        db.flush()
    return swept


@router.get("/sedna-status")
def sedna_status(_: User = Depends(require_permission("finance.cariler", "view"))):
    """Sedna içe aktarma etkin mi (buton gösterimi için)."""
    return {"configured": sedna_configured()}


def run_cari_import(db: Session, current_user: User, ip=None) -> dict:
    """Sedna'dan (320 satıcılar) cari hareketlerini çek + Excel ile aynı upsert ile içe aktar.

    Servis fonksiyonu (HTTP'siz, broadcast'siz) — hem /sedna-import endpoint'i hem merkezi
    Sedna sync ortak kullanır. Hata durumunda HTTPException yükseltir (çağıran yakalar).
    """
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

    # Bayat-satır süpürmesi Sinyal A için Sedna silinmiş satırları — başarısız olursa
    # süpürme yalnız Sinyal B (evrak tutar düzeltmesi) ile sürer (import'u bozmaz).
    try:
        deleted_rows = fetch_cari_deleted_rows()
    except Exception as e:  # noqa: BLE001 — best-effort; import ana akışını düşürme
        logger.warning("Sedna silinmiş-satır sorgusu başarısız, bayat süpürme Sinyal A atlanıyor: %s", e)
        deleted_rows = []

    # Sedna satırları → ParsedVendorTransaction (Excel ile aynı yapı + hash)
    parsed: list = []
    vendor_names: dict = {}
    vendor_payday: dict = {}
    running: dict = {}  # hesap_kodu → yürüyen bakiye (devir + borç - alacak)
    rec_by_hash: dict = {}    # tx_hash → Sedna RecId (kalıcı kimlik damgası, Faz B)
    parsed_by_recid: dict = {}  # RecId → ParsedVendorTransaction (rec_id-güncelleme geçişi)
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
        ptx = ParsedVendorTransaction(
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
        )
        parsed.append(ptx)
        rec_id = r.get("rec_id")
        if rec_id is not None:
            rec_by_hash.setdefault(ptx.tx_hash, int(rec_id))
            parsed_by_recid[int(rec_id)] = ptx
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

        # ── Faz B: rec_id-kimlikli GÜNCELLEME geçişi (insert'ten ÖNCE) ──
        # Sedna'da tutar/tarih/evrak düzeltilen satır, kalıcı RecId sayesinde yerelde
        # UPDATE olur (hash kopması sil+ekle döngüsüne düşmez). KORUNAN (eşleşmiş/
        # atanmış) kayıt DEĞİŞTİRİLMEZ — Uyuşmayan Veriler'e 'Sedna sapması' yazılır
        # ve yeni-hash'li satırın mükerrer insert'i engellenir.
        updated_count = 0
        diff_ids: set = set()
        if parsed_by_recid:
            from app.services.sedna_recon_service import report_entity_diff

            local_recid_rows = (
                db.query(VendorTransaction)
                .filter(VendorTransaction.sedna_rec_id.in_(list(parsed_by_recid.keys())))
                .all()
            )
            for row in local_recid_rows:
                tx = parsed_by_recid.get(row.sedna_rec_id)
                if tx is None or tx.tx_hash == row.tx_hash:
                    continue
                vendor = vendor_map.get(tx.hesap_kodu)
                if vendor is None:
                    continue  # savunmacı: kod bu koşuda çözülemedi — dokunma
                # Cari değişimi: aynı RecId Sedna'da artık BAŞKA hesap kodunda (muhasebe
                # hareketi başka cariye taşımış). Eskiden burada atlanıyordu ("sweep/manuel")
                # ama insert geçişi aynı rec_id'li yeni satırı eklemeye çalışıp UNIQUE
                # ihlaliyle TÜM importu düşürüyordu (canlı hata 2026-07-13, rec_id 33044).
                # Artık korunmasız satır Sedna otoritesiyle yeni cariye TAŞINIR.
                vendor_changed = vendor.id != row.vendor_id
                guarded = row.match_number is not None or row.dept_status in ("assigned", "approved")
                if guarded:
                    vendor_note = ""
                    if vendor_changed:
                        old_vendor = db.get(Vendor, row.vendor_id)
                        old_code = old_vendor.hesap_kodu if old_vendor else f"id={row.vendor_id}"
                        vendor_note = f" · cari değişimi: {old_code} → {tx.hesap_kodu}"
                    report_entity_diff(
                        db, "vendor_tx", row.id,
                        amount=float(tx.alacak or tx.borc or 0), currency="TRY",
                        event_date=tx.date or row.date,
                        description=(f"Yerel: {row.date} borç {row.borc} alacak {row.alacak} "
                                     f"evrak {row.evrak_no or '-'}"),
                        sedna_description=(f"Sedna: {tx.date} borç {tx.borc} alacak {tx.alacak} "
                                           f"evrak {tx.evrak_no or '-'} · {tx.description or ''}"
                                           f"{vendor_note}"),
                        sedna_rec_id=row.sedna_rec_id,
                    )
                    diff_ids.add(row.id)
                    existing.add((vendor.id, tx.tx_hash))  # mükerrer insert engeli
                    continue
                # Korunmayan satır → Sedna otorite: alanları güncelle + FE tazele
                if vendor_changed:
                    logger.warning(
                        "Sedna cari değişimi: tx id=%s rec_id=%s yeni cari %s (vendor_id %s → %s)",
                        row.id, row.sedna_rec_id, tx.hesap_kodu, row.vendor_id, vendor.id)
                    row.vendor_id = vendor.id
                row.date = tx.date
                row.evrak_no = tx.evrak_no
                row.transaction_type = tx.transaction_type
                row.fis_no = tx.fis_no
                row.description = tx.description
                row.borc = tx.borc
                row.alacak = tx.alacak
                row.tx_hash = tx.tx_hash
                row.payment_due_date = (
                    calculate_payment_friday(tx.date, vendor.payment_days)
                    if tx.alacak > 0 and tx.date else None
                )
                db.flush()
                if row.payment_due_date:
                    finance_event_svc.upsert_vendor_tx(db, row, vendor, float(tx.alacak))
                else:
                    finance_event_svc.invalidate(db, "vendor_payment", row.id)
                existing.add((vendor.id, tx.tx_hash))
                updated_count += 1

        # ── Faz B: rec_id-kimlikli SİLİNME geçişi (2026-07-13) ──
        # Sedna'da Deleted=1 olan RecId yerelde hâlâ duruyorsa satır KESİN bayattır
        # (rec kimliği birebir; kod/tutar değişse bile). Hash-bazlı süpürme hesap kodu
        # değişince yakalayamıyordu (canlı: FEF...1058 F041→F040 taşınıp silindi;
        # F041-hash'li yerel satır hem hash hem kapsam dışı kaldı). Korunan satır
        # SİLİNMEZ → sapma raporlanır (mevcut politika).
        deleted_recids = {int(r["rec_id"]) for r in deleted_rows if r.get("rec_id") is not None}
        deleted_recids -= set(parsed_by_recid.keys())  # savunmacı: aktifte de görünen rec'e dokunma
        recid_deleted_count = 0
        if deleted_recids:
            from app.services.sedna_recon_service import report_entity_diff
            doomed = (
                db.query(VendorTransaction)
                .filter(VendorTransaction.sedna_rec_id.in_(list(deleted_recids)))
                .all()
            )
            unguarded_doomed = [
                r for r in doomed
                if r.match_number is None and r.dept_status not in ("assigned", "approved")
            ]
            if len(unguarded_doomed) > _SWEEP_SAFETY_CAP:
                logger.error(
                    "Rec_id-silinme geçişi İPTAL: %d satır güvenlik tavanını (%d) aştı "
                    "(olası Sedna veri sorunu) — hiçbiri silinmedi.",
                    len(unguarded_doomed), _SWEEP_SAFETY_CAP)
                unguarded_doomed = []
            unguarded_ids = {r.id for r in unguarded_doomed}
            for row in doomed:
                if row.id in unguarded_ids:
                    finance_event_svc.invalidate(db, "vendor_payment", row.id)
                    logger.warning(
                        "Sedna'da silinmiş (RecId %s) yerel cari satırı silindi: id=%s cari_id=%s "
                        "tarih=%s borç=%s alacak=%s evrak=%s",
                        row.sedna_rec_id, row.id, row.vendor_id, row.date, row.borc,
                        row.alacak, row.evrak_no)
                    db.delete(row)
                    recid_deleted_count += 1
                else:
                    report_entity_diff(
                        db, "vendor_tx", row.id,
                        amount=float(row.alacak or row.borc or 0), currency="TRY",
                        event_date=row.date,
                        description=(f"Eşleşmiş/atanmış yerel kayıt: {row.date} borç {row.borc} "
                                     f"alacak {row.alacak} evrak {row.evrak_no or '-'}"),
                        sedna_description="Sedna'da SİLİNMİŞ (Deleted=1, RecId) — muhasebeyle görüşün",
                        sedna_rec_id=row.sedna_rec_id,
                    )
                    diff_ids.add(row.id)
            if recid_deleted_count:
                db.flush()

        # Yerelde zaten damgalı rec_id kümesi — insert aynı rec_id'yi İKİNCİ satıra yazmaz
        # (partial-unique ihlali tüm importu düşürür; çakışan satır damgasız eklenir,
        # kimlik eski satır temizlenince sonraki koşunun geri-doldurmasıyla çözülür).
        stamped_recids = {
            rid for (rid,) in db.query(VendorTransaction.sedna_rec_id)
            .filter(VendorTransaction.sedna_rec_id.isnot(None)).all()
        }

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
            rid = rec_by_hash.get(tx.tx_hash)
            if rid is not None and rid in stamped_recids:
                logger.warning(
                    "Sedna rec_id çakışması: %s başka yerel satırda damgalı — yeni satır damgasız eklendi (evrak=%s)",
                    rid, tx.evrak_no)
                rid = None
            vtx = VendorTransaction(
                vendor_id=vendor.id, upload_id=upload.id, date=tx.date,
                evrak_no=tx.evrak_no, transaction_type=tx.transaction_type, fis_no=tx.fis_no,
                description=tx.description, borc=tx.borc, alacak=tx.alacak, bakiye=tx.bakiye,
                tx_hash=tx.tx_hash, payment_due_date=payment_due,
                sedna_rec_id=rid,
            )
            db.add(vtx)
            db.flush()
            if rid is not None:
                stamped_recids.add(rid)
            if payment_due:
                finance_event_svc.upsert_vendor_tx(db, vtx, vendor, float(tx.alacak))
            existing.add(key)
            new_count += 1

        # ── Faz B: rec_id geri-doldurma (hash'i eşleşen eski satırlara kimlik damgası) ──
        if rec_by_hash and vids:
            for row in (
                db.query(VendorTransaction)
                .filter(VendorTransaction.vendor_id.in_(vids),
                        VendorTransaction.sedna_rec_id.is_(None))
                .all()
            ):
                rid = rec_by_hash.get(row.tx_hash)
                if rid is not None and rid not in stamped_recids:
                    row.sedna_rec_id = rid
                    stamped_recids.add(rid)

        # ── Faz B: KORUNAN kayıt Sedna'da SİLİNMİŞSE de sapma olarak raporla ──
        if deleted_rows:
            from app.services.sedna_recon_service import close_stale_entity_diffs, report_entity_diff

            deleted_hash_set = set()
            for r in deleted_rows:
                code = (r.get("hesap_kodu") or "").strip()
                if code:
                    deleted_hash_set.add(compute_vendor_tx_hash(
                        code, r.get("tarih"), r.get("evrak_no"), _f(r.get("borc")), _f(r.get("alacak"))))
            deleted_hash_set -= {tx.tx_hash for tx in parsed}
            if deleted_hash_set:
                guarded_deleted = (
                    db.query(VendorTransaction)
                    .filter(VendorTransaction.vendor_id.in_(vids),
                            VendorTransaction.tx_hash.in_(list(deleted_hash_set)),
                            VendorTransaction.match_number.isnot(None))
                    .all()
                )
                for row in guarded_deleted:
                    report_entity_diff(
                        db, "vendor_tx", row.id,
                        amount=float(row.alacak or row.borc or 0), currency="TRY",
                        event_date=row.date,
                        description=(f"Eşleşmiş yerel kayıt (match #{row.match_number}): "
                                     f"{row.date} borç {row.borc} alacak {row.alacak}"),
                        sedna_description="Sedna'da SİLİNMİŞ (Deleted=1) — muhasebeyle görüşün",
                        sedna_rec_id=row.sedna_rec_id,
                    )
                    diff_ids.add(row.id)

        # Bu koşuda artık raporlanmayan cari sapmalarını otomatik kapat (Faz B)
        from app.services.sedna_recon_service import close_stale_entity_diffs
        close_stale_entity_diffs(db, "vendor_tx", diff_ids)

        upload.total_vendors = len(vendor_codes)
        upload.total_transactions = len(parsed)
        upload.new_transactions = new_count
        upload.skipped_transactions = skipped

        removal_candidates = _compute_removal_candidates(db, vendor_map, parsed)

        # Pozitif kanıtlı bayatları (Sinyal A: Sedna Deleted=1 · Sinyal B: evrak tutar düzeltmesi)
        # otomatik sil; kanıtsızlar (hard-delete/elle) manuel silme-adayı olarak kalır.
        swept_ids = _sweep_stale_vendor_txns(
            db, [c.id for c in removal_candidates], vendor_map, parsed, deleted_rows)
        if swept_ids:
            removal_candidates = [c for c in removal_candidates if c.id not in swept_ids]

        details = f"Sedna içe aktarma: {new_count} yeni, {skipped} mükerrer"
        if updated_count:
            details += f", {updated_count} rec_id-güncellendi"
        if recid_deleted_count:
            details += f", {recid_deleted_count} rec_id-silinmiş temizlendi"
        if diff_ids:
            details += f", {len(diff_ids)} korunan-sapma raporlandı"
        if swept_ids:
            details += f", {len(swept_ids)} bayat silindi"
        if removal_candidates:
            details += f", {len(removal_candidates)} silme adayı"
        log_action(
            db, current_user.id, "create", "vendor_upload", entity_id=upload.id,
            details=details, ip_address=ip,
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

    return VendorUploadResult(
        upload_id=upload.id,
        file_name=upload.file_name,
        total_vendors=upload.total_vendors,
        total_transactions=upload.total_transactions,
        new_transactions=new_count,
        skipped_transactions=skipped,
        removal_candidates=removal_candidates,
    ).model_dump()


def run_iban_import(db: Session, current_user: User, ip=None) -> dict:
    """Sedna dbo.Bank'tan cari (320) banka/IBAN'larını çek → vendor_bank_accounts'a upsert.

    Dedup (cari + IBAN); caride hiç hesap yoksa ilk IBAN varsayılan olur. Mevcut IBAN'ın
    banka adı boşsa Sedna'dan doldurulur (varsayılan seçimi/elle eklenenler korunur).
    Yalnız MEVCUT carilere işler (önce hareket import'u). Servis fonksiyonu (HTTP'siz, broadcast'siz).
    """
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        rows = fetch_vendor_ibans()
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Sedna IBAN sorgu hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Sedna IBAN verisi alınamadı. Lütfen tekrar deneyin.")

    # normalize + boş ele
    norm: list = []
    for r in rows:
        code = (r.get("hesap_kodu") or "").strip()
        iban = _norm_iban(r.get("iban"))
        if not code or not iban:
            continue
        norm.append((
            code, iban,
            (r.get("banka") or "").strip() or None,
            (r.get("unvan") or "").strip() or None,
        ))

    codes = sorted({c for c, _, _, _ in norm})
    vendors = {
        v.hesap_kodu: v
        for v in (db.query(Vendor).filter(Vendor.hesap_kodu.in_(codes)).all() if codes else [])
    }
    vids = [v.id for v in vendors.values()]

    existing_by_vendor: dict = {}  # vid → {iban_upper: VendorBankAccount}
    state: dict = {}               # vid → {"count": n, "sort": max_sort}
    if vids:
        for ba in db.query(VendorBankAccount).filter(VendorBankAccount.vendor_id.in_(vids)).all():
            existing_by_vendor.setdefault(ba.vendor_id, {})[(ba.iban or "").upper()] = ba
    for vid in vids:
        accs = existing_by_vendor.get(vid, {})
        state[vid] = {"count": len(accs), "sort": max((b.sort_order for b in accs.values()), default=-1)}

    new_ibans = updated = skipped_existing = skipped_no_vendor = 0
    matched_vendors = set()
    try:
        for code, iban, banka, unvan in norm:
            v = vendors.get(code)
            if not v:
                skipped_no_vendor += 1
                continue
            matched_vendors.add(v.id)
            existing = existing_by_vendor.setdefault(v.id, {})
            st = state[v.id]
            if iban in existing:
                ba = existing[iban]
                if banka and not (ba.bank_name or "").strip():  # boş banka adını doldur
                    ba.bank_name = banka
                    updated += 1
                else:
                    skipped_existing += 1
                continue
            is_default = st["count"] == 0  # caride hiç hesap yoksa ilki varsayılan
            st["sort"] += 1
            ba = VendorBankAccount(
                vendor_id=v.id, bank_name=banka, iban=iban,
                account_holder=unvan, is_default=is_default, sort_order=st["sort"],
            )
            db.add(ba)
            db.flush()
            existing[iban] = ba
            st["count"] += 1
            new_ibans += 1

        log_action(
            db, current_user.id, "create", "vendor_bank_account", None,
            f"Sedna IBAN içe aktarma: {new_ibans} yeni, {updated} güncellendi, "
            f"{skipped_no_vendor} carisiz",
            ip_address=ip,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Sedna IBAN içe aktarma DB hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="IBAN içe aktarma sırasında veritabanı hatası oluştu.")

    return {
        "total_fetched": len(rows),
        "vendors_matched": len(matched_vendors),
        "new_ibans": new_ibans,
        "updated": updated,
        "skipped_existing": skipped_existing,
        "skipped_no_vendor": skipped_no_vendor,
    }


# ─── Tekil endpoint'ler (servis fonksiyonlarının ince HTTP sarmalı) ───


@router.post("/sedna-import")
def sedna_import(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Sedna cari hareketleri içe aktarma (tekil)."""
    result = run_cari_import(db, current_user, get_client_ip(request))
    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "upload")
    return result


@router.post("/sedna-import-ibans")
def sedna_import_ibans(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    """Sedna cari IBAN içe aktarma (tekil)."""
    result = run_iban_import(db, current_user, get_client_ip(request))
    broadcast_finance_update(background_tasks, BroadcastModule.CARILER, "update")
    return result
