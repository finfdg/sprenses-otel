"""Banka ekstresi yükleme/işleme domain mantığı (HTTP endpoint'siz).

`banks.py` router'ından ayrıştırıldı (dosya boyutu + tek-sorumluluk). Ekstre dosyasını
doğrula+ayrıştır (`_save_and_parse`), işlemleri dedup ile hesaba kaydet (`_process_statement`),
yükleme sonrası bildirim + otomatik eşleştirme (`_post_upload_processing`). Router upload
endpoint'leri (`banks.py`) bu üç fonksiyonu çağırır. Bu modül router'dan import ETMEZ.
"""
import asyncio
import logging
import os
import re
import uuid
from typing import List

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.constants import BroadcastModule, WSEvent
from app.models.bank_account import BankAccount
from app.models.bank_statement import BankStatement
from app.models.bank_transaction import BankTransaction
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.schemas.bank import UploadResult
from app.utils.audit import log_action
from app.utils.bank_parser import compute_tx_hash, parse_excel, parse_pdf
from app.utils.file_validation import validate_upload_file
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.matching_service import _match_cc_to_bank, _match_checks_to_bank, _match_credits_to_bank
from app.utils.notification import _notification_to_ws_event, create_notifications
from app.utils.push import send_push_to_user
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "uploads", "bank_statements")


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_banks_viewer_ids(db: Session) -> List[int]:
    """finance.banks modülüne görüntüleme yetkisi olan kullanıcı ID'lerini döndür."""
    banks_mod = db.query(Module).filter(Module.code == "finance.banks").first()
    if not banks_mod:
        return []

    rows = (
        db.query(User.id)
        .join(RoleModulePermission, User.role_id == RoleModulePermission.role_id)
        .filter(
            RoleModulePermission.module_id == banks_mod.id,
            RoleModulePermission.can_view == True,
            User.is_active == True,
        )
        .all()
    )
    return [r.id for r in rows]


async def _notify_bank_upload(
    db: Session, viewer_ids: List[int], event: dict, uploader_id: int,
    background_tasks: BackgroundTasks,
) -> None:
    """Banka ekstresi yükleme bildirimini DB + WS + Push ile gönder.

    - DB'ye bildirim kaydı oluştur (yükleyen hariç)
    - Online ve ön plandaki kullanıcılar → WS toast + WS notification (çan)
    - Arka plandaki veya çevrimdışı kullanıcılar → Push bildirim

    Push gönderimi `background_tasks` ile yapılır — yanıt dönüşünü bloklamaz.
    Push, push servisine senkron HTTP isteği yapar; isteğin içinde çağrılırsa
    (özellikle çok sayıda eski/ölü abonelik varsa) yükleme yavaşlar.
    """
    try:
        account_id = event.get("account_id", "")
        link = f"/dashboard/finans/bankalar?account={account_id}"
        notif_title = "Yeni Banka Ekstresi"
        bank_name = event.get('account_bank_name', '')
        currency = event.get('account_currency', '')
        iban_last4 = (event.get('account_iban', '') or '')[-4:]
        new_tx = event.get('new_transactions', 0)
        notif_body = (
            f"{bank_name} {currency} (*{iban_last4}) hesabına ekstre yüklendi — "
            f"{new_tx} yeni işlem"
        )

        # Tüm yetkili kullanıcılara bildirim oluştur (yükleyen dahil — çanda görsün)
        notif_user_ids = viewer_ids

        # DB'ye bildirim kayıtları oluştur
        notifs = []
        if notif_user_ids:
            notifs = create_notifications(
                db, notif_user_ids,
                type="bank_statement_uploaded",
                title=notif_title,
                body=notif_body,
                link=link,
            )
            db.commit()

        # Bildirim gönder
        notif_map = {n.user_id: n for n in notifs}

        for uid in viewer_ids:
            is_online = manager.is_online(uid)
            is_bg = manager.is_background(uid) if is_online else False

            if is_online and not is_bg:
                # Ön planda — WS toast gönder
                await manager.send_to_user(uid, event)
                # Çan bildirimi (yükleyen hariç)
                notif = notif_map.get(uid)
                if notif:
                    await manager.send_to_user(uid, _notification_to_ws_event(notif))
            elif uid != uploader_id:
                # Arka planda veya çevrimdışı — Push bildirim (yanıt dönüşünü
                # bloklamaması için arka plana al; senkron HTTP isteği yapar)
                background_tasks.add_task(
                    send_push_to_user,
                    uid,
                    notif_title,
                    notif_body,
                    link,
                    f"bank-stmt-{event.get('statement_id', '')}",
                )
    except Exception as e:
        logger.error("Ekstre bildirim hatası: %s", e)


