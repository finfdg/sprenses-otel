"""Banka hesabı ve ekstre şemaları — hesap CRUD, işlem ve ekstre yanıtları."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

# ─── BankAccount ────────────────────────────────────────

class BankAccountCreate(BaseModel):
    bank_name: str = Field(..., max_length=100)
    branch_name: Optional[str] = Field(None, max_length=200)
    account_no: Optional[str] = Field(None, max_length=50)
    iban: str = Field(..., max_length=34)
    currency: str = Field("TRY", max_length=3)
    holder_name: Optional[str] = Field(None, max_length=300)
    blocked_amount: Optional[float] = None


class BankAccountUpdate(BaseModel):
    bank_name: Optional[str] = Field(None, max_length=100)
    branch_name: Optional[str] = Field(None, max_length=200)
    account_no: Optional[str] = Field(None, max_length=50)
    iban: Optional[str] = Field(None, max_length=34)
    currency: Optional[str] = Field(None, max_length=3)
    holder_name: Optional[str] = Field(None, max_length=300)
    is_active: Optional[bool] = None
    blocked_amount: Optional[float] = None


class BankAccountResponse(BaseModel):
    id: int
    bank_name: str
    branch_name: Optional[str] = None
    account_no: Optional[str] = None
    iban: str
    currency: str
    holder_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    blocked_amount: Optional[float] = None
    transaction_count: Optional[int] = 0
    last_balance: Optional[float] = None
    last_statement_date: Optional[date] = None

    class Config:
        from_attributes = True


# ─── BankStatement ──────────────────────────────────────

class BankStatementResponse(BaseModel):
    id: int
    account_id: int
    file_name: str
    file_type: str
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    total_transactions: int
    new_transactions: int
    skipped_transactions: int
    uploaded_at: datetime

    class Config:
        from_attributes = True


class UploadResult(BaseModel):
    statement_id: int
    file_name: str
    total_transactions: int
    new_transactions: int
    skipped_transactions: int
    account_iban: Optional[str] = None
    account_currency: Optional[str] = None


# ─── BankTransaction ───────────────────────────────────

class BankTransactionResponse(BaseModel):
    id: int
    account_id: int
    date: date
    receipt_no: Optional[str] = None
    description: str
    amount: float
    balance: Optional[float] = None
    type: str
    source: str = "statement"  # 'statement' | 'manual' (ekstre-dışı)

    class Config:
        from_attributes = True


class ManualTransactionCreate(BaseModel):
    """Ekstre-dışı (manuel) banka hareketi — ekstresi gelmemiş bir işlemi yansıtmak için."""
    date: date
    amount: float  # işaretli: negatif = çıkış (hesaptan düşer), pozitif = giriş
    description: str
    category_id: Optional[int] = None
