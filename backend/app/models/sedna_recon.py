"""Banka ↔ Sedna mutabakat kayıtları (accounting.mutabakat — Uyuşmayan Veriler).

`sedna_bank_recon`: bir banka işlemi ile Sedna 102 fiş satırı arasındaki uyuşmazlık
durumu. Yalnız AÇIK bulgular + kapanmış geçmiş saklanır (birebir eşleşen yüzlerce
satır KAYDEDİLMEZ — koşu sayaçları `sedna_recon_runs`'ta). Kural: banka verisi HER
ZAMAN otorite; Sedna sonradan girilince/düzeltilince kayıt OTOMATİK kapanır
(status=matched, resolution=auto) ve açık listeden düşer.

`sedna_recon_runs`: koşu başlığı (Sedna AccReconOwner deseni) — pencere, sayaçlar,
başarısız hesaplar (tünel kopukluğunda kısmi veriyle sahte uyuşmazlık üretilmez).
"""
from datetime import date as date_type, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# resolution değerleri (DB-saklı)
RESOLUTION_AUTO = "auto"        # sonraki koşuda kendiliğinden eşleşti (Sedna girildi/düzeltildi)
RESOLUTION_MANUAL = "manual"    # kullanıcı "çözüldü" işaretledi
RESOLUTION_IGNORED = "ignored"  # kullanıcı "yoksay" işaretledi (bilinçli fark)


class SednaReconRun(Base):
    __tablename__ = "sedna_recon_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    window_start: Mapped[date_type] = mapped_column(Date)
    window_end: Mapped[date_type] = mapped_column(Date)
    triggered_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    accounts_scanned: Mapped[int] = mapped_column(Integer, server_default="0")
    accounts_skipped: Mapped[int] = mapped_column(Integer, server_default="0")  # eşlemesiz hesap
    matched_count: Mapped[int] = mapped_column(Integer, server_default="0")
    open_count: Mapped[int] = mapped_column(Integer, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, server_default="0")
    auto_closed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class SednaBankRecon(Base):
    __tablename__ = "sedna_bank_recon"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_account_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=True,
    )
    bank_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=True,
    )
    # Banka-dışı varlık sapmaları (Faz B): eşleşmiş çek/cari kaydında Sedna farkı —
    # entity_type: 'check' | 'vendor_tx'; bank_account_id bu kayıtlarda NULL olabilir.
    entity_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Sedna tarafı kimliği (AccountingTrans.RecId — kalıcı referans, Sedna'nın kendi
    # SourceId damgalama deseninin bizdeki karşılığı)
    sedna_trans_rec_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sedna_owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sedna_voucher: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    status: Mapped[str] = mapped_column(String(20))  # constants.ReconStatus
    amount: Mapped[float] = mapped_column(Numeric(15, 2))  # işaretli (+giriş / −çıkış), hesap para biriminde
    currency: Mapped[str] = mapped_column(String(3), server_default="TRY")
    event_date: Mapped[date_type] = mapped_column(Date)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)        # banka açıklaması
    sedna_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Sedna Remark1
    sedna_record_user: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)   # "kime sorulacak"
    sedna_change_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    resolved_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # auto/manual/ignored
    resolution_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_sedna_bank_recon_account_status", "bank_account_id", "status"),
        Index("ix_sedna_bank_recon_btx", "bank_transaction_id"),
        Index("ix_sedna_bank_recon_sedna_rec", "sedna_trans_rec_id"),
        Index("ix_sedna_bank_recon_event_date", "event_date"),
    )
