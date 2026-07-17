"""Acente kontrat modeli — tur operatörü sözleşme/dönem/ödeme planı/aksiyon temsili.

Tasarım kaynağı: 2026-07-17 kontrat klasörü analizi (16 operatör, 96 belge).
Çapa varlık `agency_groups` — tüzel kişi ayrımı (Odeon ≠ Coral tek ticari grup, üç
kontrat) GRUP düzeyinde değil KONTRAT düzeyinde tutulur (`legal_counterparty`).

Yapısal kararlar:
- Dönemler (`contract_periods`) aynı `code` ile birden çok satır olabilir — AllTours'un
  çift takvim bandı (P1 = 26.03–30.04 + 22.10–31.10) böyle temsil edilir.
- Ödeme planı iki katman: plan (avans/EB ön ödemesi/fatura vadesi arketipleri) +
  taksitler (sabit tarih VEYA olay+offset; sabit tutar VEYA yüzde). Addendum ile öne
  çekilen taksit `supersedes_installment_id` zinciriyle izlenir (AllTours 16.01.2026).
- Aksiyonlar booking- VEYA stay-bazlı olabilir (`basis`); kombinasyon aritmetiği
  operatöre göre değişir (`combinable`: Pegas kümüle, Coral/Odeon best-price,
  2026 net SPO'ları birleşmez). Revizyon `supersedes_action_id` zinciri.
- `data_confidence`: taranmış belgeden okunan değerler operatör teyidine dek
  `scanned_approx` işaretlenir (Pegas vade 28→21 elle, Akdem %50→%30 elle,
  Odeon 75/77/91 oda çelişkisi) — fiyat doğrulama bu bayrağı dikkate almalı.
- Fiyat matrisi (`contract_rates`) ve çocuk politikası tabloları BİLİNÇLİ ertelendi
  (Faz 4 fiyat doğrulama ile gelecek) — bu dosya arşiv/nakit-akım katmanını taşır.
"""
from datetime import date as date_type, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric,
    String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# --- Sabitler (merkezi — sihirli string yasak) ---
CONFIDENCE_VERIFIED = "verified"
CONFIDENCE_SCANNED = "scanned_approx"
CONFIDENCE_NEEDS_CONFIRM = "needs_confirmation"
ALL_CONFIDENCE = (CONFIDENCE_VERIFIED, CONFIDENCE_SCANNED, CONFIDENCE_NEEDS_CONFIRM)

CONTRACT_STATUS_DRAFT = "draft"
CONTRACT_STATUS_ACTIVE = "active"
CONTRACT_STATUS_SUPERSEDED = "superseded"
ALL_CONTRACT_STATUS = (CONTRACT_STATUS_DRAFT, CONTRACT_STATUS_ACTIVE, CONTRACT_STATUS_SUPERSEDED)

PLAN_TYPE_ADVANCE = "advance"              # sabit tarihli büyük avans (AllTours 6M€, W2M 1,6M€)
PLAN_TYPE_EB_PREPAYMENT = "eb_prepayment"  # EB booking-list ön ödemesi (%25/%50/%90)
PLAN_TYPE_GUARANTEE_CHECK = "guarantee_check"  # çek bazlı avans/teminat (Odeon 8 çek, Webres)
PLAN_TYPE_INVOICE_TERMS = "invoice_terms"  # konaklama faturası vade kuralı
ALL_PLAN_TYPES = (PLAN_TYPE_ADVANCE, PLAN_TYPE_EB_PREPAYMENT,
                  PLAN_TYPE_GUARANTEE_CHECK, PLAN_TYPE_INVOICE_TERMS)

INSTALLMENT_PENDING = "pending"
INSTALLMENT_PAID = "paid"
INSTALLMENT_CANCELLED = "cancelled"
INSTALLMENT_SUPERSEDED = "superseded"
ALL_INSTALLMENT_STATUS = (INSTALLMENT_PENDING, INSTALLMENT_PAID,
                          INSTALLMENT_CANCELLED, INSTALLMENT_SUPERSEDED)

