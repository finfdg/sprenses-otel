"""Kredi kartı ekstre yönetimi — PDF yükleme ve listeleme."""

import asyncio
import json
import logging
import os
import uuid

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip, upload_limiter
from app.models.credit_card_statement import CreditCardStatement, CreditCardTransaction
from app.models.credit_product import CreditProduct
from app.models.user import User
from app.schemas.credit_card import (
    CCStatementListItem,
    CCStatementResponse,
    CCStatementUploadResult,
    CCTransactionResponse,
)
from app.utils.audit import log_action
from app.utils.cc_statement_parser import parse_cc_statement
from app.utils.file_validation import validate_upload_file
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc

router = APIRouter(prefix="/krediler/kart")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "uploads", "cc_statements")


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---- Auto Upload (kart otomatik algılama) ----------------------------------

@router.post("/auto-upload", status_code=status.HTTP_201_CREATED)
async def auto_upload_statement(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Ekstre PDF yükle — kart numarasından otomatik algıla."""
    contents = await validate_upload_file(file, allowed_types=["pdf"])

    _ensure_upload_dir()
    ext = os.path.splitext(file.filename or ".pdf")[1]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)

    try:
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        logger.error("PDF dosya kaydetme hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Dosya kaydedilemedi. Lütfen tekrar deneyin.")

    # PDF parse — CPU-yoğun, threadpool'a al → event loop bloke olmaz (eşzamanlı istekler beklemez)
    try:
        parsed = await asyncio.to_thread(parse_cc_statement, file_path)
    except Exception:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="PDF okunamadı. Lütfen geçerli bir banka ekstresi yükleyin.")

    if not parsed.kart_no:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="PDF'den kart numarası okunamadı")

    # Son 4 hane ile kartı bul
    parsed_last4 = parsed.kart_no.replace(" ", "").replace("-", "").replace("*", "")[-4:]

    all_cards = db.query(CreditProduct).filter(CreditProduct.type == "kredi_karti").all()
    matched_product = None
    for card in all_cards:
        if card.details:
            try:
                details = json.loads(card.details)
                if details.get("kart_no_son4") == parsed_last4:
                    matched_product = card
                    break
            except (json.JSONDecodeError, TypeError):
                logger.debug("Kart detayları parse edilemedi: product_id=%s", card.id)

    if not matched_product:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=400,
            detail=f"*{parsed_last4} numaralı kart sistemde bulunamadı. Önce kartı ekleyin.",
        )

    # Tarih kontrol
    if not parsed.kesim_tarihi:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Ekstre kesim tarihi PDF'den okunamadı")

    if not parsed.son_odeme_tarihi:
        from datetime import timedelta
        parsed.son_odeme_tarihi = parsed.kesim_tarihi + timedelta(days=5)

    # Aynı dönem kontrolü
    existing = db.query(CreditCardStatement).filter(
        CreditCardStatement.credit_product_id == matched_product.id,
        CreditCardStatement.kesim_tarihi == parsed.kesim_tarihi,
    ).first()
    if existing:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=409,
            detail=f"{matched_product.name} için bu dönem zaten yüklü (Kesim: {parsed.kesim_tarihi})",
        )

    # Kaydet
    stmt = CreditCardStatement(
        credit_product_id=matched_product.id,
        ekstre_no=parsed.ekstre_no or None,
        kesim_tarihi=parsed.kesim_tarihi,
        son_odeme_tarihi=parsed.son_odeme_tarihi,
        onceki_bakiye=parsed.onceki_bakiye,
        donem_harcama=parsed.donem_harcama,
        faiz_ucret=parsed.faiz_ucret,
        donem_odeme=parsed.donem_odeme,
        toplam_borc=parsed.toplam_borc,
        asgari_odeme=parsed.asgari_odeme,
        file_name=file.filename,
        file_url=file_path,
        uploaded_by=current_user.id,
    )
    db.add(stmt)
    db.flush()

    for tx in parsed.transactions:
        db.add(CreditCardTransaction(
            statement_id=stmt.id,
            islem_tarihi=tx.islem_tarihi,
            aciklama=tx.aciklama,
            kategori=tx.kategori,
            taksit_bilgi=tx.taksit_bilgi,
            tutar=tx.tutar,
            is_credit=tx.is_credit,
            bonus=tx.bonus,
        ))

    matched_product.remaining_amount = parsed.toplam_borc

    log_action(
        db, current_user.id, "create", "cc_statement",
        entity_id=stmt.id,
        details=f"Ekstre yüklendi: {matched_product.name} | Kesim: {parsed.kesim_tarihi} | ₺{parsed.toplam_borc:,.2f}",
        ip_address=get_client_ip(request),
    )
    finance_event_svc.upsert_cc_statement(db, stmt, matched_product)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "upload")

    return CCStatementUploadResult(
        statement_id=stmt.id,
        kart_no=parsed.kart_no,
        kesim_tarihi=parsed.kesim_tarihi,
        toplam_borc=parsed.toplam_borc,
        transaction_count=len(parsed.transactions),
        card_name=matched_product.name,
    ).model_dump()


# ---- Upload (belirli kart) ------------------------------------------------

@router.post("/{product_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_statement(
    product_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Kredi kartı ekstre PDF'i yükle ve işle."""
    upload_limiter.check(f"upload-{get_client_ip(request)}")
    # Urun kontrol
    product = db.query(CreditProduct).filter(
        CreditProduct.id == product_id,
        CreditProduct.type == "kredi_karti",
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi kartı bulunamadı")

    contents = await validate_upload_file(file, allowed_types=["pdf"])

    # Dosyayi kaydet
    _ensure_upload_dir()
    ext = os.path.splitext(file.filename or ".pdf")[1]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)

    try:
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        logger.error("PDF dosya kaydetme hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Dosya kaydedilemedi. Lütfen tekrar deneyin.")

    # PDF parse — CPU-yoğun, threadpool'a al → event loop bloke olmaz (eşzamanlı istekler beklemez)
    try:
        parsed = await asyncio.to_thread(parse_cc_statement, file_path)
    except Exception:
        # Dosyayi temizle
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="PDF okunamadı. Lütfen geçerli bir banka ekstresi yükleyin.")

    # Kart numarasi eslestirme (son 4 hane)
    if parsed.kart_no:
        parsed_last4 = parsed.kart_no.replace(" ", "").replace("-", "")[-4:]
        # CreditProduct details JSON'inda kart_no_son4 alani var
        product_details = None
        if product.details:
            try:
                product_details = json.loads(product.details)
            except (json.JSONDecodeError, TypeError):
                logger.debug("Kart detayları parse edilemedi: product_id=%s", product.id)

        if product_details and product_details.get("kart_no_son4"):
            if parsed_last4 != product_details["kart_no_son4"]:
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise HTTPException(
                    status_code=400,
                    detail=f"Kart numarası eşleşmiyor. PDF: ...{parsed_last4}, Beklenen: ...{product_details['kart_no_son4']}",
                )

    # Tarih kontrol
    if not parsed.kesim_tarihi:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Ekstre kesim tarihi PDF'den okunamadı")

    # Son ödeme tarihi yoksa kesim + 5 gün olarak hesapla
    if not parsed.son_odeme_tarihi:
        from datetime import timedelta
        parsed.son_odeme_tarihi = parsed.kesim_tarihi + timedelta(days=5)

    # Aynı dönem için ekstre var mı?
    existing = db.query(CreditCardStatement).filter(
        CreditCardStatement.credit_product_id == product_id,
        CreditCardStatement.kesim_tarihi == parsed.kesim_tarihi,
    ).first()
    if existing:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=409,
            detail=f"Bu dönem için zaten bir ekstre mevcut (Kesim: {parsed.kesim_tarihi})",
        )

    # Ekstre oluştur
    stmt = CreditCardStatement(
        credit_product_id=product_id,
        ekstre_no=parsed.ekstre_no or None,
        kesim_tarihi=parsed.kesim_tarihi,
        son_odeme_tarihi=parsed.son_odeme_tarihi,
        onceki_bakiye=parsed.onceki_bakiye,
        donem_harcama=parsed.donem_harcama,
        faiz_ucret=parsed.faiz_ucret,
        donem_odeme=parsed.donem_odeme,
        toplam_borc=parsed.toplam_borc,
        asgari_odeme=parsed.asgari_odeme,
        file_name=file.filename,
        file_url=f"/uploads/cc_statements/{safe_name}",
        uploaded_by=current_user.id,
    )
    db.add(stmt)
    db.flush()

    # İşlemleri oluştur
    for tx in parsed.transactions:
        db.add(CreditCardTransaction(
            statement_id=stmt.id,
            islem_tarihi=tx.islem_tarihi,
            aciklama=tx.aciklama,
            kategori=tx.kategori,
            taksit_bilgi=tx.taksit_bilgi,
            tutar=tx.tutar,
            is_credit=tx.is_credit,
            bonus=tx.bonus,
        ))

    # Urunun kalan borcunu guncelle
    product.remaining_amount = parsed.toplam_borc

    log_action(
        db, current_user.id, "create", "credit_card_statement",
        entity_id=stmt.id,
        details=f"Kredi kartı ekstresi yüklendi: {file.filename} ({len(parsed.transactions)} islem)",
        ip_address=get_client_ip(request),
    )
    finance_event_svc.upsert_cc_statement(db, stmt, product)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "upload")
    db.refresh(stmt)

    return CCStatementUploadResult(
        statement_id=stmt.id,
        kart_no=parsed.kart_no,
        kesim_tarihi=parsed.kesim_tarihi,
        toplam_borc=parsed.toplam_borc,
        transaction_count=len(parsed.transactions),
    ).model_dump()


