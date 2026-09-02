"""Acente Grup Yönetimi — CRUD + atama endpoint'leri (sales.acente_mahsup).

Mutasyon mantığı `services/agency_group_service` içindedir (D1-2 deseni, 2026-09-01):
router ve onay executor (`approval_executor` → `sales.acente_mahsup`, payload `_kind`)
AYNI fonksiyonları çağırır. Router yalnız HTTP doğrulama (404/409/400), `check_approval`,
audit (`log_action`) ve WS broadcast yapar.

Onay akışı: POST / PATCH / DELETE / POST /assign `check_approval` ile korunur. Modül kodu oda
tipleriyle ORTAK (`sales.acente_mahsup`) olduğundan payload `_kind` taşır
("agency_group" | "agency_assign"); executor bu anahtarla doğru servise yönlenir, `_kind`
olmayan payload oda tipidir. Bilinen sınır: bekleyen-onay kontrolü (module_code, entity_id)
çiftiyle yapılır → aynı id'li bir oda tipinin bekleyen talebi, aynı id'li grubun
güncellemesini talep kapanana dek 409 ile bloklar (nadir, geçici).

`payment_alignment` (2026-09-01): friday | month_end | checkin | day_1..day_31 —
`models/agency_group.PAYMENT_ALIGNMENT_PATTERN` ile şemada doğrulanır; UI: Acente Mahsup →
"Acente Ayarları" modalı. Daha önce yalnız SQL ile set edilebiliyordu (denetim Y2).
"""

import json
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.approval.approval_check import check_approval
from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.models import AgencyGroup, User
from app.models.agency_group import PAYMENT_ALIGN_FRIDAY, PAYMENT_ALIGNMENT_PATTERN
from app.realtime.sales_broadcast import broadcast_sales_update
from app.services import agency_group_service
from app.utils.audit import log_action

MODULE_CODE = "sales.acente_mahsup"
KIND_GROUP = "agency_group"     # onay payload'ı ayrıştırıcısı (executor)
KIND_ASSIGN = "agency_assign"

router = APIRouter(prefix="/agency-groups", tags=["agency-groups"])


# ─── Şemalar ─────────────────────────────────────────────────────────────────

class AgencyGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    members: List[str] = Field(default_factory=list)
    # Acente Mahsup & Nakit Akım projeksiyon konfigü
    term_days: int = Field(default=30, ge=0, le=365)
    kickback_percent: float = Field(default=0, ge=0, le=100)
    # Ödeme günü hizalaması: friday | month_end | checkin | day_1..day_31
    payment_alignment: str = Field(default=PAYMENT_ALIGN_FRIDAY, max_length=10,
                                   pattern=PAYMENT_ALIGNMENT_PATTERN)


class AgencyGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    members: Optional[List[str]] = None
    term_days: Optional[int] = Field(default=None, ge=0, le=365)
    kickback_percent: Optional[float] = Field(default=None, ge=0, le=100)
    payment_alignment: Optional[str] = Field(default=None, max_length=10,
                                             pattern=PAYMENT_ALIGNMENT_PATTERN)


class AgencyAssignRequest(BaseModel):
    """Acenteyi hedef gruba ata; target_group_id=None ise tüm gruplardan çıkar."""
    agency_name: str = Field(min_length=1, max_length=200)
    target_group_id: Optional[int] = None


class AgencyGroupResponse(BaseModel):
    id: int
    name: str
    members: List[str]
    term_days: int
    kickback_percent: float
    payment_alignment: str

    class Config:
        from_attributes = True


