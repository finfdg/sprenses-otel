"""Kredi kartı ekstre Pydantic şemaları."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class CCTransactionResponse(BaseModel):
    id: int
    islem_tarihi: Optional[date] = None
    aciklama: str
    kategori: Optional[str] = None
    taksit_bilgi: Optional[str] = None
    tutar: float
    is_credit: bool
    bonus: Optional[float] = None

    class Config:
        from_attributes = True


class CCStatementResponse(BaseModel):
    id: int
    credit_product_id: int
    ekstre_no: Optional[str] = None
    kesim_tarihi: date
    son_odeme_tarihi: date
    onceki_bakiye: float
    donem_harcama: float
    faiz_ucret: float
    donem_odeme: float
    toplam_borc: float
    asgari_odeme: float
    is_paid: bool
    paid_amount: Optional[float] = None
    paid_date: Optional[date] = None
    file_name: Optional[str] = None
    created_at: datetime
    transactions: List[CCTransactionResponse] = []

    class Config:
        from_attributes = True


class CCStatementListItem(BaseModel):
    id: int
    ekstre_no: Optional[str] = None
    kesim_tarihi: date
    son_odeme_tarihi: date
    toplam_borc: float
    asgari_odeme: float
    is_paid: bool
    paid_amount: Optional[float] = None
    paid_date: Optional[date] = None
    file_name: Optional[str] = None
    transaction_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class CCStatementUploadResult(BaseModel):
    statement_id: int
    kart_no: str
    kesim_tarihi: date
    toplam_borc: float
    transaction_count: int
    card_name: Optional[str] = None
