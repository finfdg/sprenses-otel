"""Mutabakat dönem kilidi (Faz C) — UYARI modu, bloklamayan.

Tek satırlık tablo: `lock_date` öncesi dönem "kapatılmış" sayılır. Sedna'da dönem
kilidi fiilen kapalı olduğundan (AccPeriodLock 2016'da kalmış) geçmiş aylar her an
değişebilir — bizim kilit SERT DEĞİLDİR: senkron/mutabakat geriye dönük çalışmaya
devam eder, ama kilit-öncesi tarihli YENİ uyuşmazlık tespit edilirse ayrı vurgulu
bildirim üretilir ("kapanmış ay verisi değişti" sinyali).
"""
from datetime import date as date_type, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FinancePeriodLock(Base):
    __tablename__ = "finance_period_locks"

    id: Mapped[int] = mapped_column(primary_key=True)
    lock_date: Mapped[date_type] = mapped_column(Date)  # bu tarihe KADAR (dahil) kapalı dönem
    updated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
