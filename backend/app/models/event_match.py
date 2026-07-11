"""Kalıcı eşleşme izi + kur farkı kayıtları (Faz B — Sedna AccountingMatch deseni).

`event_matches`: bugünkü tek sayılık match_number'ın üst modeli — hangi banka kaynağı
hangi kalemi hangi tutarla/kurla/yöntemle kapattı. SALT-EK katman: finance_events
is_matched/match_number davranışı DEĞİŞMEZ; match() yazar, unmatch() siler. İleride
öneri kuyruğu (method='suggestion') ve kısmi/1-N eşleşme aynı şemayı kullanır.

`fx_differences`: çapraz-para eşleşme/değerleme kur farkı (Sedna 646/656 eşleniği).
finance_events'e kalem YAZILMAZ (nakit değil — kullanıcı kararı 2026-07-11).
"""
from datetime import date as date_type, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# event_matches.method değerleri (DB-saklı)
MATCH_METHOD_AUTO = "auto"            # otomatik matcher (matching_service)
MATCH_METHOD_MANUAL = "manual"        # kullanıcı eşleştirmesi (match endpoint'leri)
MATCH_METHOD_SUGGESTION = "suggestion"  # öneri kuyruğu (Faz 1 — henüz üretilmiyor)


class EventMatch(Base):
    __tablename__ = "event_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bank_source_type: Mapped[str] = mapped_column(String(30))   # genelde 'bank'
    bank_source_id: Mapped[int] = mapped_column(Integer)
    target_source_type: Mapped[str] = mapped_column(String(30))  # check/credit/advance/cc_payment/...
    target_source_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # kapatılan tutar (hedef pb)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    rate_used: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    method: Mapped[str] = mapped_column(String(12), server_default=MATCH_METHOD_AUTO)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_event_matches_bank", "bank_source_type", "bank_source_id"),
        Index("ix_event_matches_target", "target_source_type", "target_source_id"),
    )


class FxDifference(Base):
    __tablename__ = "fx_differences"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_match_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_matches.id", ondelete="CASCADE"), nullable=True,
    )
    period: Mapped[date_type] = mapped_column(Date)  # gerçekleşme/değerleme tarihi
    amount_try: Mapped[float] = mapped_column(Numeric(15, 2))  # işaretli: + kambiyo karı / − zararı
    rate_estimate: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    rate_realized: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    expected_try: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    realized_try: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(12), server_default="match")  # match | revaluation
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_fx_differences_period", "period"),
    )