# ---- List -------------------------------------------------------------------

@router.get("/{product_id}/statements")
def list_statements(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Kredi kartı ekstrelerini listele."""
    product = db.query(CreditProduct).filter(
        CreditProduct.id == product_id,
        CreditProduct.type == "kredi_karti",
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi kartı bulunamadı")

    stmts = (
        db.query(CreditCardStatement)
        .filter(CreditCardStatement.credit_product_id == product_id)
        .order_by(desc(CreditCardStatement.kesim_tarihi))
        .all()
    )

    # İşlem sayılarını toplu al (N+1 engeli)
    stmt_ids = [s.id for s in stmts]
    tx_count_map = {}
    if stmt_ids:
        count_rows = (
            db.query(CreditCardTransaction.statement_id, func.count(CreditCardTransaction.id))
            .filter(CreditCardTransaction.statement_id.in_(stmt_ids))
            .group_by(CreditCardTransaction.statement_id)
            .all()
        )
        tx_count_map = {sid: cnt for sid, cnt in count_rows}

    items = []
    for s in stmts:
        items.append(CCStatementListItem(
            id=s.id,
            ekstre_no=s.ekstre_no,
            kesim_tarihi=s.kesim_tarihi,
            son_odeme_tarihi=s.son_odeme_tarihi,
            toplam_borc=float(s.toplam_borc),
            asgari_odeme=float(s.asgari_odeme),
            is_paid=s.is_paid,
            paid_amount=float(s.paid_amount) if s.paid_amount is not None else None,
            paid_date=s.paid_date,
            file_name=s.file_name,
            transaction_count=tx_count_map.get(s.id, 0),
            created_at=s.created_at,
        ).model_dump())

    return items


# ---- Detail -----------------------------------------------------------------

@router.get("/{product_id}/statements/{stmt_id}")
def get_statement(
    product_id: int,
    stmt_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Ekstre detayı + işlemler."""
    stmt = db.query(CreditCardStatement).filter(
        CreditCardStatement.id == stmt_id,
        CreditCardStatement.credit_product_id == product_id,
    ).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Ekstre bulunamadı")

    txs = (
        db.query(CreditCardTransaction)
        .filter(CreditCardTransaction.statement_id == stmt_id)
        .order_by(CreditCardTransaction.islem_tarihi.nullsfirst(), CreditCardTransaction.id)
        .all()
    )

    return CCStatementResponse(
        id=stmt.id,
        credit_product_id=stmt.credit_product_id,
        ekstre_no=stmt.ekstre_no,
        kesim_tarihi=stmt.kesim_tarihi,
        son_odeme_tarihi=stmt.son_odeme_tarihi,
        onceki_bakiye=float(stmt.onceki_bakiye),
        donem_harcama=float(stmt.donem_harcama),
        faiz_ucret=float(stmt.faiz_ucret),
        donem_odeme=float(stmt.donem_odeme),
        toplam_borc=float(stmt.toplam_borc),
        asgari_odeme=float(stmt.asgari_odeme),
        is_paid=stmt.is_paid,
        paid_amount=float(stmt.paid_amount) if stmt.paid_amount is not None else None,
        paid_date=stmt.paid_date,
        file_name=stmt.file_name,
        created_at=stmt.created_at,
        transactions=[
            CCTransactionResponse(
                id=tx.id,
                islem_tarihi=tx.islem_tarihi,
                aciklama=tx.aciklama,
                kategori=tx.kategori,
                taksit_bilgi=tx.taksit_bilgi,
                tutar=float(tx.tutar),
                is_credit=tx.is_credit,
                bonus=float(tx.bonus) if tx.bonus is not None else None,
            )
            for tx in txs
        ],
    ).model_dump()


# ---- Delete -----------------------------------------------------------------

@router.delete("/{product_id}/statements/{stmt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_statement(
    product_id: int,
    stmt_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Ekstre sil."""
    stmt = db.query(CreditCardStatement).filter(
        CreditCardStatement.id == stmt_id,
        CreditCardStatement.credit_product_id == product_id,
    ).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Ekstre bulunamadı")

    file_name = stmt.file_name
    file_url = stmt.file_url

    finance_event_svc.invalidate(db, "cc_payment", stmt_id)
    db.delete(stmt)

    log_action(
        db, current_user.id, "delete", "credit_card_statement",
        entity_id=stmt_id,
        details=f"Kredi kartı ekstresi silindi: {file_name}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, "delete")

    # Dosyayi sil
    if file_url:
        full_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            file_url.lstrip("/"),
        )
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except OSError as e:
                logger.warning("Ekstre dosyası silinemedi: %s — %s", full_path, e)
