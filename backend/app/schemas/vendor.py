"""Cari hesap şemaları — cari ve işlem yanıt modelleri."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


# ─── Cari Banka Hesabı (IBAN) ───────────────────────────

class VendorBankAccountCreate(BaseModel):
    bank_name: Optional[str] = None
    iban: str
    account_holder: Optional[str] = None
    is_default: bool = False


class VendorBankAccountUpdate(BaseModel):
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    account_holder: Optional[str] = None
    is_default: Optional[bool] = None


class VendorBankAccountResponse(BaseModel):
    id: int
    vendor_id: int
    bank_name: Optional[str] = None
    iban: str
    account_holder: Optional[str] = None
    is_default: bool
    sort_order: int

    class Config:
        from_attributes = True


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
    # İletişim (Firma Bilgileri sekmesi)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    # Özet kart metrikleri (tasarım: Güncel Bakiye / Vadesi Geçmiş / Son Ödeme)
    overdue: float = 0.0
    overdue_count: int = 0
    last_payment_amount: Optional[float] = None
    last_payment_date: Optional[date] = None

    class Config:
        from_attributes = True


class VendorPaymentDaysUpdate(BaseModel):
    payment_days: int


class VendorStatusUpdate(BaseModel):
    status: str


class VendorContactUpdate(BaseModel):
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


# ─── Cari Notu (Notlar sekmesi) ─────────────────────────

class VendorNoteCreate(BaseModel):
    text: str


class VendorNoteUpdate(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None


class VendorNoteResponse(BaseModel):
    id: int
    vendor_id: int
    text: str
    author_name: Optional[str] = None
    done: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VendorNoteListItem(VendorNoteResponse):
    """Toplu not listesi satırı — nota firma bilgisi eklenir (Notlar sekmesi kartı)."""
    vendor_name: str
    vendor_code: str


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
