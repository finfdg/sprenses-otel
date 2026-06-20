"""Verilen çekler endpoint'leri."""
import asyncio
import logging
import math
import os
import uuid
from datetime import datetime
from typing import Optional

import pytz
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip, upload_limiter
from app.models.bank_transaction import BankTransaction
from app.models.check import Check, CheckUpload
from app.models.user import User
from app.schemas.check import CheckResponse, CheckUploadResponse, CheckUploadResult
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.check_parser import parse_check_excel
from app.utils.file_validation import validate_upload_file
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.matching_service import _match_checks_to_bank
from app.utils.sedna_client import SednaUnavailable, fetch_issued_checks, sedna_configured

logger = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Istanbul")

router = APIRouter(prefix="/checks")


def _check_status_from_pos(max_pos: Optional[int]) -> str:
    """Sedna çek pozisyonu → bizim durum. 101/102 Bankadan/Kasadan Ödeme=paid,
    103 Geri Al=cancelled, gerisi (100 Verilen, 104 Protesto, 105 Takipte)=pending."""
    if max_pos in (101, 102):
        return "paid"
    if max_pos == 103:
        return "cancelled"
    return "pending"


def _check_dedup_key(check_no, vendor_code, currency, amount_tl, amount_currency):
    """Çek dedup anahtarı: (check_no, vendor_code, currency, NATIVE tutar).

    `due_date` ANAHTARDA YOK → vade değişimi mükerrer üretmez. Tutar olarak **para birimi cinsi
    yüz değer** kullanılır: TL çek → `amount_tl` (sabit); döviz çek → `amount_currency` (EUR/USD
    yüz değeri, sabit). `amount_tl` döviz çekte TL değerlemesidir ve KUR ile değişir → anahtarda
    kullanılamaz (her kur hareketinde "yeni" çek sanılır)."""
    curr = (currency or "TL").strip().upper()
    if curr in ("TL", "TRY", ""):
        return (check_no, vendor_code, "TL", round(float(amount_tl or 0), 2))
    return (check_no, vendor_code, curr, round(float(amount_currency or amount_tl or 0), 2))


UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "uploads", "check_files",
)


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─── Dosya Yükleme ──────────────────────────────────────


@router.post("/upload")
async def upload_checks(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.checks", "use")),
):
    """Verilen çekler Excel dosyasını yükle ve ayrıştır."""
    upload_limiter.check(f"upload-{get_client_ip(request)}")
    content = await validate_upload_file(file, allowed_types=["excel"])

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    _ensure_upload_dir()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        f.write(content)

    try:
        # CPU-yoğun Excel parse'ı threadpool'a al → event loop bloke olmaz (eşzamanlı istekler beklemez)
        parsed = await asyncio.to_thread(parse_check_excel, file_path)
    except Exception as e:
        logger.error("Çek dosyası ayrıştırma hatası (%s): %s", file.filename, e, exc_info=True)
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Dosya ayrıştırılamadı. Lütfen geçerli bir çek dosyası yükleyin.")

    if not parsed.checks:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Dosyada çek kaydı bulunamadı")

    # Upload kaydı
    upload = CheckUpload(
        file_name=file.filename or unique_name,
        file_url=file_path,
        uploaded_by=current_user.id,
    )
    db.add(upload)
    db.flush()

    # Mevcut çek anahtarlarını al — Sedna import'uyla AYNI dedup (_check_dedup_key): vade değişen
    # çek Excel yüklemede de mükerrer üretmez; döviz çekte kur-bağımsız yüz değer kullanılır.
    existing_keys = set(
        _check_dedup_key(row[0], row[1], row[2], row[3], row[4]) for row in
        db.query(Check.check_no, Check.vendor_code, Check.currency,
                 Check.amount_tl, Check.amount_currency).all()
    )

    new_count = 0
    skipped_count = 0

    for c in parsed.checks:
        key = _check_dedup_key(c.check_no, c.vendor_code, c.currency, c.amount_tl, c.amount_currency)
        if key in existing_keys:
            skipped_count += 1
            continue

        new_check = Check(
            upload_id=upload.id,
            check_type=c.check_type,
            sequence_no=c.sequence_no,
            check_no=c.check_no,
            vendor_code=c.vendor_code,
            vendor_name=c.vendor_name,
            description=c.description,
            city=c.city,
            due_date=c.due_date,
            amount_tl=c.amount_tl,
            currency=c.currency,
            amount_currency=c.amount_currency,
            transaction_type=c.transaction_type,
        )
        db.add(new_check)
        db.flush()
        finance_event_svc.upsert_check(db, new_check)
        existing_keys.add(key)
        new_count += 1

    upload.total_checks = len(parsed.checks)
    upload.new_checks = new_count
    upload.skipped_checks = skipped_count

    log_action(
        db, current_user.id, "create", "check_upload",
        entity_id=upload.id,
        details=f"Çek dosyası yüklendi: {file.filename} ({new_count} yeni, {skipped_count} mükerrer)",
        ip_address=get_client_ip(request),
    )
    db.commit()
    # Yeni çekleri MEVCUT banka hareketleriyle eşleştir (ekstre daha önce yüklenmiş olabilir)
    try:
        _match_checks_to_bank(db)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Çek upload sonrası banka eşleştirme hatası: %s", e)
    broadcast_finance_update(background_tasks, BroadcastModule.CHECKS, "upload")

    return CheckUploadResult(
        upload_id=upload.id,
        file_name=upload.file_name,
        total_checks=len(parsed.checks),
        new_checks=new_count,
        skipped_checks=skipped_count,
    ).model_dump()


