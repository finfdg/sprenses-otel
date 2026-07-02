"""Hak ediş vade tanımı — acente/firma (120.*) bazlı sözleşme vadesi.

Sedna'da vade bilgisi YOKTUR (Invoice.DueDate=InvoiceDate, Agency.Days=0 — 2026-07-02 keşfi)
→ 30/45 gün anlaşma vadeleri burada, yerelde tutulur. Fatura vadesi hesaplamada
`invoice_date + term_days` kullanılır; tanımsız firma varsayılan 30 gün sayılır.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DEFAULT_TERM_DAYS = 30  # tanımsız firma için varsayılan sözleşme vadesi (gün)


class ReceivableTerm(Base):
    __tablename__ = "receivable_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(50), unique=True)  # 120.* cari kodu
    term_days: Mapped[int] = mapped_column(Integer, server_default="30")  # sözleşme vadesi (gün)
    notes: Mapped[str] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
