"""Sedna Mutabakat (accounting.mutabakat) istek şemaları."""
from typing import Optional

from pydantic import BaseModel, Field


class ReconItemAction(BaseModel):
    """Uyuşmazlık kaydı aksiyonu: resolve (çözüldü) / ignore (yoksay) / reopen (geri aç)."""

    action: str = Field(pattern="^(resolve|ignore|reopen)$")
    note: Optional[str] = Field(default=None, max_length=500)


class AccountMappingUpdate(BaseModel):
    """Banka hesabı ↔ Sedna 102 leaf kodu eşlemesi (None = temizle)."""

    sedna_account_code: Optional[str] = Field(default=None, max_length=30)
    confirmed: bool = False


class ReconRunRequest(BaseModel):
    """Elle mutabakat taraması tetikleme."""

    window_days: int = Field(default=45, ge=7, le=365)
