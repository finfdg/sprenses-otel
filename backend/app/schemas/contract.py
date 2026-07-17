"""Kontrat modülü Pydantic şemaları (sales.kontratlar).

Onay payload'ı JSON'a serileşir (default=str) → tarihler string olur; contract_service
tüketirken `_coerce_date` ile date'e çevirir (credit_service deseni). Bu yüzden Create
şemalarında tarih alanları `Optional[date]` ama service string de kabul eder.
"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.contract import (
    ALL_ACTION_TYPES, ALL_COMBINE_RULES, ALL_CONFIDENCE, ALL_CONTRACT_STATUS,
    ALL_DOC_TYPES, ALL_INSTALLMENT_STATUS, ALL_PLAN_TYPES,
)


# --- Kontrat ---
class ContractCreate(BaseModel):
    agency_group_id: int
    code: str = Field(min_length=2, max_length=50)
    title: Optional[str] = Field(default=None, max_length=200)
    legal_counterparty: Optional[str] = Field(default=None, max_length=300)
    signed_date: Optional[date] = None
    season_code: str = Field(min_length=2, max_length=20)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    currency: str = Field(default="EUR", max_length=5)
    fx_rule: Optional[str] = Field(default=None, max_length=40)
    fx_fixed_rate: Optional[float] = Field(default=None, ge=0)
    pricing_model: Optional[str] = Field(default=None, max_length=30)
    board_default: str = Field(default="AI", max_length=10)
    min_stay_default: Optional[int] = Field(default=None, ge=0, le=30)
    release_days_default: Optional[int] = Field(default=None, ge=0, le=60)
    invoice_due_basis: Optional[str] = Field(default=None, max_length=40)
    invoice_due_days: Optional[int] = Field(default=None, ge=0, le=180)
    markets: Optional[List[str]] = None
    exclusive_markets: Optional[List[str]] = None
    closed_markets: Optional[List[str]] = None
    status: str = Field(default="active", pattern="^(" + "|".join(ALL_CONTRACT_STATUS) + ")$")
    supersedes_contract_id: Optional[int] = None
    sedna_contrack_ids: Optional[List[int]] = None
    data_confidence: str = Field(default="verified",
                                 pattern="^(" + "|".join(ALL_CONFIDENCE) + ")$")
    notes: Optional[str] = None


class ContractUpdate(BaseModel):
    agency_group_id: Optional[int] = None
    code: Optional[str] = Field(default=None, min_length=2, max_length=50)
    title: Optional[str] = Field(default=None, max_length=200)
    legal_counterparty: Optional[str] = Field(default=None, max_length=300)
    signed_date: Optional[date] = None
    season_code: Optional[str] = Field(default=None, min_length=2, max_length=20)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    currency: Optional[str] = Field(default=None, max_length=5)
    fx_rule: Optional[str] = Field(default=None, max_length=40)
    fx_fixed_rate: Optional[float] = Field(default=None, ge=0)
    pricing_model: Optional[str] = Field(default=None, max_length=30)
    board_default: Optional[str] = Field(default=None, max_length=10)
    min_stay_default: Optional[int] = Field(default=None, ge=0, le=30)
    release_days_default: Optional[int] = Field(default=None, ge=0, le=60)
    invoice_due_basis: Optional[str] = Field(default=None, max_length=40)
    invoice_due_days: Optional[int] = Field(default=None, ge=0, le=180)
    markets: Optional[List[str]] = None
    exclusive_markets: Optional[List[str]] = None
    closed_markets: Optional[List[str]] = None
    status: Optional[str] = Field(default=None,
                                  pattern="^(" + "|".join(ALL_CONTRACT_STATUS) + ")$")
    supersedes_contract_id: Optional[int] = None
    sedna_contrack_ids: Optional[List[int]] = None
    data_confidence: Optional[str] = Field(default=None,
                                           pattern="^(" + "|".join(ALL_CONFIDENCE) + ")$")
    notes: Optional[str] = None


# --- Alt varlıklar (kind-tabanlı tek uç: şemalar service içinde whitelist'lenir) ---
class PeriodCreate(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    date_start: date
    date_end: date
    release_days: Optional[int] = Field(default=None, ge=0, le=60)
    min_stay: Optional[int] = Field(default=None, ge=0, le=30)


class RoomTypeMapCreate(BaseModel):
    contract_code: str = Field(min_length=1, max_length=40)
    contract_name: Optional[str] = Field(default=None, max_length=120)
    room_type_id: Optional[int] = None
    pricing_basis: Optional[str] = Field(default=None, pattern="^(pp|pu)$")
    occupancy_min: Optional[int] = Field(default=None, ge=0, le=12)
    occupancy_max: Optional[int] = Field(default=None, ge=0, le=12)
    max_adults: Optional[int] = Field(default=None, ge=0, le=12)


class PaymentPlanCreate(BaseModel):
    plan_type: str = Field(pattern="^(" + "|".join(ALL_PLAN_TYPES) + ")$")
    description: Optional[str] = Field(default=None, max_length=300)
    total_amount: Optional[float] = Field(default=None, ge=0)
    currency: str = Field(default="EUR", max_length=5)
    offset_rule: Optional[str] = Field(default=None, max_length=30)
    carryover_rule: Optional[str] = Field(default=None, max_length=300)
    late_interest: Optional[str] = Field(default=None, max_length=150)
    data_confidence: str = Field(default="verified",
                                 pattern="^(" + "|".join(ALL_CONFIDENCE) + ")$")
    notes: Optional[str] = Field(default=None, max_length=500)


class InstallmentCreate(BaseModel):
    plan_id: int
    due_date: Optional[date] = None
    due_event: Optional[str] = Field(default=None, max_length=30)
    offset_days: Optional[int] = Field(default=None, ge=0, le=365)
    amount: Optional[float] = Field(default=None, ge=0)
    percent: Optional[float] = Field(default=None, ge=0, le=100)
    percent_basis: Optional[str] = Field(default=None, max_length=30)
    currency: str = Field(default="EUR", max_length=5)
    status: str = Field(default="pending",
                        pattern="^(" + "|".join(ALL_INSTALLMENT_STATUS) + ")$")
    paid_date: Optional[date] = None
    is_conditional: bool = False
    condition_note: Optional[str] = Field(default=None, max_length=300)
    linked_action_id: Optional[int] = None
    supersedes_installment_id: Optional[int] = None
    data_confidence: str = Field(default="verified",
                                 pattern="^(" + "|".join(ALL_CONFIDENCE) + ")$")
    notes: Optional[str] = Field(default=None, max_length=300)


class ActionCreate(BaseModel):
    action_type: str = Field(pattern="^(" + "|".join(ALL_ACTION_TYPES) + ")$")
    title: Optional[str] = Field(default=None, max_length=200)
    sales_start: Optional[date] = None
    sales_end: Optional[date] = None
    open_ended: bool = False
    basis: Optional[str] = Field(default=None, pattern="^(booking|stay)$")
    combinable: Optional[str] = Field(default=None,
                                      pattern="^(" + "|".join(ALL_COMBINE_RULES) + ")$")
    market_scope: Optional[List[str]] = None
    room_scope: Optional[List[str]] = None
    supersedes_action_id: Optional[int] = None
    source_document_id: Optional[int] = None
    status: str = Field(default="confirmed", pattern="^(proposed|confirmed|superseded)$")
    data_confidence: str = Field(default="verified",
                                 pattern="^(" + "|".join(ALL_CONFIDENCE) + ")$")
    notes: Optional[str] = Field(default=None, max_length=500)


class ActionTierCreate(BaseModel):
    action_id: int
    stay_start: Optional[date] = None
    stay_end: Optional[date] = None
    discount_percent: Optional[float] = Field(default=None, ge=0, le=100)
    fixed_net_price: Optional[float] = Field(default=None, ge=0)
    room_scope: Optional[List[str]] = None
    note: Optional[str] = Field(default=None, max_length=200)


class AllotmentCreate(BaseModel):
    contract_room_type_id: Optional[int] = None
    room_count: int = Field(ge=0, le=500)
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    allotment_type: str = Field(default="allot", pattern="^(allot|guaranteed|free_sale)$")
    guaranteed_share_percent: Optional[float] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = Field(default=None, max_length=300)


class DeductionCreate(BaseModel):
    deduction_type: str = Field(min_length=2, max_length=40)
    percent: Optional[float] = Field(default=None, ge=0, le=100)
    fixed_amount: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=5)
    applies: str = Field(default="per_invoice", pattern="^(per_invoice|season_end|monthly)$")
    tier_from: Optional[float] = Field(default=None, ge=0)
    tier_to: Optional[float] = Field(default=None, ge=0)
    settlement_month: Optional[int] = Field(default=None, ge=1, le=12)
    cumulative_with_kb: bool = True
    notes: Optional[str] = Field(default=None, max_length=300)


class DocumentMetaUpdate(BaseModel):
    contract_id: Optional[int] = None
    doc_type: Optional[str] = Field(default=None,
                                    pattern="^(" + "|".join(ALL_DOC_TYPES) + ")$")
    doc_date: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=500)
