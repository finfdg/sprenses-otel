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


class CreditMappingUpdate(BaseModel):
    """Kredi ürünü ↔ Sedna 300 leaf kodu (None = temizle)."""

    sedna_account_code: Optional[str] = Field(default=None, max_length=30)


class AgencyMappingUpdate(BaseModel):
    """Acente grubu ↔ Sedna 340 kod listesi (para birimi başına ayrı hesap; boş = temizle)."""

    sedna_account_codes: Optional[list] = None


class PeriodLockUpdate(BaseModel):
    """Dönem kilidi tarihi (None = kaldır) — uyarı modu, bloklamaz."""

    lock_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
