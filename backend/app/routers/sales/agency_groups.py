"""Acente Grup Yönetimi — CRUD endpoint'leri."""

import json
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models import AgencyGroup, User
from app.utils.audit import log_action
from app.utils.sales_broadcast import broadcast_sales_update

router = APIRouter(prefix="/agency-groups", tags=["agency-groups"])


# ─── Şemalar ─────────────────────────────────────────────────────────────────

class AgencyGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    members: List[str] = Field(default_factory=list)
    # Acente Mahsup & Nakit Akım projeksiyon konfigü
    term_days: int = Field(default=30, ge=0, le=365)
    kickback_percent: float = Field(default=0, ge=0, le=100)


class AgencyGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    members: Optional[List[str]] = None
    term_days: Optional[int] = Field(default=None, ge=0, le=365)
    kickback_percent: Optional[float] = Field(default=None, ge=0, le=100)


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

    class Config:
        from_attributes = True


# ─── Yardımcı ────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, group_id: int) -> AgencyGroup:
    g = db.query(AgencyGroup).filter(AgencyGroup.id == group_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Grup bulunamadı")
    return g


# ─── Endpoint'ler ─────────────────────────────────────────────────────────────

@router.get("/", response_model=List[AgencyGroupResponse])
def list_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.acente_mahsup", "view")),
):
    """Tüm acente gruplarını listele."""
    return db.query(AgencyGroup).order_by(AgencyGroup.name).all()


@router.post("/", response_model=AgencyGroupResponse, status_code=201)
def create_group(
    data: AgencyGroupCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.acente_mahsup", "use")),
):
    """Yeni acente grubu oluştur."""
    existing = db.query(AgencyGroup).filter(AgencyGroup.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Bu isimde bir grup zaten mevcut")

    group = AgencyGroup(name=data.name.strip().upper(), members=data.members,
                        term_days=data.term_days, kickback_percent=data.kickback_percent)
    db.add(group)
    db.commit()
    db.refresh(group)

    log_action(db, current_user.id, "create", "agency_group", group.id,
               json.dumps({"name": group.name, "members": group.members,
                           "term_days": group.term_days,
                           "kickback_percent": float(group.kickback_percent)}, ensure_ascii=False))

    broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "create")

    return group


@router.patch("/{group_id}", response_model=AgencyGroupResponse)
def update_group(
    group_id: int,
    data: AgencyGroupUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.acente_mahsup", "use")),
):
    """Grup adını ve/veya üyelerini güncelle."""
    group = _get_or_404(db, group_id)

    if data.name is not None:
        new_name = data.name.strip().upper()
        conflict = db.query(AgencyGroup).filter(
            AgencyGroup.name == new_name,
            AgencyGroup.id != group_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Bu isimde başka bir grup var")
        group.name = new_name

    if data.members is not None:
        # Boş ve tekrar eden değerleri temizle
        group.members = list(dict.fromkeys(m.strip() for m in data.members if m.strip()))

    if data.term_days is not None:
        group.term_days = data.term_days
    if data.kickback_percent is not None:
        group.kickback_percent = data.kickback_percent

    db.commit()
    db.refresh(group)

    log_action(db, current_user.id, "update", "agency_group", group.id,
               json.dumps({"name": group.name, "members": group.members,
                           "term_days": group.term_days,
                           "kickback_percent": float(group.kickback_percent)}, ensure_ascii=False))

    broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "update")

    return group


@router.delete("/{group_id}", status_code=204)
def delete_group(
    group_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.acente_mahsup", "use")),
):
    """Acente grubunu sil."""
    group = _get_or_404(db, group_id)
    log_action(db, current_user.id, "delete", "agency_group", group.id,
               json.dumps({"name": group.name}, ensure_ascii=False))
    db.delete(group)
    db.commit()

    broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "delete")


@router.post("/assign", response_model=List[AgencyGroupResponse])
def assign_agency(
    data: AgencyAssignRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.acente_mahsup", "use")),
):
    """
    Tek istekte bir acenteyi gruba ata veya gruptan çıkar (atomik).

    - target_group_id verilmişse: acenteyi mevcut grubundan çıkar, hedefe ekle
    - target_group_id None ise: acenteyi mevcut grubundan çıkar (bireysel yap)
    - Acente zaten hedef grupta ise: no-op (sessizce başarılı döner)

    Dönüş: tüm grupların güncel hali (frontend tek atış ile state'i tazeleyebilsin diye).
    """
    agency = data.agency_name.strip()
    if not agency:
        raise HTTPException(status_code=400, detail="Acente adı boş olamaz")

    # Hedef grubu doğrula (verildiyse)
    target: Optional[AgencyGroup] = None
    if data.target_group_id is not None:
        target = _get_or_404(db, data.target_group_id)

    # Mevcut grubu bul (acente birden fazla grupta olmamalı ama defansif tara)
    all_groups = db.query(AgencyGroup).order_by(AgencyGroup.name).all()
    current_groups = [g for g in all_groups if agency in (g.members or [])]

    # Hedef ile aynı gruptaysa ve tek grupta ise no-op
    if target and len(current_groups) == 1 and current_groups[0].id == target.id:
        return all_groups

    changed: List[AgencyGroup] = []

    # Mevcut tüm gruplardan çıkar
    for g in current_groups:
        if target and g.id == target.id:
            continue  # Hedef bu grupsa atla; aşağıda zaten eklenecek
        g.members = [m for m in (g.members or []) if m != agency]
        changed.append(g)

    # Hedefe ekle (yoksa)
    if target and agency not in (target.members or []):
        target.members = [*(target.members or []), agency]
        changed.append(target)

    if not changed:
        return all_groups

    db.commit()

    log_action(
        db, current_user.id, "update", "agency_group_assign", target.id if target else 0,
        json.dumps({
            "agency_name": agency,
            "target_group_id": data.target_group_id,
            "target_group_name": target.name if target else None,
            "removed_from": [g.name for g in current_groups if not target or g.id != target.id],
        }, ensure_ascii=False),
    )

    broadcast_sales_update(background_tasks, BroadcastModule.AGENCY_GROUPS, "update")

    # Güncellenmiş tüm grup listesini döndür
    return db.query(AgencyGroup).order_by(AgencyGroup.name).all()
