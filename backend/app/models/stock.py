"""Stok / Depo Maliyet modülü — Sedna muhasebeden içe aktarılan stok verisi.

Kaynak: Sedna `Store` (depo/departman), `Product` (ürün kartı), `StockOwner`+`StockTrans`
(hareketler). Salt-okunur içe aktarma; maliyet analizi (alış/tüketim, departman, tedarikçi).
"""
from datetime import date as date_type
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Sedna StockOwner.Type → (etiket, yön). Yön: in=giriş/alış, out=çıkış/transfer,
# consume=tüketim (departman maliyeti), count=sayım, other=diğer.
TYPE_MAP = {
    10: ("Devir / Açılış", "in"),
    12: ("Alış", "in"),
    13: ("Bedelsiz Giriş", "in"),
    25: ("Alış (Faturalı)", "in"),
    20: ("Çıkış / Transfer", "out"),
    21: ("Çıkış", "out"),
    29: ("Tüketim", "consume"),
    40: ("Sayım", "count"),
    23: ("Düzeltme", "other"),
}


def type_label(code: Optional[int]) -> str:
    return TYPE_MAP.get(code or 0, ("Diğer", "other"))[0]


def type_direction(code: Optional[int]) -> str:
    return TYPE_MAP.get(code or 0, ("Diğer", "other"))[1]


class StockDepot(Base):
    """Depo / departman tanımı (Sedna Store) — maliyet merkezi."""
    __tablename__ = "stock_depots"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # '001', '002'...
    name: Mapped[str] = mapped_column(String(200))                          # 'ANA MUTFAK'
    no_consumption: Mapped[bool] = mapped_column(Boolean, default=False)
    is_expense: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class StockProduct(Base):
    """Ürün kartı (Sedna Product) + anlık stok + son maliyet."""
    __tablename__ = "stock_products"
    __table_args__ = (
        Index("ix_stock_prod_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sedna_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    code: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    stock_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_stock: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    last_cost: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    current_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)  # stock × cost
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class StockMovement(Base):
    """Stok hareketi (Sedna StockOwner+StockTrans) — alış/tüketim/çıkış, denormalize."""
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_mov_period", "period"),
        Index("ix_stock_mov_dir", "direction"),
        Index("ix_stock_mov_prod", "product_sedna_id"),
        Index("ix_stock_mov_cons", "cons_depot"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sedna_line_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)  # dedup (StockTrans.RecId)
    sedna_owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    date: Mapped[Optional[date_type]] = mapped_column(Date, index=True, nullable=True)
    period: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)  # YYYY-MM
    type_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    type_label: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # in/out/consume/count/other

    product_sedna_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    product_code: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    entry_depot: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    exit_depot: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cons_depot: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    quantity: Mapped[float] = mapped_column(Numeric(18, 3), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    net_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    supplier_code: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    doc_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
