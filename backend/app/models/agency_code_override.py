"""PMS acente adı → 120 cari kodu YEREL düzeltme/ekleme katmanı.

`agency_code_map` Sedna satış senkronunda SİLİNİP yeniden yüklenir (sales_invoices.py
delete+insert) — elle eklenen satır bir sonraki senkronda kaybolur. Sedna'da kodu
eksik (NORDIC) veya yanlış (AKAY İNŞ → 0123, faturalar A001'de) acenteler için kalıcı
yerel katman burasıdır. Tüketici (receivable_service._group_map) Sedna haritasını
kurduktan sonra bu tabloyu ÜZERİNE yazar — override kazanır. (2026-07-17 kontrat analizi)
"""
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgencyCodeOverride(Base):
    __tablename__ = "agency_code_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    pms_name: Mapped[str] = mapped_column(String(200), unique=True)  # PMS acente adı
    acc_code: Mapped[str] = mapped_column(String(50))  # 120.* cari kodu
    notes: Mapped[str] = mapped_column(String(300), nullable=True)  # neden/kanıt
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
