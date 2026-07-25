"""Sunucu izleme (system.server) şemaları."""

from typing import List, Optional

from pydantic import BaseModel, Field


class DiskCleanupRequest(BaseModel):
    """Disk temizliği isteği — `keys` boş/None ise tüm temizlenebilir kategoriler temizlenir."""

    keys: Optional[List[str]] = Field(
        default=None,
        description="Temizlenecek kategori anahtarları (boş → tümü)",
    )
