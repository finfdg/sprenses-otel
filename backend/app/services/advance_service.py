"""Avans (advance) domain servis katmanı — CRUD + finance_events (HTTP'siz).

D1-2 (2026-06-22): Router (advances.py) ve onay executor (_handle_finance_avanslar) ORTAK çağırır.
"""
from sqlalchemy.orm import Session

from app.models.advance import Advance
from app.utils.finance_event_service import finance_event_svc


def create_advance(db: Session, data: dict, actor_id) -> Advance:
    adv = Advance(
        agency_name=data.get("agency_name", ""),
        amount=data.get("amount", 0),
        currency=data.get("currency", "TRY"),
        advance_date=data.get("advance_date"),
        notes=data.get("notes"),
        status="pending",
        created_by=actor_id,
    )
    db.add(adv)
    db.flush()
    finance_event_svc.upsert_advance(db, adv)
    return adv


def apply_advance_update(db: Session, adv: Advance, update_data: dict) -> dict:
    """Alanları uygula + finance_event tazele. Döner: changes (boşsa yan etki yok)."""
    changes: dict = {}
    for field, value in update_data.items():
        if field.startswith("_"):
            continue
        old_val = getattr(adv, field)
        if old_val != value:
            changes[field] = {"old": str(old_val), "new": str(value)}
            setattr(adv, field, value)
    if not changes:
        return changes
    finance_event_svc.upsert_advance(db, adv)
    return changes


def delete_advance(db: Session, adv: Advance) -> None:
    finance_event_svc.invalidate(db, "advance", adv.id)
    db.delete(adv)
