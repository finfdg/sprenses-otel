"""Kredi kartı ekstre ve işlem modelleri."""
from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    pass


class CreditCardStatement(Base):
    """Kredi kartı ekstre özeti."""
    __tablename__ = "credit_card_statements"
    __table_args__ = (
        Index("ix_cc_stmt_product", "credit_product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("credit_products.id", ondelete="CASCADE"),
    )
    ekstre_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    kesim_tarihi: Mapped[date_type] = mapped_column(Date)
    son_odeme_tarihi: Mapped[date_type] = mapped_column(Date)
    onceki_bakiye: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    donem_harcama: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    faiz_ucret: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    donem_odeme: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    toplam_borc: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    asgari_odeme: Mapped[float] = mapped_column(Numeric(15, 2), default=0)
    # Odeme bilgileri
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    paid_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    # Dosya
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    uploaded_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    product = relationship("CreditProduct", backref="statements")
    transactions = relationship(
        "CreditCardTransaction", back_populates="statement",
        cascade="all, delete-orphan",
    )


class CreditCardTransaction(Base):
    """Kredi kartı ekstre işlem satırı."""
    __tablename__ = "credit_card_transactions"
    __table_args__ = (
        Index("ix_cc_tx_stmt", "statement_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("credit_card_statements.id", ondelete="CASCADE"),
    )
    islem_tarihi: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    aciklama: Mapped[str] = mapped_column(Text)
    kategori: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    taksit_bilgi: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tutar: Mapped[float] = mapped_column(Numeric(15, 2))
    is_credit: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    statement = relationship("CreditCardStatement", back_populates="transactions")
