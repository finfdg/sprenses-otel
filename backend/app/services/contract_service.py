"""Kontrat modülü domain servisi (sales.kontratlar) — router + onay executor ORTAK (D1-2).

Mutasyon mantığının TEK kaynağı: `routers/sales/contracts.py` endpoint'leri ve
`approval_executor._handle_sales_kontratlar` aynı fonksiyonları çağırır — davranış
sapması yapısal olarak engellenir (credit_service emsali).

Alt varlıklar (dönem/oda-eşleme/plan/taksit/aksiyon/band/kontenjan/kesinti) tek
`kind` sözlüğü üzerinden yönetilir: onay payload'ı `_kind` alanı taşır, executor
buna göre doğru modele yönlenir. Onay payload'ı JSON'a serileştiğinden (default=str)
tarih alanları string gelebilir → `_coerce_date` normalize eder.
"""
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session, selectinload

from app.models.contract import (
    AgencyContract, ContractAction, ContractActionTier, ContractAllotment,
    ContractChildPolicy, ContractDeduction, ContractDocument, ContractInstallment,
    ContractPaymentPlan, ContractPeriod, ContractRate, ContractRoomType,
)

logger = logging.getLogger(__name__)

# kind → (model, kontrata bağlanma şekli)
# "contract_id": modelde contract_id kolonu var (create'te otomatik set edilir)
# "via_parent": üst kaydı ayrı FK ile bulur (taksit → plan_id, band → action_id)
KIND_MODELS = {
    "periods": (ContractPeriod, "contract_id"),
    "room-types": (ContractRoomType, "contract_id"),
    "plans": (ContractPaymentPlan, "contract_id"),
    "installments": (ContractInstallment, "via_parent"),
    "actions": (ContractAction, "contract_id"),
    "tiers": (ContractActionTier, "via_parent"),
    "allotments": (ContractAllotment, "contract_id"),
    "deductions": (ContractDeduction, "contract_id"),
    "rates": (ContractRate, "contract_id"),
    "child-policies": (ContractChildPolicy, "contract_id"),
}

_DATE_FIELDS = {
    "signed_date", "valid_from", "valid_to", "date_start", "date_end",
    "due_date", "paid_date", "sales_start", "sales_end", "stay_start",
    "stay_end", "doc_date",
}


def _coerce_date(v):
    """Onay payload_json'ı tarihleri string yapar (json.dumps default=str);
    router yolu date objesi geçirir — ikisini de date'e normalize et."""
    if isinstance(v, str) and v:
        return date.fromisoformat(v[:10])
    return v


def _normalize(data: dict) -> dict:
    """Tarih alanlarını coerce et, bilinmeyen anahtar bırakma (Model(**data) güvenliği
    çağıranın şema doğrulamasında — onay yolunda da aynı Pydantic şemadan geçmiş olur)."""
    return {k: (_coerce_date(v) if k in _DATE_FIELDS else v) for k, v in data.items()}


# --- Kontrat CRUD ---

def get_contract(db: Session, contract_id: int) -> Optional[AgencyContract]:
    return (
        db.query(AgencyContract)
        .options(
            selectinload(AgencyContract.periods),
            selectinload(AgencyContract.room_types),
            selectinload(AgencyContract.payment_plans)
            .selectinload(ContractPaymentPlan.installments),
            selectinload(AgencyContract.actions).selectinload(ContractAction.tiers),
            selectinload(AgencyContract.allotments),
            selectinload(AgencyContract.deductions),
            selectinload(AgencyContract.documents),
        )
        .filter(AgencyContract.id == contract_id)
        .first()
    )


def create_contract(db: Session, data: dict) -> AgencyContract:
    obj = AgencyContract(**_normalize(data))
    db.add(obj)
    db.flush()
    return obj


def apply_contract_update(db: Session, contract: AgencyContract, data: dict) -> AgencyContract:
    for k, v in _normalize(data).items():
        setattr(contract, k, v)
    db.flush()
    return contract


