"""Planlı gider tanım ve giriş şemaları."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

# ─── Definition Schemas ──────────────────────────────────


class DefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: Optional[str] = None
    amount: float = Field(..., gt=0)
    currency: str = Field(default="TRY", max_length=3)
    frequency: str = Field(default="monthly", pattern="^(monthly|quarterly|yearly)$")
    payment_day: int = Field(default=1, ge=1, le=28)
    start_month: int = Field(default=1, ge=1, le=12)
    year: Optional[int] = None
    notes: Optional[str] = None
    vendor_id: Optional[int] = None  # cari (satıcı) bağlantısı — recurring senkronu için
    billing_offset_months: int = Field(default=0, ge=0, le=6)  # fatura gecikmesi (su=1, elektrik=0)


class DefinitionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    category: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    frequency: Optional[str] = Field(None, pattern="^(monthly|quarterly|yearly)$")
    payment_day: Optional[int] = Field(None, ge=1, le=28)
    start_month: Optional[int] = Field(None, ge=1, le=12)  # değişirse girişler yeniden üretilir
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    vendor_id: Optional[int] = None  # None gönderilirse bağlantı korunur (exclude_unset); 0 → kaldır
    billing_offset_months: Optional[int] = Field(None, ge=0, le=6)


class DefinitionResponse(BaseModel):
    id: int
    source_type: str
    name: str
    category: Optional[str] = None
    amount: float
    currency: str
    frequency: str
    payment_day: int
    start_month: int
    year: int
    notes: Optional[str] = None
    is_active: bool
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None  # bağlı cari adı (gösterim)
    billing_offset_months: int = 0
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    entries: Optional[List["EntryResponse"]] = None

    class Config:
        from_attributes = True


# ─── Entry Schemas ───────────────────────────────────────


class EntryUpdate(BaseModel):
    amount: Optional[float] = Field(None, gt=0)
    entry_date: Optional[date] = None
    period_month: Optional[int] = Field(None, ge=1, le=12)
    period_year: Optional[int] = Field(None, ge=2000, le=2100)
    is_paid: Optional[bool] = None
    paid_date: Optional[date] = None
    notes: Optional[str] = None


class EntryResponse(BaseModel):
    id: int
    definition_id: int
    source_type: str
    entry_date: date
    period_month: int
    period_year: int
    amount: float
    currency: str
    description: Optional[str] = None
    is_paid: bool
    paid_date: Optional[date] = None
    notes: Optional[str] = None
    synced_from_cari: bool = False  # tutar/ödeme cari gerçek faturadan mı senkronlandı

    class Config:
        from_attributes = True
