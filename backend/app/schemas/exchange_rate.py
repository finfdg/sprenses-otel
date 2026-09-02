"""Döviz kuru Pydantic şemaları."""

from datetime import date
from typing import Optional

from pydantic import BaseModel


class ExchangeRateResponse(BaseModel):
    id: int
    date: date
    currency_code: str
    currency_name: Optional[str] = None
    unit: int
    forex_buying: Optional[float] = None
    forex_selling: Optional[float] = None
    banknote_buying: Optional[float] = None
    banknote_selling: Optional[float] = None
    source: str

    class Config:
        from_attributes = True

