"""Banka talimat PDF oluşturma — EFT/havale ve döviz bozma talimatları."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.bank_account import BankAccount
from app.models.user import User
from app.utils.pdf_bank_instruction import (
    generate_currency_exchange_instruction,
    generate_transfer_instruction,
)

router = APIRouter(prefix="/bank-instructions")


# ─── Şemalar ───────────────────────────────────────────

class TransferInstructionRequest(BaseModel):
    source_account_id: int
    dest_account_id: int
    amount: float
    instruction_date: Optional[str] = None
    description: Optional[str] = None
    # Sol imza: "ugur" (Uğur CARUS) veya "erol" (Erol YILDIZ). Default: ugur.
    left_signer: Optional[str] = "ugur"


class CurrencyExchangeRequest(BaseModel):
    source_account_id: int
    target_currency: str
    amount: float
    target_account_id: Optional[int] = None
    instruction_date: Optional[str] = None
    description: Optional[str] = None
    # Sol imza: "ugur" (Uğur CARUS) veya "erol" (Erol YILDIZ). Default: ugur.
    left_signer: Optional[str] = "ugur"


# ─── Yardımcılar ───────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> date:
    """Tarih string'ini parse et, yoksa bugünü döndür."""
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def _get_account(db: Session, account_id: int) -> BankAccount:
    """Hesabı getir, yoksa 404."""
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail=f"Banka hesabı bulunamadı (ID: {account_id})")
    return account


# ─── Endpoint'ler ──────────────────────────────────────

@router.post("/transfer")
def create_transfer_instruction(
    body: TransferInstructionRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.banks", "view")),
):
    """EFT/Havale talimat PDF'i oluştur."""
    source = _get_account(db, body.source_account_id)
    dest = _get_account(db, body.dest_account_id)

    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Tutar sıfırdan büyük olmalıdır")

    if source.id == dest.id:
        raise HTTPException(status_code=400, detail="Kaynak ve hedef hesap aynı olamaz")

    # EFT/Havale: Kaynak ve hedef aynı para biriminde olmalı.
    # Farklı para birimi için "Döviz Bozma Talimatı" endpoint'i kullanılır.
    source_currency = (source.currency or "TRY").upper()
    dest_currency = (dest.currency or "TRY").upper()
    if source_currency != dest_currency:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Kaynak hesap ({source_currency}) ile hedef hesap ({dest_currency}) "
                "farklı para biriminde. Farklı para birimi için 'Döviz Bozma Talimatı' kullanın."
            ),
        )

    instruction_date = _parse_date(body.instruction_date)

    pdf_bytes = generate_transfer_instruction(
        source_bank_name=source.bank_name,
        source_branch_name=source.branch_name,
        source_account_no=source.account_no,
        source_iban=source.iban,
        source_currency=source.currency or "TRY",
        dest_bank_name=dest.bank_name,
        dest_branch_name=dest.branch_name,
        dest_iban=dest.iban,
        amount=body.amount,
        instruction_date=instruction_date,
        description=body.description,
        left_signer=body.left_signer or "ugur",
    )

    # Dosya adı işleme göre ("eft" | "havale" | "transfer")
    src_cur = (source.currency or "TRY").upper()
    if src_cur != "TRY":
        prefix = "transfer"
    elif (source.bank_name or "").strip().lower() == (dest.bank_name or "").strip().lower():
        prefix = "havale"
    else:
        prefix = "eft"
    filename = f"{prefix}-talimat-{instruction_date.strftime('%Y%m%d')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/currency-exchange")
def create_currency_exchange_instruction(
    body: CurrencyExchangeRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.banks", "view")),
):
    """Döviz bozma/alma talimat PDF'i oluştur."""
    source = _get_account(db, body.source_account_id)

    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Tutar sıfırdan büyük olmalıdır")

    valid_currencies = ["TRY", "EUR", "USD", "GBP"]
    if body.target_currency not in valid_currencies:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz hedef para birimi. Geçerli değerler: {', '.join(valid_currencies)}",
        )

    if body.target_currency == (source.currency or "TRY"):
        raise HTTPException(status_code=400, detail="Kaynak ve hedef para birimi aynı olamaz")

    instruction_date = _parse_date(body.instruction_date)

    target_iban = None
    if body.target_account_id:
        target_account = _get_account(db, body.target_account_id)
        target_iban = target_account.iban

    pdf_bytes = generate_currency_exchange_instruction(
        bank_name=source.bank_name,
        branch_name=source.branch_name,
        account_no=source.account_no,
        source_iban=source.iban,
        source_currency=source.currency or "TRY",
        target_currency=body.target_currency,
        amount=body.amount,
        target_iban=target_iban,
        instruction_date=instruction_date,
        description=body.description,
        left_signer=body.left_signer or "ugur",
    )

    filename = f"doviz-talimat-{instruction_date.strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/accounts")
def list_bank_accounts_for_instructions(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.banks", "view")),
):
    """Talimat oluşturmak için banka hesap listesi."""
    accounts = (
        db.query(BankAccount)
        .filter(BankAccount.is_active == True)
        .order_by(BankAccount.bank_name, BankAccount.currency)
        .all()
    )
    return [
        {
            "id": a.id,
            "bank_name": a.bank_name,
            "branch_name": a.branch_name,
            "account_no": a.account_no,
            "iban": a.iban,
            "currency": a.currency or "TRY",
            "holder_name": a.holder_name,
            "label": f"{a.bank_name} - {a.currency or 'TRY'} ({a.iban[-4:]})",
        }
        for a in accounts
    ]
