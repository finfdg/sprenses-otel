"""Banka hesapları ve ekstre yönetimi — hesap CRUD, ekstre yükleme, işlem listeleme."""

import logging
import math
import os
import uuid
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status

logger = logging.getLogger(__name__)
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip, upload_limiter
from app.models.bank_account import BankAccount
from app.models.bank_statement import BankStatement
from app.models.bank_transaction import BankTransaction
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.routers.finance.banks_cc_match import _match_cc_to_bank
from app.routers.finance.checks import _match_checks_to_bank
from app.routers.finance.krediler import _match_credits_to_bank
from app.schemas.bank import (
    BankAccountCreate,
    BankAccountResponse,
    BankAccountUpdate,
    BankStatementResponse,
    BankTransactionResponse,
    UploadResult,
)
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.bank_parser import parse_excel, parse_pdf
from app.utils.file_validation import validate_upload_file
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.notification import _notification_to_ws_event, create_notifications
from app.utils.push import send_push_to_user
from app.websocket.manager import manager


async def _notify_bank_upload(
    db: Session, viewer_ids: List[int], event: dict, uploader_id: int,
) -> None:
    """Banka ekstresi yükleme bildirimini DB + WS + Push ile gönder.

    - DB'ye bildirim kaydı oluştur (yükleyen hariç)
    - Online ve ön plandaki kullanıcılar → WS toast + WS notification (çan)
    - Arka plandaki veya çevrimdışı kullanıcılar → Push bildirim
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
                # Arka planda veya çevrimdışı — Push bildirim gönder
                send_push_to_user(
                    uid,
                    notif_title,
                    notif_body,
                    link,
                    f"bank-stmt-{event.get('statement_id', '')}",
                )
    except Exception as e:
        logger.error("Ekstre bildirim hatası: %s", e)

router = APIRouter(prefix="/banks")

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


# ─── Hesap CRUD ──────────────────────────────────────────

@router.get("/accounts/")
def list_accounts(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.banks", "view")),
):
    """Tüm banka hesaplarını listele."""
    accounts = db.query(BankAccount).order_by(BankAccount.bank_name, BankAccount.currency).all()

    if not accounts:
        return []

    account_ids = [a.id for a in accounts]

    # İşlem sayılarını toplu al
    count_rows = (
        db.query(BankTransaction.account_id, func.count(BankTransaction.id))
        .filter(BankTransaction.account_id.in_(account_ids))
        .group_by(BankTransaction.account_id)
        .all()
    )
    count_map = {acc_id: cnt for acc_id, cnt in count_rows}

    # Son bakiyeleri toplu al (window function ile)
    last_tx_subq = (
        db.query(
            BankTransaction.account_id,
            BankTransaction.balance,
            func.row_number().over(
                partition_by=BankTransaction.account_id,
                order_by=[desc(BankTransaction.date), desc(BankTransaction.id)],
            ).label("rn"),
        )
        .filter(
            BankTransaction.account_id.in_(account_ids),
            BankTransaction.balance.isnot(None),
        )
        .subquery()
    )
    last_balance_rows = (
        db.query(last_tx_subq.c.account_id, last_tx_subq.c.balance)
        .filter(last_tx_subq.c.rn == 1)
        .all()
    )
    balance_map = {acc_id: bal for acc_id, bal in last_balance_rows}

    # Son ekstre yükleme tarihlerini toplu al
    from sqlalchemy import Date, cast
    stmt_date_rows = (
        db.query(
            BankStatement.account_id,
            func.max(cast(BankStatement.uploaded_at, Date)).label("last_date"),
        )
        .filter(BankStatement.account_id.in_(account_ids))
        .group_by(BankStatement.account_id)
        .all()
    )
    stmt_date_map = {acc_id: d for acc_id, d in stmt_date_rows}

    result = []
    for acc in accounts:
        result.append(BankAccountResponse(
            id=acc.id,
            bank_name=acc.bank_name,
            branch_name=acc.branch_name,
            account_no=acc.account_no,
            iban=acc.iban,
            currency=acc.currency,
            holder_name=acc.holder_name,
            is_active=acc.is_active,
            created_at=acc.created_at,
            blocked_amount=float(acc.blocked_amount) if acc.blocked_amount is not None else None,
            transaction_count=count_map.get(acc.id, 0),
            last_balance=float(balance_map[acc.id]) if acc.id in balance_map and balance_map[acc.id] is not None else None,
            last_statement_date=stmt_date_map.get(acc.id),
        ).model_dump())

    return result


@router.post("/accounts/", status_code=status.HTTP_201_CREATED)
def create_account(
    data: BankAccountCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Yeni banka hesabı oluştur."""
    approval_resp = check_approval(db, "finance.banks", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    # IBAN tekrarı ön-kontrolü — autoflush kaynaklı hataları önler
    if data.iban:
        existing = db.query(BankAccount).filter(BankAccount.iban == data.iban).first()
        if existing:
            raise HTTPException(status_code=400, detail="Bu IBAN zaten kayıtlı")

    acc = BankAccount(
        bank_name=data.bank_name,
        branch_name=data.branch_name,
        account_no=data.account_no,
        iban=data.iban,
        currency=data.currency,
        holder_name=data.holder_name,
        blocked_amount=data.blocked_amount,
        created_by=current_user.id,
    )
    db.add(acc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Bu IBAN zaten kayıtlı")

    log_action(
        db, current_user.id, "create", "bank_account",
        entity_id=acc.id,
        details=f"{acc.bank_name} - {acc.iban}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, "banks", "create")
    db.refresh(acc)

    return BankAccountResponse(
        id=acc.id, bank_name=acc.bank_name, branch_name=acc.branch_name,
        account_no=acc.account_no, iban=acc.iban, currency=acc.currency,
        holder_name=acc.holder_name, is_active=acc.is_active,
        blocked_amount=float(acc.blocked_amount) if acc.blocked_amount is not None else None,
        created_at=acc.created_at, transaction_count=0, last_balance=None, last_statement_date=None,
    ).model_dump()


@router.patch("/accounts/{account_id}")
def update_account(
    account_id: int,
    data: BankAccountUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Banka hesabını güncelle."""
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")

    approval_resp = check_approval(db, "finance.banks", account_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp

    update_data = data.model_dump(exclude_unset=True)
    if "iban" in update_data and update_data["iban"] != acc.iban:
        existing = db.query(BankAccount).filter(
            BankAccount.iban == update_data["iban"],
            BankAccount.id != account_id,
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Bu IBAN zaten kayıtlı")

    for key, value in update_data.items():
        setattr(acc, key, value)

    log_action(
        db, current_user.id, "update", "bank_account",
        entity_id=account_id,
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, "banks", "update")
    db.refresh(acc)

    return {"detail": "Hesap güncellendi"}


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Banka hesabını sil (cascade: ekstre + işlemler de silinir)."""
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")

    approval_resp = check_approval(db, "finance.banks", account_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    log_action(
        db, current_user.id, "delete", "bank_account",
        entity_id=account_id,
        details=f"{acc.bank_name} - {acc.iban}",
        ip_address=get_client_ip(request),
    )
    db.delete(acc)
    db.commit()
    broadcast_finance_update(background_tasks, "banks", "delete")


# ─── Ortak Ekstre Yükleme (IBAN otomatik tespit) ────────

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
        if file_type == "pdf":
            parsed = parse_pdf(file_path)
        else:
            parsed = parse_excel(file_path)
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

        # Mevcut hash'leri çek
        existing_hashes = set(
            row[0] for row in
            db.query(BankTransaction.tx_hash)
            .filter(BankTransaction.account_id == acc.id)
            .all()
        )

        new_count = 0
        skipped_count = 0

        from app.utils.bank_parser import compute_tx_hash

        # DB'deki mevcut bakiyeleri set olarak tut (tarih+tutar+bakiye = benzersiz işlem)
        existing_balances = set()
        for row in db.query(
            BankTransaction.date, BankTransaction.amount, BankTransaction.balance
        ).filter(BankTransaction.account_id == acc.id).all():
            existing_balances.add((row.date, float(row.amount), float(row.balance or 0)))

        # Açıklama bazlı mükerrer kontrolü (tarih+tutar+normalize açıklama)
        import re

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

    return UploadResult(
        statement_id=stmt.id,
        file_name=file.filename or unique_name,
        total_transactions=len(parsed.transactions),
        new_transactions=new_count,
        skipped_transactions=skipped_count,
        account_iban=acc.iban,
        account_currency=acc.currency,
    ).model_dump()


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
            "type": "bank_statement_uploaded",
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
        await _notify_bank_upload(db, viewer_ids, ws_event, current_user.id)

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

    broadcast_finance_update(background_tasks, "banks", "upload")


@router.post("/upload")
async def upload_statement_auto(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Ekstre yükle — IBAN'dan hesabı otomatik tespit et, mükerrerleri atla."""
    upload_limiter.check(f"upload-{get_client_ip(request)}")
    file_path, parsed, file_type, unique_name = await _save_and_parse(file)

    # IBAN'dan hesap bul
    header = parsed.header
    acc = None
    if header.iban:
        acc = db.query(BankAccount).filter(BankAccount.iban == header.iban).first()

    if not acc:
        # Dosyayı temizle
        if os.path.exists(file_path):
            os.remove(file_path)
        iban_msg = f" (IBAN: {header.iban})" if header.iban else ""
        raise HTTPException(
            status_code=400,
            detail=f"Dosyadaki IBAN ile eşleşen hesap bulunamadı{iban_msg}. Lütfen önce hesabı ekleyin.",
        )

    result = _process_statement(
        db, acc, parsed, file, file_path, file_type, unique_name,
        current_user, get_client_ip(request),
    )
    await _post_upload_processing(db, acc, result, current_user, background_tasks)
    return result


@router.post("/accounts/{account_id}/upload")
async def upload_statement(
    account_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Belirli hesaba ekstre yükle, işlemleri ayrıştır, mükerrerleri atla."""
    upload_limiter.check(f"upload-{get_client_ip(request)}")
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")

    file_path, parsed, file_type, unique_name = await _save_and_parse(file)

    result = _process_statement(
        db, acc, parsed, file, file_path, file_type, unique_name,
        current_user, get_client_ip(request),
    )
    await _post_upload_processing(db, acc, result, current_user, background_tasks)
    return result


# ─── İşlem Listesi ───────────────────────────────────────

@router.get("/accounts/{account_id}/transactions")
def list_transactions(
    account_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.banks", "view")),
):
    """Hesap işlemlerini listele (sayfalanmış)."""
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")

    query = db.query(BankTransaction).filter(BankTransaction.account_id == account_id)
    total = query.count()

    items = (
        query.order_by(desc(BankTransaction.date), desc(BankTransaction.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            BankTransactionResponse(
                id=tx.id,
                account_id=tx.account_id,
                date=tx.date,
                receipt_no=tx.receipt_no,
                description=tx.description,
                amount=float(tx.amount),
                balance=float(tx.balance) if tx.balance is not None else None,
                type=tx.type,
            ).model_dump()
            for tx in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


# ─── Ekstre Geçmişi ─────────────────────────────────────

@router.get("/accounts/{account_id}/statements")
def list_statements(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.banks", "view")),
):
    """Hesap ekstre yükleme geçmişi."""
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")

    stmts = (
        db.query(BankStatement)
        .filter(BankStatement.account_id == account_id)
        .order_by(desc(BankStatement.uploaded_at))
        .all()
    )

    return [
        BankStatementResponse(
            id=s.id,
            account_id=s.account_id,
            file_name=s.file_name,
            file_type=s.file_type,
            period_start=s.period_start,
            period_end=s.period_end,
            total_transactions=s.total_transactions,
            new_transactions=s.new_transactions,
            skipped_transactions=s.skipped_transactions,
            uploaded_at=s.uploaded_at,
        ).model_dump()
        for s in stmts
    ]
