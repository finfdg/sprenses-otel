"""Oda tipi (sales.acente_mahsup) domain servis katmanı — CRUD (HTTP'siz).

D1-2 (2026-06-22): Router (sales/room_types.py create/update/delete) ve onay executor
(_handle_sales_room_types) ORTAK çağırır → tek kaynak, sapma imkansız. HTTP doğrulama
(404/400), response (RoomTypeResponse), approval, audit (log_action) ve broadcast ROUTER'da
kalır; service yalnız mutasyon + delete guard'ı (rezervasyon koruması) yapar.

Onay payload'ı JSON'dur (json.dumps default=str) → tüm alanlar (kod/sayı/bool) zaten
JSON-uyumlu primitifler; room_types'ta tarih/saat alanı YOK, bu yüzden coercion gerekmez.

Delete guard: `Reservation.room_type == rt.code` sayısı > 0 ise silinemez (FK yok; koda
string-bağlı orphan referansı engeller) → ValueError (router 400'e çevirir).
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.reservation import Reservation
from app.models.room_type import RoomType


def create_room_type(db: Session, data: dict) -> RoomType:
    """Yeni oda tipi oluştur (flush/commit ÇAĞIRMAZ — çağıran yapar)."""
    rt = RoomType(
        code=data.get("code", ""),
        name=data.get("name", ""),
        total_rooms=data.get("total_rooms", 0),
        max_occupancy=data.get("max_occupancy", 2),
        sort_order=data.get("sort_order", 0),
        is_active=data.get("is_active", True),
        description=data.get("description"),
    )
    db.add(rt)
    return rt


def apply_room_type_update(db: Session, rt: RoomType, update_data: dict) -> None:
    """Verilen alanları oda tipine uygula (yalnız model kolonları)."""
    for key, value in update_data.items():
        if key.startswith("_"):
            continue
        if hasattr(rt, key):
            setattr(rt, key, value)


def delete_room_type(db: Session, rt: RoomType) -> None:
    """Oda tipini sil — bağlı rezervasyon kaydı varsa ValueError (router 400'e çevirir)."""
    rez_count = (
        db.query(func.count(Reservation.id))
        .filter(Reservation.room_type == rt.code)
        .scalar()
    )
    if rez_count and rez_count > 0:
        raise ValueError(
            f"Bu oda tipine ait {rez_count} rezervasyon kaydı bulunduğu için silinemez. "
            "Bunun yerine 'Pasif' duruma alabilirsiniz."
        )
    db.delete(rt)