# ─── Sedna (muhasebe DB) doğrudan içe aktarma ───────────


@router.get("/sedna-status")
def sedna_status(_: User = Depends(require_permission("finance.checks", "view"))):
    """Sedna çek içe aktarma etkin mi (buton gösterimi için)."""
    return {"configured": sedna_configured()}


def run_check_import(db: Session, current_user: User, ip=None) -> dict:
    """Sedna'dan verilen çekleri çek (320 satıcı + 159 avans + 335 personel/ortak) + dedup ile içe aktar.

    **Dedup key: (check_no, vendor_code, currency, NATIVE tutar)** — `due_date` ANAHTARDA YOK. Sedna'da
    çekin vadesi değişince (yeniden vadelendirme) yeni kayıt değil **mevcut kaydın güncellenmesi** gerekir;
    tutar yeniden vadelendirmede sabittir ama aynı no'lu farklı çekleri ayırır. Mevcut çek **banka/cari
    eşleşmesi yoksa** vade + durum Sedna'dan güncellenir; eşleşmişe dokunulmaz. Vade değişiminden kalan
    eşleşmemiş mükerrerler temizlenir (geçmiş kayıtların hayalet gösterimi engellenir).

    **Tutar-kayması iyileştirmesi:** dedup-key bulunamayıp aynı `(check_no, vendor_code, due_date)` UNIQUE
    üçlüsünde EŞLEŞMEMİŞ bir kayıt varsa (tutar/para birimi bizde bozuk), INSERT yerine Sedna'ya hizalanır
    — aksi halde UNIQUE çakışıp sessizce atlanır ve yanlış tutar kalıcı olurdu (ör. PEKSAN 0353816 bizde
    30.000 TL sanılmış, Sedna'da 30.000 EUR=1.596.726 TL). Eşleşmiş kayda dokunulmaz (mutabık veri korunur).

    Sonunda banka eşleştirme çalışır. Servis fonksiyonu (HTTP'siz, broadcast'siz) — endpoint + merkezi sync ortak.
    """
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        rows = fetch_issued_checks()
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Sedna çek sorgu hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Sedna çek verisi alınamadı. Lütfen tekrar deneyin.")

    if not rows:
        raise HTTPException(status_code=400, detail="Sedna'dan verilen çek alınamadı (0 satır).")

    upload = CheckUpload(
        file_name=f"Sedna çek içe aktarma · {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}",
        file_url="sedna://import",
        uploaded_by=current_user.id,
    )
    db.add(upload)
    db.flush()

    # Mevcut çekler + vade değişiminden kalan eşleşmemiş mükerrerleri tespit et (temizlik için).
    # Dedup anahtarı: (check_no, vendor_code, currency, NATIVE tutar) — bk. _check_dedup_key.
    existing = {}
    stale_dupes = []
    for c in db.query(Check).order_by(Check.id).all():
        k = _check_dedup_key(c.check_no, c.vendor_code, c.currency, c.amount_tl, c.amount_currency)
        prev = existing.get(k)
        if prev is None:
            existing[k] = c
            continue
        c_matched = bool(c.bank_transaction_id or c.match_number)
        prev_matched = bool(prev.bank_transaction_id or prev.match_number)
        if prev_matched and not c_matched:
            stale_dupes.append(c)                       # eşleşmiş prev korunur
        elif c_matched and not prev_matched:
            stale_dupes.append(prev); existing[k] = c   # eşleşmiş c korunur
        elif not c_matched and not prev_matched:
            stale_dupes.append(prev); existing[k] = c   # ikisi de eşleşmemiş → yeni (c) tut, eskiyi sil
        # else: ikisi de eşleşmiş → gerçek ayrı ödemeler olabilir, DOKUNMA

    new_count = updated_count = skipped_count = removed_dupes = 0
    try:
        # Vade değişiminden kalan eşleşmemiş mükerrerleri ÖNCE temizle — güncelleme döngüsünde
        # mevcut kaydı yeni vadeye çekerken UNIQUE(check_no,vendor_code,due_date) çakışmasını önler.
        for d in stale_dupes:
            finance_event_svc.invalidate(db, "check", d.id)
            db.delete(d)
            removed_dupes += 1
        if removed_dupes:
            db.flush()

        for r in rows:
            check_no = (str(r.get("check_no")) or "").strip()[:50]
            vendor_code = (r.get("vendor_code") or "").strip() or None
            due_date = r.get("due_date")
            if not check_no or not due_date:
                skipped_count += 1
                continue
            curr = (r.get("currency") or "TL").strip() or "TL"
            amount_tl = float(r.get("amount_tl") or 0)
            cur_amt = float(r.get("amount_currency") or 0)
            amount_currency = cur_amt if (curr != "TL" and cur_amt) else amount_tl
            new_status = _check_status_from_pos(r.get("max_pos"))
            bank = (r.get("bank") or "").strip() or None
            key = _check_dedup_key(check_no, vendor_code, curr, amount_tl, amount_currency)

            # Her satır kendi SAVEPOINT'inde — bir kısıt çakışması tüm içe aktarmayı düşürmesin.
            try:
                with db.begin_nested():
                    ex = existing.get(key)
                    if ex is not None:
                        # eşleşmemiş çek → Sedna güncel durumunu yansıt (VADE + durum + banka); eşleşmişe dokunma.
                        # Banka farkı/eksiği de tetikler → mevcut çeklerde bank_name geriye doldurulur (re-sync backfill).
                        if ex.bank_transaction_id is None and ex.match_number is None:
                            bank_changed = bool(bank) and ex.bank_name != bank
                            if ex.due_date != due_date or ex.status != new_status or bank_changed:
                                ex.due_date = due_date
                                ex.status = new_status
                                ex.amount_currency = amount_currency
                                ex.currency = curr
                                if bank:
                                    ex.bank_name = bank
                                finance_event_svc.upsert_check(db, ex)
                                updated_count += 1
                            else:
                                skipped_count += 1
                        else:
                            skipped_count += 1
                    else:
                        # Bu dedup-key (no,vendor,para,tutar) yok. Ama AYNI (no,vendor,vade) UNIQUE
                        # üçlüsünde bir kayıt olabilir → tutar/para BİRİMİ kaymış (ör. PEKSAN 0353816
                        # bizde 30.000 TL sanılmış, Sedna'da 30.000 EUR = 1.596.726 TL). Eşleşmemişse
                        # Sedna'ya HİZALA (INSERT yerine UPDATE) — aksi halde UNIQUE çakışıp sessizce
                        # atlanır ve yanlış tutar kalıcı olur (nakit akım eksik). Eşleşmişe DOKUNMA
                        # (mutabık verimiz korunur, ör. 714659 paid+banka-eşleşmiş EUR/TL etiketi).
                        drift = db.query(Check).filter(
                            Check.check_no == check_no,
                            Check.vendor_code == vendor_code,
                            Check.due_date == due_date,
                        ).first()
                        if drift is not None and drift.bank_transaction_id is None and drift.match_number is None:
                            drift.amount_tl = amount_tl
                            drift.amount_currency = amount_currency
                            drift.currency = curr
                            drift.status = new_status
                            if bank:
                                drift.bank_name = bank
                            finance_event_svc.upsert_check(db, drift)
                            existing[key] = drift
                            updated_count += 1
                        elif drift is not None:
                            skipped_count += 1               # eşleşmiş çek → dokunma (benign)
                        else:
                            chk = Check(
                                upload_id=upload.id,
                                check_type=None,
                                check_no=check_no,
                                vendor_code=vendor_code,
                                vendor_name=(r.get("vendor_name") or "").strip() or check_no,
                                bank_name=bank,                   # çekin ödeneceği banka (Sedna AccCheck.Bank)
                                city=(r.get("city") or "").strip() or None,
                                due_date=due_date,
                                amount_tl=amount_tl,
                                currency=curr,
                                amount_currency=amount_currency,
                                transaction_type="Verilen Çek",
                                status=new_status,
                            )
                            db.add(chk)
                            db.flush()
                            finance_event_svc.upsert_check(db, chk)
                            existing[key] = chk
                            new_count += 1
            except IntegrityError:
                skipped_count += 1
                logger.warning("Çek kısıt çakışması, atlandı: no=%s vendor=%s vade=%s tutar=%s %s",
                               check_no, vendor_code, due_date, amount_tl, curr)

        upload.total_checks = len(rows)
        upload.new_checks = new_count
        upload.skipped_checks = skipped_count
        log_action(
            db, current_user.id, "create", "check_upload", entity_id=upload.id,
            details=f"Sedna çek içe aktarma: {new_count} yeni, {updated_count} güncel (vade/durum), "
                    f"{removed_dupes} mükerrer temizlendi, {skipped_count} atlandı",
            ip_address=ip,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Sedna çek içe aktarma DB hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Çek içe aktarma sırasında veritabanı hatası oluştu.")

    # Yeni/güncellenen çekleri MEVCUT banka hareketleriyle eşleştir: ekstre daha önce
    # yüklenmiş olabilir (matcher yalnız ekstre yüklemede çalışıyordu) — banka kanıtı
    # varsa çek "ödendi" olur (Sedna ödemeyi henüz işlememiş olsa bile).
    matched = 0
    try:
        matched = _match_checks_to_bank(db).get("matched", 0)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Sedna çek import sonrası banka eşleştirme hatası: %s", e)

    return {
        "upload_id": upload.id,
        "total_fetched": len(rows),
        "new_checks": new_count,
        "updated_checks": updated_count,
        "removed_dupes": removed_dupes,
        "skipped_checks": skipped_count,
        "matched_to_bank": matched,
    }


@router.post("/sedna-import")
def sedna_import_checks(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.checks", "use")),
):
    """Sedna verilen çek içe aktarma (tekil)."""
    result = run_check_import(db, current_user, get_client_ip(request))
    broadcast_finance_update(background_tasks, BroadcastModule.CHECKS, "upload")
    return result


# ─── Yükleme Geçmişi ────────────────────────────────────


@router.get("/uploads")
def list_uploads(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.checks", "view")),
):
    """Yükleme geçmişi."""
    uploads = (
        db.query(CheckUpload, User.first_name, User.last_name)
        .outerjoin(User, CheckUpload.uploaded_by == User.id)
        .order_by(desc(CheckUpload.uploaded_at))
        .all()
    )
    return [
        CheckUploadResponse(
            id=u.id,
            file_name=u.file_name,
            total_checks=u.total_checks,
            new_checks=u.new_checks,
            skipped_checks=u.skipped_checks,
            uploaded_by=u.uploaded_by,
            uploader_name=f"{fn or ''} {ln or ''}".strip() if fn or ln else None,
            uploaded_at=u.uploaded_at,
        ).model_dump()
        for u, fn, ln in uploads
    ]


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(
    upload_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.checks", "use")),
):
    """Yüklemeyi ve ilişkili çekleri sil."""
    upload = db.query(CheckUpload).filter(CheckUpload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Yükleme bulunamadı")

    if upload.file_url and os.path.exists(upload.file_url):
        os.remove(upload.file_url)

    log_action(
        db, current_user.id, "delete", "check_upload",
        entity_id=upload_id,
        details=f"Çek dosyası silindi: {upload.file_name}",
        ip_address=get_client_ip(request),
    )
    db.delete(upload)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CHECKS, "delete")


# ─── Çek Listesi ────────────────────────────────────────


@router.get("/")
def list_checks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(pending|paid|cancelled)$"),
    currency: Optional[str] = Query(None, pattern="^(TL|EUR|USD|GBP)$"),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, pattern="^(vendor_name|due_date|amount_tl)$"),
    sort_dir: Optional[str] = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.checks", "view")),
):
    """Çek listesi (sayfalanmış, filtrelenebilir, sıralanabilir)."""
    query = db.query(Check)

    if status_filter:
        query = query.filter(Check.status == status_filter)
    if currency:
        query = query.filter(Check.currency == currency)
    if search:
        s = search.strip()[:200].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{s}%"
        query = query.filter(
            (Check.vendor_name.ilike(pattern, escape="\\")) |
            (Check.check_no.ilike(pattern, escape="\\")) |
            (Check.vendor_code.ilike(pattern, escape="\\"))
        )

    # Sıralama
    sort_map = {
        "vendor_name": Check.vendor_name,
        "due_date": Check.due_date,
        "amount_tl": Check.amount_tl,
    }
    if sort_by and sort_by in sort_map:
        order_col = sort_map[sort_by]
        order_expr = desc(order_col) if sort_dir == "desc" else order_col
    else:
        order_expr = Check.due_date

    total = query.count()
    items = (
        query.order_by(order_expr, Check.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [CheckResponse.model_validate(c).model_dump() for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


# ─── Özet ────────────────────────────────────────────────


@router.get("/summary")
def checks_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.checks", "view")),
):
    """Çek özeti — toplam, bekleyen, ödenen + EUR karşılığı."""
    from datetime import date as dt_date

    from app.models.exchange_rate import ExchangeRate

    today = dt_date.today()

    total = db.query(func.count(Check.id)).scalar() or 0
    total_amount = db.query(func.coalesce(func.sum(Check.amount_tl), 0)).scalar()

    pending = db.query(func.count(Check.id)).filter(Check.status == "pending").scalar() or 0
    pending_amount = db.query(func.coalesce(func.sum(Check.amount_tl), 0)).filter(Check.status == "pending").scalar()

    overdue = db.query(func.count(Check.id)).filter(
        Check.status == "pending", Check.due_date < today
    ).scalar() or 0
    overdue_amount = db.query(func.coalesce(func.sum(Check.amount_tl), 0)).filter(
        Check.status == "pending", Check.due_date < today
    ).scalar()

    # EUR karşılığı: TL çekler kura bölünür, EUR çekler direkt eklenir
    pending_amount_eur = None
    # EUR çeklerin orijinal tutarı
    pending_eur_direct = float(
        db.query(func.coalesce(func.sum(Check.amount_currency), 0))
        .filter(Check.status == "pending", Check.currency == "EUR")
        .scalar()
    )
    # TL çeklerin toplamı
    pending_tl_only = float(
        db.query(func.coalesce(func.sum(Check.amount_tl), 0))
        .filter(Check.status == "pending", Check.currency != "EUR")
        .scalar()
    )
    latest_date = db.query(func.max(ExchangeRate.date)).scalar()
    if latest_date:
        eur_rate = db.query(ExchangeRate).filter(
            ExchangeRate.date == latest_date,
            ExchangeRate.currency_code == "EUR",
        ).first()
        if eur_rate and eur_rate.forex_selling and float(eur_rate.forex_selling) > 0:
            tl_as_eur = pending_tl_only / float(eur_rate.forex_selling)
            pending_amount_eur = round(tl_as_eur + pending_eur_direct, 2)
        elif pending_eur_direct > 0:
            # Kur yoksa sadece EUR çekleri göster
            pending_amount_eur = round(pending_eur_direct, 2)

    return {
        "total_count": total,
        "total_amount": float(total_amount),
        "pending_count": pending,
        "pending_amount": float(pending_amount),
        "pending_amount_eur": pending_amount_eur,
        "overdue_count": overdue,
        "overdue_amount": float(overdue_amount),
    }


# ─── Durum Güncelleme ───────────────────────────────────


@router.patch("/{check_id}/status")
def update_check_status(
    check_id: int,
    background_tasks: BackgroundTasks,
    new_status: str = Query(..., pattern="^(pending|paid|cancelled)$"),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.checks", "use")),
):
    """Çek durumunu güncelle."""
    from app.models.vendor_transaction import VendorTransaction

    check = db.query(Check).filter(Check.id == check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="Çek bulunamadı")

    approval_resp = check_approval(db, "finance.checks", check_id, current_user.id, "update", {"new_status": new_status})
    if approval_resp:
        return approval_resp

    old_status = check.status

    # Eşleştirilmiş çekin iptal edilmesi → eşleşmeyi de kaldır
    if new_status == "cancelled":
        # Cari eşleşmesi (match_number ile direkt bul)
        if check.match_number:
            matched_vtx = db.query(VendorTransaction).filter(
                VendorTransaction.match_number == check.match_number,
            ).first()
            if matched_vtx:
                matched_vtx.match_number = None
                matched_vtx.payment_method = None
            check.match_number = None
            check.matched_vendor_id = None

        # Banka eşleşmesini de kaldır
        if check.bank_transaction_id:
            btx = db.query(BankTransaction).filter(BankTransaction.id == check.bank_transaction_id).first()
            if btx:
                btx.match_number = None
            check.bank_transaction_id = None

    check.status = new_status

    status_labels = {"pending": "Bekliyor", "paid": "Ödendi", "cancelled": "İptal"}
    log_action(
        db, current_user.id, "update", "check",
        entity_id=check_id,
        details=f"Çek durumu: {status_labels.get(old_status, old_status)} → {status_labels.get(new_status, new_status)} (Çek No: {check.check_no})",
        ip_address=get_client_ip(request) if request else None,
    )
    db.commit()
    # finance_events'i güncelle
    bank_tx = None
    if check.bank_transaction_id:
        bank_tx = db.query(BankTransaction).filter(BankTransaction.id == check.bank_transaction_id).first()
    finance_event_svc.upsert_check(db, check, bank_tx)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CHECKS, "update")

    return {"ok": True, "status": new_status}


# ─── Otomatik Eşleştirme ────────────────────────────────


@router.post("/match-bank")
def auto_match_bank(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.checks", "use")),
):
    """Bekleyen çekleri banka işlemleriyle otomatik eşleştir."""
    result = _match_checks_to_bank(db)

    if result["matched"] > 0:
        log_action(
            db, current_user.id, "update", "check",
            details=f"Çek-banka otomatik eşleştirme: {result['matched']}/{result['total_pending']} çek eşleştirildi",
            ip_address=get_client_ip(request),
        )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CHECKS, "match")

    return result