ACTION_EARLY_BOOKING = "early_booking"
ACTION_SPO = "spo"
ACTION_LONG_STAY = "long_stay"
ACTION_RELEASE_REVISION = "release_revision"
ACTION_CHILD_POLICY_REVISION = "child_policy_revision"
ACTION_CLOSEOUT = "closeout"
ACTION_PRICE_UPDATE = "price_update"
ACTION_OTHER = "other"
ALL_ACTION_TYPES = (ACTION_EARLY_BOOKING, ACTION_SPO, ACTION_LONG_STAY,
                    ACTION_RELEASE_REVISION, ACTION_CHILD_POLICY_REVISION,
                    ACTION_CLOSEOUT, ACTION_PRICE_UPDATE, ACTION_OTHER)

COMBINE_CUMULATIVE = "cumulative"        # yüzdeler toplanır (Pegas %20+%10+%2)
COMBINE_BEST_PRICE = "best_price"        # en ucuz kazanır (Coral/Odeon)
COMBINE_NON_COMBINABLE = "non_combinable"
COMBINE_KB_ONLY = "kb_only"              # yalnız kickback ile birleşir
ALL_COMBINE_RULES = (COMBINE_CUMULATIVE, COMBINE_BEST_PRICE,
                     COMBINE_NON_COMBINABLE, COMBINE_KB_ONLY)

DEDUCTION_KICKBACK_INVOICE = "kickback_invoice"      # fatura-başı % kesinti
DEDUCTION_KICKBACK_SEASON = "kickback_seasonend"     # sezon sonu ciro bareminden
DEDUCTION_ADVERTISEMENT = "advertisement"
DEDUCTION_REPRESENTATIVE = "representative_fee"
DEDUCTION_RATE_PROTECTION = "rate_protection"
DEDUCTION_FLIGHT_SUPPORT = "flight_support"
DEDUCTION_MARKETING_FIXED = "marketing_fixed"        # sabit tutar (Odeon 3.000€)
DEDUCTION_TURNOVER_BONUS = "turnover_bonus"          # ciro primi (Akay %2, Pegas)
DEDUCTION_OTHER = "other"

DOC_TYPE_CONTRACT = "contract"
DOC_TYPE_ANNEX = "annex"
DOC_TYPE_PROTOCOL = "protocol"
DOC_TYPE_RATELIST = "ratelist"
DOC_TYPE_SPO = "spo"
DOC_TYPE_EMAIL = "email"
DOC_TYPE_OTHER = "other"
ALL_DOC_TYPES = (DOC_TYPE_CONTRACT, DOC_TYPE_ANNEX, DOC_TYPE_PROTOCOL,
                 DOC_TYPE_RATELIST, DOC_TYPE_SPO, DOC_TYPE_EMAIL, DOC_TYPE_OTHER)


class AgencyContract(Base):
    """Tur operatörü kontratı — sezon başına bir kayıt (revizyon zinciri supersedes ile)."""

    __tablename__ = "agency_contracts"
    __table_args__ = (
        Index("ix_agency_contracts_group", "agency_group_id"),
        Index("ix_agency_contracts_season", "season_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_groups.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True)      # "ALLTOURS-S26"
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    legal_counterparty: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    signed_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    season_code: Mapped[str] = mapped_column(String(20))            # S26 / W26-27 / YEARLY
    valid_from: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(5), server_default="EUR")
    fx_rule: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    fx_fixed_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    pricing_model: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    board_default: Mapped[str] = mapped_column(String(10), server_default="AI")
    min_stay_default: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    release_days_default: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    invoice_due_basis: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    invoice_due_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    markets: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    exclusive_markets: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    closed_markets: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default=CONTRACT_STATUS_ACTIVE)
    supersedes_contract_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="SET NULL"), nullable=True)
    sedna_contrack_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    data_confidence: Mapped[str] = mapped_column(String(30), server_default=CONFIDENCE_VERIFIED)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    periods = relationship("ContractPeriod", cascade="all, delete-orphan",
                           order_by="ContractPeriod.date_start", back_populates="contract")
    room_types = relationship("ContractRoomType", cascade="all, delete-orphan",
                              back_populates="contract")
    payment_plans = relationship("ContractPaymentPlan", cascade="all, delete-orphan",
                                 back_populates="contract")
    actions = relationship("ContractAction", cascade="all, delete-orphan",
                           order_by="ContractAction.sales_start", back_populates="contract")
    allotments = relationship("ContractAllotment", cascade="all, delete-orphan",
                              back_populates="contract")
    deductions = relationship("ContractDeduction", cascade="all, delete-orphan",
                              back_populates="contract")
    documents = relationship("ContractDocument", back_populates="contract")


