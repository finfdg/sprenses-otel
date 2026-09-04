"""Avans (advance) domain servis katmanı — CRUD + finance_events (HTTP'siz).

D1-2 (2026-06-22): Router (advances.py) ve onay executor (_handle_finance_avanslar) ORTAK çağırır.

`summary(db)` (2026-09-02, yeniden yapılandırma — BİREBİR/verbatim taşıma): `GET /avanslar/summary`
endpoint'inin (routers/finance/advances.py `advance_summary`) gövdesi değiştirilmeden buraya alındı;
endpoint ince sarmalayıcı olarak sonucu olduğu gibi döner. Finansal parmak-izi
(`audit_finance_invariants._inv_avans_modul_ozet`) bu hesabı ölçer — gövde oynatılamaz.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.advance import Advance
from app.services.finance_event_service import finance_event_svc


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


# ─── Özet (router GET /summary ince sarmalayıcı; 2026-09-02 verbatim taşıma) ───

def summary(db: Session):
    """Özet: bekleyen ve alınan toplam tutarlar (para birimine göre)."""
    rows = (
        db.query(
            Advance.currency,
            Advance.status,
            func.sum(Advance.amount).label("total_amount"),
            func.count(Advance.id).label("count"),
        )
        .filter(Advance.status != "cancelled")
        .group_by(Advance.currency, Advance.status)
        .all()
    )

    result = {}
    for currency, status, total_amount, count in rows:
        if currency not in result:
            result[currency] = {"pending": 0.0, "received": 0.0, "pending_count": 0, "received_count": 0}
        if status == "pending":
            result[currency]["pending"] = float(total_amount or 0)
            result[currency]["pending_count"] = count
        elif status == "received":
            result[currency]["received"] = float(total_amount or 0)
            result[currency]["received_count"] = count

    return result