def delete_contract(db: Session, contract: AgencyContract) -> None:
    """Kontratı sil — alt varlıklar cascade; belgeler YETİM kalır (contract_id NULL,
    arşiv korunur). Taksiti banka eşleşmeli plan varsa silme reddedilir (iz kaybı)."""
    matched = (
        db.query(ContractInstallment)
        .join(ContractPaymentPlan, ContractInstallment.plan_id == ContractPaymentPlan.id)
        .filter(ContractPaymentPlan.contract_id == contract.id,
                ContractInstallment.bank_transaction_id.isnot(None))
        .count()
    )
    if matched:
        raise ValueError(
            f"Bu kontratın {matched} taksidi banka işlemiyle eşleşmiş — önce eşleşmeleri kaldırın.")
    db.delete(contract)
    db.flush()


# --- Alt varlık CRUD (kind-tabanlı) ---

def _resolve_contract_id_for_child(db: Session, kind: str, data: dict) -> Optional[int]:
    """via_parent türlerinde üst kaydın kontratını bul (yetki/varlık doğrulaması için)."""
    if kind == "installments":
        plan = db.query(ContractPaymentPlan).filter(
            ContractPaymentPlan.id == data.get("plan_id")).first()
        return plan.contract_id if plan else None
    if kind == "tiers":
        action = db.query(ContractAction).filter(
            ContractAction.id == data.get("action_id")).first()
        return action.contract_id if action else None
    return None


def create_child(db: Session, kind: str, contract_id: int, data: dict):
    """Alt varlık oluştur. contract_id'li türlerde kolon otomatik set edilir;
    via_parent türlerinde üst FK payload'da gelir ve kontrata aitliği doğrulanır."""
    model, link = KIND_MODELS[kind]
    payload = _normalize(data)
    if link == "contract_id":
        payload["contract_id"] = contract_id
    else:
        parent_cid = _resolve_contract_id_for_child(db, kind, payload)
        if parent_cid != contract_id:
            raise ValueError("Üst kayıt bu kontrata ait değil.")
    obj = model(**payload)
    db.add(obj)
    db.flush()
    return obj


def get_child(db: Session, kind: str, child_id: int):
    model, _ = KIND_MODELS[kind]
    return db.query(model).filter(model.id == child_id).first()


def apply_child_update(db: Session, kind: str, obj, data: dict):
    """Alt varlık güncelle. Üst-bağ kolonları (contract_id/plan_id/action_id) update'te
    DEĞİŞTİRİLEMEZ — kayıt başka kontrata/plana sessizce taşınamaz (denetim bulgusu #2,
    2026-07-17); taşıma gerekiyorsa sil + yeniden ekle."""
    for parent_key in ("contract_id", "plan_id", "action_id"):
        if parent_key in data and data[parent_key] != getattr(obj, parent_key, None):
            raise ValueError(
                f"'{parent_key}' güncellemeyle değiştirilemez — kaydı silip doğru üst kayda yeniden ekleyin.")
    for k, v in _normalize(data).items():
        setattr(obj, k, v)
    db.flush()
    return obj


def delete_child(db: Session, kind: str, obj) -> None:
    if kind == "installments" and getattr(obj, "bank_transaction_id", None):
        raise ValueError("Banka işlemiyle eşleşmiş taksit silinemez — önce eşleşmeyi kaldırın.")
    db.delete(obj)
    db.flush()


# --- Belge arşivi (onay akışı DIŞI — dosya yükleme istisnası) ---

def create_document(db: Session, agency_group_id: int, file_path: str, original_name: str,
                    doc_type: str, uploaded_by: Optional[int],
                    contract_id: Optional[int] = None, doc_date=None,
                    notes: Optional[str] = None) -> ContractDocument:
    obj = ContractDocument(
        agency_group_id=agency_group_id, contract_id=contract_id,
        doc_type=doc_type, file_path=file_path, original_name=original_name,
        doc_date=_coerce_date(doc_date), uploaded_by=uploaded_by, notes=notes)
    db.add(obj)
    db.flush()
    return obj


def apply_document_meta(db: Session, doc: ContractDocument, data: dict) -> ContractDocument:
    for k, v in _normalize(data).items():
        setattr(doc, k, v)
    db.flush()
    return doc
