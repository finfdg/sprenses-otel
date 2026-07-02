"""Hak ediş takibi Pydantic şemaları."""
from typing import Optional

from pydantic import BaseModel, Field


class ReceivableTermUpdate(BaseModel):
    """Firma vade tanımı upsert isteği (PATCH /terms/{customer_code})."""
    term_days: int = Field(ge=0, le=365, description="Sözleşme vadesi (gün, ör. 30/45)")
    notes: Optional[str] = Field(default=None, max_length=300)
