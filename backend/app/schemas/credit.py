"""Kredi ürünleri Pydantic şemaları."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CreditProductCreate(BaseModel):
    type: str
    name: str = Field(..., min_length=1, max_length=200)
    bank_name: Optional[str] = None
    company: Optional[str] = None
    currency: str = "TRY"
    total_amount: float = 0
    remaining_amount: float = 0
    interest_rate: Optional[float] = None
    bsmv_rate: Optional[float] = None
    commission_rate: Optional[float] = None
    linked_account_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    details: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class CreditProductUpdate(BaseModel):
    name: Optional[str] = None
    bank_name: Optional[str] = None
    company: Optional[str] = None
    currency: Optional[str] = None
    total_amount: Optional[float] = None
    remaining_amount: Optional[float] = None
    interest_rate: Optional[float] = None
    bsmv_rate: Optional[float] = None
    commission_rate: Optional[float] = None
    linked_account_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class CreditProductResponse(BaseModel):
    id: int
    type: str
    type_label: str = ""
    name: str
    bank_name: Optional[str] = None
    company: Optional[str] = None
    currency: str
    total_amount: float
    remaining_amount: float
    interest_rate: Optional[float] = None
    bsmv_rate: Optional[float] = None
    commission_rate: Optional[float] = None
    linked_account_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str
    closed_date: Optional[date] = None
    details: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    creator_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    payment_count: int = 0
    paid_count: int = 0
    next_payment_date: Optional[date] = None
    next_payment_amount: Optional[float] = None

    class Config:
        from_attributes = True


class CreditCloseRequest(BaseModel):
    """Kredi kapatma isteği — kapanış tarihi (varsayılan bugün)."""
    closed_date: Optional[date] = None


class CreditPaymentCreate(BaseModel):
    installment_no: Optional[int] = None
    due_date: date
    amount: float
    principal: Optional[float] = None
    interest: Optional[float] = None
    bsmv: Optional[float] = None
    commission: Optional[float] = None
    notes: Optional[str] = None


class CreditPaymentBulkCreate(BaseModel):
    payments: List[CreditPaymentCreate]


class CreditPaymentUpdate(BaseModel):
    due_date: Optional[date] = None
    amount: Optional[float] = None
    principal: Optional[float] = None
    interest: Optional[float] = None
    bsmv: Optional[float] = None
    commission: Optional[float] = None
    is_paid: Optional[bool] = None
    paid_date: Optional[date] = None
    notes: Optional[str] = None


class CreditPaymentResponse(BaseModel):
    id: int
    credit_product_id: int
    installment_no: Optional[int] = None
    due_date: date
    amount: float
    principal: Optional[float] = None
    interest: Optional[float] = None
    bsmv: Optional[float] = None
    commission: Optional[float] = None
    is_paid: bool
    paid_date: Optional[date] = None
    bank_transaction_id: Optional[int] = None
    match_number: Optional[int] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CreditSummaryItem(BaseModel):
    type: str
    type_label: str
    count: int
    total_amount: float
    remaining_amount: float