# ─── Yardımcı ────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, group_id: int) -> AgencyGroup:
    g = db.query(AgencyGroup).filter(AgencyGroup.id == group_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Grup bulunamadı")
    return g


def _audit_payload(group: AgencyGroup) -> str:
    return json.dumps({
        "name": group.name, "members": group.members,
        "term_days": group.term_days,
        "kickback_percent": float(group.kickback_percent),
        "payment_alignment": group.payment_alignment,
    }, ensure_ascii=False)


# ─── Endpoint'ler ─────────────────────────────────────────────────────────────

@router.get("/", response_model=List[AgencyGroupResponse])
def list_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Tüm acente gruplarını listele."""
    return db.query(AgencyGroup).order_by(AgencyGroup.name).all()


@router.post("/", response_model=AgencyGroupResponse, status_code=201)
def create_group(
    data: AgencyGroupCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Yeni acente grubu oluştur."""
    name = agency_group_service.normalize_name(data.name)
    if not name:
        raise HTTPException(status_code=400, detail="Grup adı boş olamaz")
    if agency_group_service.find_name_conflict(db, name):
        raise HTTPException(status_code=409, detail="Bu isimde bir grup zaten mevcut")

    approval_resp = check_approval(
        db, MODULE_CODE, 0, current_user.id, "create",
        {**data.model_dump(), "_kind": KIND_GROUP},
    )
    if approval_resp:
        return approval_resp

    try:
        group = agency_group_service.create_group(db, data.model_dump())
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(group)

    log_action(db, current_user.id, "create", "agency_group", group.id, _audit_payload(group))
    broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "create")
    return group


@router.patch("/{group_id}", response_model=AgencyGroupResponse)
def update_group(
    group_id: int,
    data: AgencyGroupUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Grup adı / üyeleri / vade / kickback / ödeme günü hizalamasını güncelle."""
    group = _get_or_404(db, group_id)

    if data.name is not None:
        new_name = agency_group_service.normalize_name(data.name)
        if not new_name:
            raise HTTPException(status_code=400, detail="Grup adı boş olamaz")
        if agency_group_service.find_name_conflict(db, new_name, exclude_id=group_id):
            raise HTTPException(status_code=409, detail="Bu isimde başka bir grup var")

    changes = data.model_dump(exclude_unset=True)
    approval_resp = check_approval(
        db, MODULE_CODE, group.id, current_user.id, "update",
        {**changes, "_kind": KIND_GROUP},
    )
    if approval_resp:
        return approval_resp

    try:
        agency_group_service.apply_group_update(db, group, changes)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(group)

    log_action(db, current_user.id, "update", "agency_group", group.id, _audit_payload(group))
    broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "update")
    return group


@router.delete("/{group_id}", status_code=204)
def delete_group(
    group_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Acente grubunu sil."""
    group = _get_or_404(db, group_id)

    approval_resp = check_approval(
        db, MODULE_CODE, group.id, current_user.id, "delete", {"_kind": KIND_GROUP},
    )
    if approval_resp:
        return approval_resp

    log_action(db, current_user.id, "delete", "agency_group", group.id,
               json.dumps({"name": group.name}, ensure_ascii=False))
    agency_group_service.delete_group(db, group)
    db.commit()

    broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "delete")


@router.post("/assign", response_model=List[AgencyGroupResponse])
def assign_agency(
    data: AgencyAssignRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """
    Tek istekte bir acenteyi gruba ata veya gruptan çıkar (atomik).

    - target_group_id verilmişse: acenteyi mevcut grubundan çıkar, hedefe ekle
    - target_group_id None ise: acenteyi mevcut grubundan çıkar (bireysel yap)
    - Acente zaten hedef grupta ise: no-op (sessizce başarılı döner)

    Dönüş: tüm grupların güncel hali (frontend tek atış ile state'i tazeleyebilsin diye).
    Onay: entity_id = hedef grup (bireysel yapmada 0), payload `_kind="agency_assign"`.
    """
    agency = data.agency_name.strip()
    if not agency:
        raise HTTPException(status_code=400, detail="Acente adı boş olamaz")
    if data.target_group_id is not None:
        _get_or_404(db, data.target_group_id)

    approval_resp = check_approval(
        db, MODULE_CODE, data.target_group_id or 0, current_user.id, "update",
        {"_kind": KIND_ASSIGN, "agency_name": agency, "target_group_id": data.target_group_id},
    )
    if approval_resp:
        return approval_resp

    try:
        result = agency_group_service.assign_agency(db, agency, data.target_group_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if result["changed"]:
        db.commit()
        log_action(
            db, current_user.id, "update", "agency_group_assign", result["target_id"] or 0,
            json.dumps({
                "agency_name": agency,
                "target_group_id": data.target_group_id,
                "target_group_name": result["target_name"],
                "removed_from": result["removed_from"],
            }, ensure_ascii=False),
        )
        broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "update")

    return db.query(AgencyGroup).order_by(AgencyGroup.name).all()
