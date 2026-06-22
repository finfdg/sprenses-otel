"""Oda tipleri modülü — Oda tipi master CRUD.

Oda tipleri (`room_types`) doluluk hesaplamasında payda olarak kullanılır:
- `total_rooms` toplamı otel kapasitesini verir (otel toplam oda sayısı)
- Rezervasyonlardaki `room_type` değeri `code` ile eşleşir
- Doluluk = SUM(rooms × nights) / (total_rooms × tarih_aralığı_gün) × 100
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.room_type import RoomType
from app.models.user import User
from app.schemas.room_type import (
    RoomTypeCreate,
    RoomTypeListResponse,
    RoomTypeResponse,
    RoomTypeUpdate,
)
from app.services import room_type_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action

router = APIRouter(prefix="/room-types", tags=["Oda Tipleri"])


# ─── Liste ──────────────────────────────────────────────


@router.get("/", response_model=RoomTypeListResponse)
def list_room_types(
    include_inactive: bool = Query(False, description="Pasif tipleri de döndür"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.room_types", "view")),
):
    """Tüm oda tiplerini sıralı olarak döndür + toplam kapasiteyi hesapla."""
    query = db.query(RoomType)
    if not include_inactive:
        query = query.filter(RoomType.is_active.is_(True))

    items = query.order_by(RoomType.sort_order, RoomType.code).all()

    # Toplam kapasite — aktif/pasif filtresinden bağımsız her zaman aktiflerin toplamı
    total_capacity = (
        db.query(func.coalesce(func.sum(RoomType.total_rooms), 0))
        .filter(RoomType.is_active.is_(True))
        .scalar()
    )
    active_count = (
        db.query(func.count(RoomType.id))
        .filter(RoomType.is_active.is_(True))
        .scalar()
    )

    return RoomTypeListResponse(
        items=[RoomTypeResponse.model_validate(rt) for rt in items],
        total_capacity=int(total_capacity or 0),
        active_count=int(active_count or 0),
    )


# ─── Tek kayıt ──────────────────────────────────────────


@router.get("/{room_type_id}", response_model=RoomTypeResponse)
def get_room_type(
    room_type_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.room_types", "view")),
):
    """Tek oda tipi detayı."""
    rt = db.query(RoomType).filter(RoomType.id == room_type_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="Oda tipi bulunamadı")
    return RoomTypeResponse.model_validate(rt)


# ─── Oluştur ────────────────────────────────────────────


@router.post("/", response_model=RoomTypeResponse, status_code=status.HTTP_201_CREATED)
def create_room_type(
    data: RoomTypeCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.room_types", "use")),
):
    """Yeni oda tipi oluştur."""
    approval_resp = check_approval(
        db, "sales.room_types", 0, current_user.id, "create", data.model_dump(),
    )
    if approval_resp:
        return approval_resp

    rt = room_type_service.create_room_type(db, data.model_dump())
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Bu oda tipi kodu zaten kayıtlı: {data.code}",
        )

    log_action(
        db, current_user.id, "create", "room_type",
        entity_id=rt.id,
        details=f"{rt.code} — {rt.name} ({rt.total_rooms} oda)",
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(rt)
    return RoomTypeResponse.model_validate(rt)


# ─── Güncelle ───────────────────────────────────────────


@router.patch("/{room_type_id}", response_model=RoomTypeResponse)
def update_room_type(
    room_type_id: int,
    data: RoomTypeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.room_types", "use")),
):
    """Oda tipini güncelle."""
    rt = db.query(RoomType).filter(RoomType.id == room_type_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="Oda tipi bulunamadı")

    payload = data.model_dump(exclude_unset=True)
    approval_resp = check_approval(
        db, "sales.room_types", room_type_id, current_user.id, "update", payload,
    )
    if approval_resp:
        return approval_resp

    room_type_service.apply_room_type_update(db, rt, payload)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Bu oda tipi kodu zaten kayıtlı",
        )

    log_action(
        db, current_user.id, "update", "room_type",
        entity_id=rt.id,
        details=f"{rt.code} — {rt.name} ({rt.total_rooms} oda)",
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(rt)
    return RoomTypeResponse.model_validate(rt)


# ─── Sil ────────────────────────────────────────────────


@router.delete("/{room_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room_type(
    room_type_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.room_types", "use")),
):
    """Oda tipini sil — bağlı rezervasyon kaydı varsa engelle (silinmek yerine pasif yapılmalı)."""
    rt = db.query(RoomType).filter(RoomType.id == room_type_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="Oda tipi bulunamadı")

    approval_resp = check_approval(
        db, "sales.room_types", room_type_id, current_user.id, "delete", {},
    )
    if approval_resp:
        return approval_resp

    # Bu koda sahip rezervasyon varsa silinemez (service guard'ı — router 400'e çevirir)
    try:
        room_type_service.delete_room_type(db, rt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        db, current_user.id, "delete", "room_type",
        entity_id=room_type_id,
        details=f"{rt.code} — {rt.name}",
        ip_address=get_client_ip(request),
    )
    db.commit()
