"""Nakit akım yanıt şeması — finance_events birleşik görünüm."""

from datetime import date
from typing import Optional

from pydantic import BaseModel


class CashFlowResponse(BaseModel):
    id: int
    date: date
    description: str
    amount: float
    type: str
    source: str = "bank"  # "bank", "check", "credit", "vendor_payment"
    balance: Optional[float] = None
    receipt_no: Optional[str] = None
    bank_name: Optional[str] = None
    bank_name_inferred: bool = False
    currency: str = "TL"
    iban: Optional[str] = None
    account_id: Optional[int] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    category_color: Optional[str] = None
    tag_note: Optional[str] = None
    tag_source: Optional[str] = None
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None
    payment_method: Optional[str] = None
    match_number: Optional[int] = None
    # Çek-spesifik alanlar
    check_no: Optional[str] = None
    check_status: Optional[str] = None
    vendor_code: Optional[str] = None
    amount_try: Optional[float] = None
    invoice_count: Optional[int] = None
    # Karşı kayıtla eşleşmiş (çift sayım gizlemesine tabi) — listede BİLGİ amaçlı
    # gösterilir, gün/ay toplamlarına KATILMAZ (ör. ödenen çek "Ödendi" rozetiyle kalır)
    is_matched: bool = False

    class Config:
        from_attributes = True
