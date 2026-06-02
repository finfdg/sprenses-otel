"""Cari hesap şemaları — cari ve işlem yanıt modelleri."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel

# ─── Vendor ─────────────────────────────────────────────

class VendorResponse(BaseModel):
    id: int
    hesap_kodu: str
    hesap_adi: str
    payment_days: int
    status: str = "normal"
    total_borc: float
    total_alacak: float
    bakiye: float
    transaction_count: int
    unmatched_count: int = 0

    class Config:
        from_attributes = True


class VendorDetailResponse(BaseModel):
    id: int
    hesap_kodu: str
    hesap_adi: str
    payment_days: int
    status: str = "normal"
    total_borc: float
    total_alacak: float
    bakiye: float

    class Config:
        from_attributes = True


class VendorPaymentDaysUpdate(BaseModel):
    payment_days: int


class VendorStatusUpdate(BaseModel):
    status: str


# ─── VendorTransaction ──────────────────────────────────

class VendorTransactionResponse(BaseModel):
    id: int
    vendor_id: int
    date: date
    evrak_no: Optional[str] = None
    transaction_type: Optional[str] = None
    fis_no: Optional[str] = None
    description: Optional[str] = None
    borc: float
    alacak: float
    bakiye: Optional[float] = None
    payment_due_date: Optional[date] = None
    match_number: Optional[int] = None
    payment_method: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    budget_category_id: Optional[int] = None
    budget_category_name: Optional[str] = None
    dept_status: Optional[str] = None
    dept_assigned_by_name: Optional[str] = None
    dept_assigned_at: Optional[str] = None
    dept_rejection_note: Optional[str] = None

    class Config:
        from_attributes = True


# ─── VendorUpload ──────────────────────────────────────

class VendorUploadResponse(BaseModel):
    id: int
    file_name: str
    total_vendors: int
    total_transactions: int
    new_transactions: int
    skipped_transactions: int
    uploaded_by: Optional[int] = None
    uploader_name: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


# ─── Removal Candidate (Excel'de olmayan ama DB'de duran kayıtlar) ─────

class RemovalCandidate(BaseModel):
    """Yüklenen Excel'in kapsamında (vendor + tarih aralığı) yer aldığı halde
    Excel'de tx_hash karşılığı bulunmayan, üzerinde manuel iş yapılmamış kayıt."""
    id: int
    vendor_id: int
    hesap_kodu: str
    hesap_adi: str
    date: date
    evrak_no: Optional[str] = None
    transaction_type: Optional[str] = None
    description: Optional[str] = None
    borc: float
    alacak: float
    bakiye: Optional[float] = None


class BulkDeleteRequest(BaseModel):
    ids: List[int]


class BulkDeleteResult(BaseModel):
    deleted: int
    skipped: int
    skipped_reasons: List[str] = []


class VendorUploadResult(BaseModel):
    upload_id: int
    file_name: str
    total_vendors: int
    total_transactions: int
    new_transactions: int
    skipped_transactions: int
    removal_candidates: List[RemovalCandidate] = []


# ─── Payment Schedule ──────────────────────────────────

class PaymentScheduleItem(BaseModel):
    vendor_id: int
    hesap_kodu: str
    hesap_adi: str
    evrak_no: Optional[str] = None
    transaction_type: Optional[str] = None
    invoice_date: date
    payment_due_date: date
    amount: float


class WeeklyPaymentGroup(BaseModel):
    friday_date: date
    total_amount: float
    items: List[PaymentScheduleItem]
