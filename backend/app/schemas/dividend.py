"""Kâr payı dağıtımı (temettü) Pydantic şemaları."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── Create ──────────────────────────────────────────────────────────

class DividendShareholderInput(BaseModel):
    """Oluşturmada pay sahibi girdisi — oran/brüt/stopaj/net servis tarafından hesaplanır."""
    name: str = Field(..., min_length=1, max_length=200)
    share_value: float = Field(..., ge=0)


class DividendDistributionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    decision_date: Optional[date] = None
    total_gross: float = Field(..., gt=0)
    capital: Optional[float] = None
    withholding_rate: float = 0.15
    installment_count: int = Field(..., ge=1, le=60)
    year: int
    # Taksit vadeleri: ya açık liste (uzunluğu installment_count olmalı) ya da
    # first_installment_date'ten aylık ay-sonları türetilir.
    installment_dates: Optional[List[date]] = None
    first_installment_date: Optional[date] = None
    notes: Optional[str] = None
    shareholders: List[DividendShareholderInput] = Field(..., min_length=1)


# ─── Update ──────────────────────────────────────────────────────────

class DividendDistributionUpdate(BaseModel):
    """Yalnız metadata — finansal alanlar patch'lenmez (değişim = sil + yeniden oluştur)."""
    name: Optional[str] = None
    decision_date: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class DividendPaymentUpdate(BaseModel):
    is_paid: Optional[bool] = None
    paid_date: Optional[date] = None
    stopaj_paid: Optional[bool] = None
    stopaj_paid_date: Optional[date] = None
    notes: Optional[str] = None


# ─── Response ────────────────────────────────────────────────────────

class DividendShareholderResponse(BaseModel):
    id: int
    sort_order: int
    name: str
    share_value: float
    share_ratio: float
    gross_dividend: float
    stopaj_amount: float
    net_dividend: float

    class Config:
        from_attributes = True


class DividendInstallmentResponse(BaseModel):
    id: int
    installment_no: int
    due_date: date
    label: Optional[str] = None
    gross_amount: float
    stopaj_amount: float
    net_amount: float
    stopaj_due_date: Optional[date] = None  # türev: due_date'in ertesi ayının 26'sı
    paid_count: int = 0
    total_count: int = 0
    net_paid: bool = False    # taksitin tüm net ödemeleri yapıldı mı
    stopaj_paid: bool = False  # taksitin tüm stopaj ödemeleri yapıldı mı


class DividendPaymentResponse(BaseModel):
    id: int
    distribution_id: int
    installment_id: int
    shareholder_id: int
    shareholder_name: Optional[str] = None
    installment_no: Optional[int] = None
    gross_amount: float
    stopaj_amount: float
    net_amount: float
    is_paid: bool
    paid_date: Optional[date] = None
    stopaj_paid: bool
    stopaj_paid_date: Optional[date] = None
    notes: Optional[str] = None


class DividendDistributionResponse(BaseModel):
    id: int
    name: str
    decision_date: Optional[date] = None
    total_gross: float
    capital: Optional[float] = None
    withholding_rate: float
    installment_count: int
    year: int
    status: str
    notes: Optional[str] = None
    created_by: Optional[int] = None
    creator_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # rollup / türev alanlar
    total_stopaj: float = 0
    total_net: float = 0
    shareholder_count: int = 0
    net_paid_count: int = 0      # ödenmiş net satır sayısı
    net_total_count: int = 0     # toplam net satır (= shareholder × installment)
    stopaj_paid_count: int = 0

    # detay GET'te doldurulur
    shareholders: List[DividendShareholderResponse] = []
    installments: List[DividendInstallmentResponse] = []
    payments: List[DividendPaymentResponse] = []
