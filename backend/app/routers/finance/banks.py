"""Banka hesapları ve ekstre yönetimi — hesap CRUD, ekstre yükleme, işlem listeleme."""

import hashlib
import logging
import math
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip, upload_limiter
from app.models.bank_account import BankAccount
from app.models.bank_statement import BankStatement
from app.models.bank_transaction import BankTransaction
from app.models.user import User
from app.schemas.bank import (
    BankAccountCreate,
    BankAccountResponse,
    BankAccountUpdate,
    BankStatementResponse,
    BankTransactionResponse,
    ManualTransactionCreate,
)
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.services import bank_account_service
from app.routers.finance.bank_statement_import import (
    _post_upload_processing,
    _process_statement,
    _save_and_parse,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/banks")

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

    acc = bank_account_service.create_account(db, data.model_dump(), current_user.id)
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
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "create")
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

    bank_account_service.apply_account_update(db, acc, update_data)

    log_action(
        db, current_user.id, "update", "bank_account",
        entity_id=account_id,
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "update")
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
    bank_account_service.delete_account(db, acc)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "delete")


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

    # Faz 3 #22b: ekstre başlığı hesapla uyuşmalı — yanlış hesaba (hatta yanlış para
    # biriminde) yükleme sessizce kabul ediliyordu (denetim: dedup hesap-bazlı olduğundan
    # mükerrer de engellenmiyordu). Başlıkta IBAN/para birimi varsa doğrulanır.
    header = getattr(parsed, "header", None)
    if header is not None:
        h_iban = "".join((getattr(header, "iban", "") or "").split()).upper()
        a_iban = "".join((acc.iban or "").split()).upper()
        if h_iban and a_iban and h_iban != a_iban:
            raise HTTPException(
                status_code=400,
                detail=f"Ekstre IBAN'ı ({h_iban[-8:]}…) seçili hesapla uyuşmuyor — doğru hesabı seçin",
            )
        h_cur = (getattr(header, "currency", "") or "").strip().upper()
        if h_cur in ("TL",):
            h_cur = "TRY"
        if h_cur and h_cur != (acc.currency or "TRY").upper():
            raise HTTPException(
                status_code=400,
                detail=f"Ekstre para birimi ({h_cur}) hesabın para birimiyle ({acc.currency}) uyuşmuyor",
            )

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
                source=tx.source,
            ).model_dump()
            for tx in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


# ─── Manuel (ekstre-dışı) hareket ───────────────────────

