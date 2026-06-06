"""Otel satış faturaları (120/Alıcılar) + tahsilatlar — Sedna kaynaklı, FIFO tahsil takibi.

Cariler'in (320/Satıcılar) aynası: fatura = 120 **Borç** hareketi (DocumentType=1 Hizmet Satış
Fatura); tahsilat = 120 **Alacak** hareketi. Tahsil durumu, müşteri bazında tahsilatların
faturalara FIFO (en eskiden) düşülmesiyle hesaplanır — ödendi / kısmi / açık.

Münferit (bireysel/walk-in misafir) ≈ 120.03.* ; diğer 120 grupları = acente/kurumsal.
"""
from datetime import date as date_type
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CUSTOMER_MUNFERIT = "munferit"
CUSTOMER_AGENCY = "agency"

# Tahsil durumları (hesaplanır, kolon değil)
STATUS_PAID = "paid"        # tamamı tahsil edildi
STATUS_PARTIAL = "partial"  # kısmi tahsil
STATUS_OPEN = "open"        # hiç tahsil edilmedi


class SalesInvoice(Base):
    """Kesilen satış faturası (Sedna 120 DocumentType=1 Borç hareketi). Dedup: tx_hash."""
    __tablename__ = "sales_invoices"
    __table_args__ = (
        Index("ix_sales_inv_customer", "customer_code"),
        Index("ix_sales_inv_date", "invoice_date"),
        Index("ix_sales_inv_hash", "tx_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(50))
    customer_name: Mapped[str] = mapped_column(String(300))
    is_munferit: Mapped[bool] = mapped_column(Boolean, server_default="false")
    invoice_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    invoice_date: Mapped[date_type] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Numeric(15, 2))                 # TL karşılığı
    currency: Mapped[str] = mapped_column(String(5), server_default="TL")
    amount_currency: Mapped[float] = mapped_column(Numeric(15, 2), server_default="0")  # döviz tutarı (TL ise = amount)
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    tx_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SalesCollection(Base):
    """120 tahsilat (Alacak hareketi) — faturalardan FIFO ile düşülür. Dedup: tx_hash."""
    __tablename__ = "sales_collections"
    __table_args__ = (
        Index("ix_sales_col_customer", "customer_code"),
        Index("ix_sales_col_hash", "tx_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(50))
    customer_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    collection_date: Mapped[date_type] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Numeric(15, 2))                 # TL karşılığı
    currency: Mapped[str] = mapped_column(String(5), server_default="TL")
    amount_currency: Mapped[float] = mapped_column(Numeric(15, 2), server_default="0")  # döviz tutarı (TL ise = amount)
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    tx_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
