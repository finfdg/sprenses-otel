"""Verilen çekler şemaları."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CheckResponse(BaseModel):
    id: int
    check_type: Optional[str] = None
    sequence_no: Optional[int] = None
    check_no: str
    vendor_code: Optional[str] = None
    vendor_name: str
    description: Optional[str] = None
    bank_name: Optional[str] = None
    city: Optional[str] = None
    due_date: date
    amount_tl: float
    currency: str
    amount_currency: float
    transaction_type: Optional[str] = None
    status: str
    bank_transaction_id: Optional[int] = None
    match_number: Optional[int] = None
    matched_vendor_id: Optional[int] = None

    class Config:
        from_attributes = True


class CheckUploadResponse(BaseModel):
    id: int
    file_name: str
    total_checks: int
    new_checks: int
    skipped_checks: int
    uploaded_by: Optional[int] = None
    uploader_name: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class CheckUploadResult(BaseModel):
    upload_id: int
    file_name: str
    total_checks: int
    new_checks: int
    skipped_checks: int