@router.post("/accounts/{account_id}/manual-transaction", status_code=status.HTTP_201_CREATED)
def create_manual_transaction(
    account_id: int,
    data: ManualTransactionCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Ekstre-dışı (manuel) banka hareketi ekle — ekstresi henüz gelmemiş bir işlemi yansıtmak için.

    İlgili ekstre yüklenince bu satır o ekstrenin tarih aralığında OTOMATİK silinir
    (finance_event'i de invalidate edilir) → ekstre asıl kaynak olur, **çift kayıt olmaz**.
    Operasyonel düzeltme endpoint'i (dosya yükleme/eşleştirme gibi) — onay akışından muaf, audit'li.

    `amount` işaretlidir: negatif → hesaptan çıkış (bakiye düşer), pozitif → giriş.
    Yeni bakiye = hesabın güncel son bakiyesi + tutar.
    """
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    if not (data.description or "").strip():
        raise HTTPException(status_code=400, detail="Açıklama zorunlu")
    if not data.amount or float(data.amount) == 0:
        raise HTTPException(status_code=400, detail="Tutar sıfır olamaz")

    last_balance = (
        db.query(BankTransaction.balance)
        .filter(BankTransaction.account_id == acc.id, BankTransaction.balance.isnot(None))
        .order_by(desc(BankTransaction.date), desc(BankTransaction.id))
        .limit(1)
        .scalar()
    )
    new_balance = float(last_balance or 0) + float(data.amount)

    # Ekstre satırlarıyla ASLA çakışmayan benzersiz hash (statement hash'leri compute_tx_hash formatında)
    manual_hash = hashlib.sha256(
        f"manual:{acc.id}:{data.date}:{data.amount}:{uuid.uuid4().hex}".encode()
    ).hexdigest()

    db_tx = BankTransaction(
        account_id=acc.id,
        statement_id=None,
        date=data.date,
        description=f"[MANUEL] {data.description.strip()}",
        amount=data.amount,
        balance=new_balance,
        type="income" if float(data.amount) > 0 else "expense",
        tx_hash=manual_hash,
        source="manual",
        category_id=data.category_id,
    )
    db.add(db_tx)
    db.flush()
    finance_event_svc.upsert_bank_tx(db, db_tx, acc)
    log_action(
        db, current_user.id, "create", "bank_transaction", db_tx.id,
        f"Manuel hareket: {acc.iban} {float(data.amount):+.2f} {acc.currency} → bakiye {new_balance:.2f}",
        get_client_ip(request),
    )
    db.commit()
    db.refresh(db_tx)
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "create")
    return BankTransactionResponse(
        id=db_tx.id, account_id=db_tx.account_id, date=db_tx.date, receipt_no=db_tx.receipt_no,
        description=db_tx.description, amount=float(db_tx.amount),
        balance=float(db_tx.balance) if db_tx.balance is not None else None,
        type=db_tx.type, source=db_tx.source,
    ).model_dump()


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


# ─── Ekstre / İşlem Silme (Faz 3 #22c, 2026-07-12 — denetim C7) ──────────────
# Hatalı/yanlış hesaba yüklenmiş ekstrenin geri alma yolu. Gerçek veri silme →
# onay akışına TABİ (operasyonel eşleştirme istisnası DEĞİL). Tüm temizlik
# bank_release_service'te (executor'la ORTAK — D1-2).


@router.delete("/statements/{statement_id}")
def delete_statement(
    statement_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Ekstreyi ve tüm işlemlerini sil — bağlı eşleşmeler çözülür, FE'ler temizlenir."""
    stmt = db.query(BankStatement).filter(BankStatement.id == statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Ekstre bulunamadı")

    approval_resp = check_approval(
        db, "finance.banks", statement_id, current_user.id, "delete",
        {"op": "delete_statement"},
    )
    if approval_resp:
        return approval_resp

    from app.services.bank_release_service import delete_bank_statement

    totals = delete_bank_statement(db, stmt)
    if totals.get("needs_vendor_sync"):
        from app.utils.sync_vendor_fifo import sync_vendor_finance_events
        sync_vendor_finance_events(db)

    log_action(db, current_user.id, "delete", "bank_statement", statement_id,
               f"Ekstre silindi: {totals['transactions']} işlem · çözülen eşleşme "
               f"çek={totals['checks']} kredi={totals['credits']} avans={totals['advances']} "
               f"KK={totals['cc']} cari={totals['vendor']}",
               get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "delete")
    return {"ok": True, **{k: v for k, v in totals.items() if k != "needs_vendor_sync"}}


@router.delete("/transactions/{tx_id}")
def delete_transaction(
    tx_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """Tekil banka işlemini sil — YALNIZ eşleşmemiş satır (eşleşmişse önce geri alın)."""
    tx = db.query(BankTransaction).filter(BankTransaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")

    approval_resp = check_approval(
        db, "finance.banks", tx_id, current_user.id, "delete",
        {"op": "delete_transaction"},
    )
    if approval_resp:
        return approval_resp

    from app.services.bank_release_service import delete_bank_transaction

    try:
        delete_bank_transaction(db, tx)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "delete", "bank_transaction", tx_id,
               f"Banka işlemi silindi: {tx.date} {float(tx.amount):,.2f}",
               get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "delete")
    return {"ok": True}