class ContractDocument(Base):
    """Kontrat belge arşivi — PDF/Excel/e-posta; kontrat FK'sı opsiyonel (önce yükle,
    sonra bağla akışı için) ama grup her zaman bilinir."""

    __tablename__ = "contract_documents"
    __table_args__ = (Index("ix_contract_documents_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_groups.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="SET NULL"), nullable=True)
    doc_type: Mapped[str] = mapped_column(String(20), server_default=DOC_TYPE_OTHER)
    file_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str] = mapped_column(String(255))
    doc_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract = relationship("AgencyContract", back_populates="documents")


class ContractPeriod(Base):
    """Sezon fiyat dönemi — aynı code ile birden çok takvim bandı olabilir."""

    __tablename__ = "contract_periods"
    __table_args__ = (Index("ix_contract_periods_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(10))                   # A..H / P1..P6
    date_start: Mapped[date_type] = mapped_column(Date)
    date_end: Mapped[date_type] = mapped_column(Date)
    release_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_stay: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    contract = relationship("AgencyContract", back_populates="periods")


class ContractRoomType(Base):
    """Kontrat oda kodu ↔ PMS oda tipi köprüsü (agency_code_map deseni)."""

    __tablename__ = "contract_room_types"
    __table_args__ = (Index("ix_contract_room_types_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    contract_code: Mapped[str] = mapped_column(String(40))          # DZA / RSDW / H12BAL...
    contract_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    room_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("room_types.id", ondelete="SET NULL"), nullable=True)
    pricing_basis: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # pp/pu
    occupancy_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    occupancy_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_adults: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    contract = relationship("AgencyContract", back_populates="room_types")


class ContractPaymentPlan(Base):
    """Ödeme planı başlığı — 5 arketipten biri (plan_type); taksitler ayrı satır."""

    __tablename__ = "contract_payment_plans"
    __table_args__ = (Index("ix_contract_payment_plans_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(30))
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(5), server_default="EUR")
    offset_rule: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)   # offset_100/none
    carryover_rule: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    late_interest: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    data_confidence: Mapped[str] = mapped_column(String(30), server_default=CONFIDENCE_VERIFIED)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    contract = relationship("AgencyContract", back_populates="payment_plans")
    installments = relationship("ContractInstallment", cascade="all, delete-orphan",
                                order_by="ContractInstallment.due_date",
                                back_populates="plan")


class ContractAction(Base):
    """EB/SPO/revizyon aksiyonu — booking- veya stay-bazlı; supersedes revizyon zinciri."""

    __tablename__ = "contract_actions"
    __table_args__ = (Index("ix_contract_actions_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sales_start: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    sales_end: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    open_ended: Mapped[bool] = mapped_column(Boolean, server_default="false")  # "ikinci bildirime kadar"
    basis: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)    # booking/stay
    combinable: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    market_scope: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    room_scope: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    supersedes_action_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_actions.id", ondelete="SET NULL"), nullable=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default="confirmed")
    data_confidence: Mapped[str] = mapped_column(String(30), server_default=CONFIDENCE_VERIFIED)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    contract = relationship("AgencyContract", back_populates="actions")
    tiers = relationship("ContractActionTier", cascade="all, delete-orphan",
                         back_populates="action")


class ContractActionTier(Base):
    """Aksiyonun konaklama bandı — %45/%40/%30 dilimleri veya sabit net fiyat."""

    __tablename__ = "contract_action_tiers"
    __table_args__ = (Index("ix_contract_action_tiers_action", "action_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contract_actions.id", ondelete="CASCADE"), nullable=False)
    stay_start: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    stay_end: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    discount_percent: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    fixed_net_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    room_scope: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    action = relationship("ContractAction", back_populates="tiers")


class ContractInstallment(Base):
    """Ödeme taksidi — nakit akımın kalbi. Sabit tarih (avans) veya olay+offset (fatura
    vadesi) veya EB-liste yüzdesi. Koşullu taksitler (W2M %70 şartı) ayrı bayrakla."""

    __tablename__ = "contract_installments"
    __table_args__ = (
        Index("ix_contract_installments_plan", "plan_id"),
        Index("ix_contract_installments_due", "due_date"),
        Index("ix_contract_installments_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contract_payment_plans.id", ondelete="CASCADE"), nullable=False)
    due_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    due_event: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # checkout/invoice/eb_list
    offset_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    percent: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    percent_basis: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # booking_list/invoice
    currency: Mapped[str] = mapped_column(String(5), server_default="EUR")
    status: Mapped[str] = mapped_column(String(20), server_default=INSTALLMENT_PENDING)
    paid_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    bank_transaction_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bank_transactions.id", ondelete="SET NULL"), nullable=True)
    is_conditional: Mapped[bool] = mapped_column(Boolean, server_default="false")
    condition_note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    linked_action_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_actions.id", ondelete="SET NULL"), nullable=True)
    supersedes_installment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_installments.id", ondelete="SET NULL"), nullable=True)
    data_confidence: Mapped[str] = mapped_column(String(30), server_default=CONFIDENCE_VERIFIED)
    notes: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    plan = relationship("ContractPaymentPlan", back_populates="installments")


class ContractAllotment(Base):
    """Kontenjan — oda tipi bazında tahsis; garanti payı (AllTours %80) ayrı alan."""

    __tablename__ = "contract_allotments"
    __table_args__ = (Index("ix_contract_allotments_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    contract_room_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_room_types.id", ondelete="SET NULL"), nullable=True)
    room_count: Mapped[int] = mapped_column(Integer)
    date_start: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    date_end: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    allotment_type: Mapped[str] = mapped_column(String(20), server_default="allot")  # allot/guaranteed/free_sale
    guaranteed_share_percent: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    contract = relationship("AgencyContract", back_populates="allotments")


class ContractDeduction(Base):
    """Kesinti kalemi — fatura-başı % VE sezon-sonu baremli katmanlar aynı kontratta
    olabilir (Odeon: %5 KB + %1+%1 + 3.000€ + uçak %1–4). agency_groups.kickback_percent'in
    genellemesi; Faz 3 mutabakat hesaplayıcısının veri kaynağı."""

    __tablename__ = "contract_deductions"
    __table_args__ = (Index("ix_contract_deductions_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    deduction_type: Mapped[str] = mapped_column(String(40))
    percent: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    fixed_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    applies: Mapped[str] = mapped_column(String(20), server_default="per_invoice")  # per_invoice/season_end/monthly
    tier_from: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    tier_to: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    settlement_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Odeon Kasım=11
    cumulative_with_kb: Mapped[bool] = mapped_column(Boolean, server_default="true")
    notes: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    contract = relationship("AgencyContract", back_populates="deductions")


class ContractRate(Base):
    """Fiyat matrisi satırı (Faz 4) — 4 arketip tek yapıda:
    saf PP/PU → base_price; PP×çarpan → base_price+multiplier;
    kombinasyon-toplam (DerTour/Fun&Sun) → fixed_total. Veri girişi Faz 4b."""

    __tablename__ = "contract_rates"
    __table_args__ = (
        Index("ix_contract_rates_contract", "contract_id"),
        Index("ix_contract_rates_period", "period_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    period_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_periods.id", ondelete="CASCADE"), nullable=True)
    contract_room_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_room_types.id", ondelete="CASCADE"), nullable=True)
    board: Mapped[str] = mapped_column(String(10), server_default="AI")
    occupancy_code: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # 2AD / SGL / 2AD+1CHD(7-17)
    price_type: Mapped[str] = mapped_column(String(20), server_default="per_person_night")
    base_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    multiplier: Mapped[Optional[float]] = mapped_column(Numeric(6, 3), nullable=True)
    fixed_total: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    min_payer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    market_scope: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    data_confidence: Mapped[str] = mapped_column(String(30), server_default=CONFIDENCE_VERIFIED)
    notes: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)


class ContractChildPolicy(Base):
    """Çocuk yaş bandı politikası (Faz 4) — rezervasyonda yaş verisi olmadığından
    doğrulama yaklaşık kalır (tolerans eşiğiyle)."""

    __tablename__ = "contract_child_policies"
    __table_args__ = (Index("ix_contract_child_policies_contract", "contract_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agency_contracts.id", ondelete="CASCADE"), nullable=False)
    contract_room_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contract_room_types.id", ondelete="SET NULL"), nullable=True)
    child_order: Mapped[int] = mapped_column(Integer, server_default="1")
    age_min: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    age_max: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    discount_percent: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    fixed_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    period_scope: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    data_confidence: Mapped[str] = mapped_column(String(30), server_default=CONFIDENCE_VERIFIED)
    notes: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
