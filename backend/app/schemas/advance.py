"""Alınan avanslar şemaları."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class AdvanceCreate(BaseModel):
    agency_name: str = Field(..., min_length=1, max_length=200)
    amount: float = Field(..., gt=0)
    currency: str = Field("EUR", max_length=5)
    advance_date: date
    notes: Optional[str] = None


class AdvanceUpdate(BaseModel):
    agency_name: Optional[str] = Field(None, max_length=200)
    amount: Optional[float] = None
    currency: Optional[str] = Field(None, max_length=5)
    advance_date: Optional[date] = None
    status: Optional[str] = Field(None, pattern="^(pending|received|cancelled)$")
    notes: Optional[str] = None


class AdvanceMatchRequest(BaseModel):
    """Banka işlemiyle eşleştirme."""
    bank_transaction_id: Optional[int] = None
    received_date: date
    received_amount: float = Field(..., gt=0)


class AdvanceResponse(BaseModel):
    id: int
    agency_name: str
    amount: float
    currency: str
    advance_date: date
    status: str
    notes: Optional[str] = None
    bank_transaction_id: Optional[int] = None
    received_date: Optional[date] = None
    received_amount: Optional[float] = None
    created_by: Optional[int] = None
    creator_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