async def _save_and_parse(file: UploadFile):
    """Dosyayı doğrula, kaydet ve ayrıştır. (file_path, parsed, file_type, unique_name) döner."""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "xlsx", "xls"):
        raise HTTPException(status_code=400, detail="Sadece PDF ve Excel dosyaları kabul edilir")

    # MIME + boyut doğrulama
    await validate_upload_file(file, allowed_types=["pdf", "excel"])

    file_type = "pdf" if ext == "pdf" else "xlsx"

    _ensure_upload_dir()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        content = file.file.read()
        f.write(content)

    try:
        # CPU-yoğun parse'ı threadpool'a al → event loop bloke olmaz (eşzamanlı istekler beklemez)
        if file_type == "pdf":
            parsed = await asyncio.to_thread(parse_pdf, file_path)
        else:
            parsed = await asyncio.to_thread(parse_excel, file_path)
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Dosya ayrıştırılamadı. Lütfen geçerli bir banka ekstresi yükleyin.")

    if not parsed.transactions:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Dosyada işlem bulunamadı")

    return file_path, parsed, file_type, unique_name


def _process_statement(
    db: Session, acc: BankAccount, parsed, file, file_path: str,
    file_type: str, unique_name: str, current_user: User, ip_address: str,
) -> dict:
    """Ayrıştırılmış veriyi hesaba kaydet. UploadResult dict döner."""
    try:
        header = parsed.header

        # Header'dan hesap bilgilerini güncelle (boş olanları doldur)
        if header.holder_name and not acc.holder_name:
            acc.holder_name = header.holder_name
        if header.branch_name and not acc.branch_name:
            acc.branch_name = header.branch_name
        if header.account_no and not acc.account_no:
            acc.account_no = header.account_no

        # Ekstre kaydı
        stmt = BankStatement(
            account_id=acc.id,
            file_name=file.filename or unique_name,
            file_url=file_path,
            file_type=file_type,
            period_start=header.period_start,
            period_end=header.period_end,
            uploaded_by=current_user.id,
        )
        db.add(stmt)
        db.flush()

        # ── Manuel (ekstre-dışı) hareketleri temizle (dedup) ──────────────────
        # Bu ekstrenin kapsadığı tarih aralığında daha önce ELLE eklenmiş satırlar artık
        # ekstreden geleceği için silinir → ÇİFT KAYIT OLMAZ. finance_event'leri de
        # invalidate edilir. Bu, gerçek dedup setleri kurulmadan ÖNCE yapılır ki bakiye
        # bazlı mükerrer kontrol manuel satırı "mevcut" sanıp gerçek satırı atlamasın.
        manual_purged = 0
        _stmt_dates = [t.date for t in parsed.transactions if t.date]
        if _stmt_dates:
            _dmin, _dmax = min(_stmt_dates), max(_stmt_dates)
            _manual_rows = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.account_id == acc.id,
                    BankTransaction.source == "manual",
                    BankTransaction.date >= _dmin,
                    BankTransaction.date <= _dmax,
                )
                .all()
            )
            for _mr in _manual_rows:
                finance_event_svc.invalidate(db, "bank", _mr.id)
                db.delete(_mr)
            manual_purged = len(_manual_rows)
            if manual_purged:
                db.flush()
                logger.info(
                    "Manuel hareket temizlendi (hesap=%s): %d satır [%s..%s]",
                    acc.iban, manual_purged, _dmin, _dmax,
                )

        # Mevcut hash'leri çek
        existing_hashes = set(
            row[0] for row in
            db.query(BankTransaction.tx_hash)
            .filter(BankTransaction.account_id == acc.id)
            .all()
        )

        new_count = 0
        skipped_count = 0

        # DB'deki mevcut bakiyeleri set olarak tut (tarih+tutar+bakiye = benzersiz işlem)
        existing_balances = set()
        for row in db.query(
            BankTransaction.date, BankTransaction.amount, BankTransaction.balance
        ).filter(BankTransaction.account_id == acc.id).all():
            existing_balances.add((row.date, float(row.amount), float(row.balance or 0)))

        # Açıklama bazlı mükerrer kontrolü (tarih+tutar+normalize açıklama)
        def _normalize_desc(desc: str) -> str:
            """Açıklamayı normalize et: maskeli kart numarası, boşluk, büyük/küçük harf farklarını yok say.

            Örn: '552879******4051 Kredi Kart Ödeme' ve '5528791518354051 Kredi Kart Ödeme'
            her ikisi de → '5528794051 kredi kart ödeme' olur.
            """
            s = (desc or "").strip().lower()
            # Kart numarası normalizasyonu: 12+ karakter uzunluğundaki rakam/yıldız dizilerini
            # ilk 6 + son 4 rakama indir (maskeli ve tam numara aynı sonucu verir)
            def _norm_card(m: re.Match) -> str:
                digits = re.sub(r'[^0-9]', '', m.group(0))
                if len(digits) >= 6:
                    return digits[:6] + digits[-4:]
                return m.group(0)
            s = re.sub(r'[\d*]{12,}', _norm_card, s)
            s = re.sub(r'\s+', ' ', s)      # Çoklu boşlukları teke indir
            return s

        existing_desc_keys = set()
        for row in db.query(
            BankTransaction.date, BankTransaction.amount, BankTransaction.description
        ).filter(BankTransaction.account_id == acc.id).all():
            existing_desc_keys.add((row.date, float(row.amount), _normalize_desc(row.description)))

        for tx in parsed.transactions:
            # Bakiye bazlı mükerrer kontrolü — aynı tarih+tutar+bakiye = aynı işlem
            balance_key = (tx.date, float(tx.amount), float(tx.balance or 0))
            if balance_key in existing_balances:
                skipped_count += 1
                continue

            # Açıklama bazlı FALLBACK mükerrer kontrolü — yalnızca bakiye yoksa/sıfırsa devreye girer
            # Bakiye varsa ve balance_key eşleşmediyse bu farklı bir işlemdir (ör. aynı gün
            # iki ayrı EFT: tarih+tutar+açıklama aynı olsa da bakiyeleri farklıdır, ikisi de kaydedilmeli)
            desc_key = (tx.date, float(tx.amount), _normalize_desc(tx.description))
            if (tx.balance is None or float(tx.balance) == 0) and desc_key in existing_desc_keys:
                skipped_count += 1
                continue

            # Hash bazlı mükerrer kontrolü (fallback)
            final_hash = tx.tx_hash
            if final_hash in existing_hashes:
                # Aynı hash → seq ile benzersiz hash üret
                for seq in range(1, 20):
                    candidate = compute_tx_hash(tx.date, tx.receipt_no, tx.amount, tx.description, seq)
                    if candidate not in existing_hashes:
                        final_hash = candidate
                        break
                else:
                    skipped_count += 1
                    continue

            # Son kontrol
            if final_hash in existing_hashes:
                skipped_count += 1
                continue

            db_tx = BankTransaction(
                account_id=acc.id,
                statement_id=stmt.id,
                date=tx.date,
                receipt_no=tx.receipt_no,
                description=tx.description,
                amount=tx.amount,
                balance=tx.balance,
                type=tx.type,
                tx_hash=final_hash,
            )
            db.add(db_tx)
            db.flush()
            # Finance event upsert — yeni işlem nakit akıma eklenir
            finance_event_svc.upsert_bank_tx(db, db_tx, acc)
            existing_hashes.add(final_hash)
            existing_balances.add(balance_key)
            existing_desc_keys.add(desc_key)
            new_count += 1

        stmt.total_transactions = len(parsed.transactions)
        stmt.new_transactions = new_count
        stmt.skipped_transactions = skipped_count

        log_action(
            db, current_user.id, "create", "bank_statement",
            entity_id=stmt.id,
            details=f"{file.filename}: {new_count} yeni, {skipped_count} mükerrer ({acc.iban})",
            ip_address=ip_address,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Banka ekstresi kaydetme hatası (hesap=%s): %s", acc.iban, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ekstre kaydedilirken bir veritabanı hatası oluştu. Lütfen tekrar deneyin.")

    _result = UploadResult(
        statement_id=stmt.id,
        file_name=file.filename or unique_name,
        total_transactions=len(parsed.transactions),
        new_transactions=new_count,
        skipped_transactions=skipped_count,
        account_iban=acc.iban,
        account_currency=acc.currency,
    ).model_dump()
    _result["manual_purged"] = manual_purged  # ekstre yüklenince temizlenen manuel satır sayısı
    return _result


