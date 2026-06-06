"""Ödeme talimat listesi şemaları."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── Kalem ───────────────────────────────────────────────

class PaymentItemCreate(BaseModel):
    """Listeye eklenecek kalem — cari ve tutar (+ seçili banka/IBAN)."""
    vendor_id: Optional[int] = None
    hesap_kodu: Optional[str] = None
    hesap_adi: str
    amount: float = 0
    balance_snapshot: Optional[float] = None
    notes: Optional[str] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None


class PaymentItemUpdate(BaseModel):
    amount: Optional[float] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None


class PaymentItemResponse(BaseModel):
    id: int
    vendor_id: Optional[int] = None
    hesap_kodu: Optional[str] = None
    hesap_adi: str
    amount: float
    balance_snapshot: Optional[float] = None
    notes: Optional[str] = None
    sort_order: int
    bank_name: Optional[str] = None
    iban: Optional[str] = None

    class Config:
        from_attributes = True


# ─── Liste ───────────────────────────────────────────────

class PaymentListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    items: List[PaymentItemCreate] = Field(default_factory=list)


class PaymentListUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[str] = None


class BulkAddItemsRequest(BaseModel):
    """Listeye toplu cari ekleme (cariler tablosundan seçim)."""
    items: List[PaymentItemCreate] = Field(default_factory=list)


class PaymentListResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    item_count: int = 0
    total_amount: float = 0
    created_by: Optional[int] = None
    creator_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    items: List[PaymentItemResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True