async def _post_upload_processing(
    db: Session,
    acc: BankAccount,
    result: dict,
    current_user: User,
    background_tasks: BackgroundTasks,
):
    """Ekstre yükleme sonrası ortak işlemler: WS bildirim + otomatik eşleştirmeler."""
    # Görüntüleme yetkisi olan kullanıcılara WS + Push bildirim gönder
    viewer_ids = _get_banks_viewer_ids(db)
    if viewer_ids:
        ws_event = {
            "type": WSEvent.BANK_STATEMENT_UPLOADED,
            "account_id": acc.id,
            "account_bank_name": acc.bank_name,
            "statement_id": result.get("statement_id"),
            "file_name": result.get("file_name"),
            "account_iban": result.get("account_iban"),
            "account_currency": result.get("account_currency"),
            "new_transactions": result.get("new_transactions"),
            "skipped_transactions": result.get("skipped_transactions"),
            "uploader_name": f"{current_user.first_name} {current_user.last_name}",
        }
        await _notify_bank_upload(db, viewer_ids, ws_event, current_user.id, background_tasks)

    # Otomatik eşleştirmeler — her biri SAVEPOINT ile izole; biri başarısız olursa diğerleri etkilenmez
    for match_fn, label, key in [
        (_match_checks_to_bank, "Çek-banka", "checks_matched"),
        (_match_credits_to_bank, "Kredi-banka", "credits_matched"),
        (_match_cc_to_bank, "Kredi kartı-banka", "cc_matched"),
    ]:
        try:
            nested = db.begin_nested()
            match_result = match_fn(db)
            if match_result["matched"] > 0:
                nested.commit()
                db.commit()
                result[key] = match_result["matched"]
            else:
                nested.rollback()
        except Exception as e:
            db.rollback()
            logger.error("%s otomatik eşleştirme hatası: %s", label, e, exc_info=True)

    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "upload")
