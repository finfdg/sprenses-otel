"""Planlı gider CRUD — tüm modüller için ortak router fabrikası.

Vergiler, düzenli ödemeler, maaş, stopaj aynı CRUD pattern'ını kullanır.
Bu dosya generic endpoint'ler oluşturur; her modül kendi prefix ve
permission kodu ile bir router alır.

Kullanım:
    router = create_scheduled_router(
        source_type="tax",
        permission_code="accounting.taxes",
        entity_label="Vergi",
    )
"""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.models.user import User
from app.schemas.scheduled import (
    DefinitionCreate,
    DefinitionResponse,
    DefinitionUpdate,
    EntryResponse,
    EntryUpdate,
)
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.recurring_vendor_sync import run_recurring_vendor_sync
from app.services import scheduled_service
from app.utils.pagination import page_meta


def _entry_response(e: ScheduledEntry) -> dict:
    return EntryResponse(
        id=e.id,
        definition_id=e.definition_id,
        source_type=e.source_type,
        entry_date=e.entry_date,
        period_month=e.period_month,
        period_year=e.period_year,
        amount=float(e.amount),
        currency=e.currency,
        description=e.description,
        is_paid=e.is_paid,
        paid_date=e.paid_date,
        notes=e.notes,
        synced_from_cari=e.synced_from_cari,
    ).model_dump()


def _defn_response(d: ScheduledDefinition, include_entries: bool = False) -> dict:
    resp = DefinitionResponse(
        id=d.id,
        source_type=d.source_type,
        name=d.name,
        category=d.category,
        amount=float(d.amount),
        currency=d.currency,
        frequency=d.frequency,
        payment_day=d.payment_day,
        start_month=d.start_month,
        year=d.year,
        notes=d.notes,
        is_active=d.is_active,
        vendor_id=d.vendor_id,
        vendor_name=d.vendor.hesap_adi if d.vendor_id and d.vendor else None,
        billing_offset_months=d.billing_offset_months,
        created_by=d.created_by,
        created_at=d.created_at,
    ).model_dump()
    if include_entries:
        entries = d.entries.order_by(ScheduledEntry.entry_date).all()
        resp["entries"] = [_entry_response(e) for e in entries]
    return resp


def create_scheduled_router(
    source_type: str,
    permission_code: str,
    entity_label: str,
    broadcast_module: str = "scheduled",
    direction: int = -1,
    enable_vendor_sync: bool = False,
) -> APIRouter:
    """Verilen source_type için CRUD router oluştur.

    direction: -1 (gider) veya +1 (gelir). finance_events'e yazılır.
    enable_vendor_sync: True → cari-bağlı tanımların girişlerini cari gerçek faturayla
        senkronlayan ``POST /sync-vendors`` endpoint'i eklenir (yalnız "recurring").
    """

    router = APIRouter()

    # ─── LIST ─────────────────────────────────────────────

    @router.get("/")
    def list_definitions(
        db: Session = Depends(get_db),
        _: User = Depends(require_permission(permission_code, "view")),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        year: Optional[int] = Query(None),
    ):
        q = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.source_type == source_type,
        )
        if year:
            q = q.filter(ScheduledDefinition.year == year)

        total = q.count()
        items = (
            q.order_by(desc(ScheduledDefinition.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return page_meta([_defn_response(d, include_entries=True) for d in items], total, page, page_size)

    # ─── GET (detail) ────────────────────────────────────

    @router.get("/{defn_id}")
    def get_definition(
        defn_id: int,
        db: Session = Depends(get_db),
        _: User = Depends(require_permission(permission_code, "view")),
    ):
        d = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.id == defn_id,
            ScheduledDefinition.source_type == source_type,
        ).first()
        if not d:
            raise HTTPException(status_code=404, detail=f"{entity_label} bulunamadı")
        return _defn_response(d, include_entries=True)

    # ─── CREATE ──────────────────────────────────────────

    @router.post("/", status_code=201)
    def create_definition(
        data: DefinitionCreate,
        request: Request,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        current_user: User = Depends(require_permission(permission_code, "use")),
    ):
        current_year = data.year or date.today().year

        # Onay kontrolü
        approval_resp = check_approval(
            db, permission_code, 0, current_user.id, "create",
            data.model_dump(),
        )
        if approval_resp:
            # Onay gerekiyor — kaydı pasif olarak oluştur (listede "Onayda" görünsün)
            defn = ScheduledDefinition(
                source_type=source_type,
                name=data.name,
                category=data.category,
                amount=data.amount,
                currency=data.currency,
                frequency=data.frequency,
                payment_day=data.payment_day,
                start_month=data.start_month,
                year=current_year,
                notes=data.notes,
                vendor_id=data.vendor_id,
                billing_offset_months=data.billing_offset_months,
                is_active=False,
                created_by=current_user.id,
            )
            db.add(defn)
            db.flush()

            # Onay talebinin entity_id'sini güncelle (temizlik için gerekli)
            resp_body = json.loads(approval_resp.body)
            from app.models.approval import ApprovalRequest
            ar = db.query(ApprovalRequest).filter(
                ApprovalRequest.id == resp_body["request_id"]
            ).first()
            if ar:
                ar.entity_id = defn.id
            db.commit()
            broadcast_finance_update(background_tasks, broadcast_module, "create")
            return approval_resp

        defn = ScheduledDefinition(
            source_type=source_type,
            name=data.name,
            category=data.category,
            amount=data.amount,
            currency=data.currency,
            frequency=data.frequency,
            payment_day=data.payment_day,
            start_month=data.start_month,
            year=current_year,
            notes=data.notes,
            vendor_id=data.vendor_id,
            billing_offset_months=data.billing_offset_months,
            is_active=True,
            created_by=current_user.id,
        )
        db.add(defn)
        db.flush()

        # Girişleri üret + cari-bağlıysa senkronla (router + onay executor ORTAK)
        entries = scheduled_service.post_create(db, defn, direction)

        log_action(
            db, current_user.id, "create", source_type, defn.id,
            json.dumps({
                "name": data.name, "amount": data.amount,
                "frequency": data.frequency, "entries_count": len(entries),
            }, ensure_ascii=False),
            get_client_ip(request),
        )
        db.commit()
        broadcast_finance_update(background_tasks, broadcast_module, "create")
        db.refresh(defn)
        return _defn_response(defn, include_entries=True)

    # ─── UPDATE ──────────────────────────────────────────

    @router.patch("/{defn_id}")
    def update_definition(
        defn_id: int,
        data: DefinitionUpdate,
        request: Request,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        current_user: User = Depends(require_permission(permission_code, "use")),
    ):
        defn = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.id == defn_id,
            ScheduledDefinition.source_type == source_type,
        ).first()
        if not defn:
            raise HTTPException(status_code=404, detail=f"{entity_label} bulunamadı")

        # Onay kontrolü
        approval_resp = check_approval(
            db, permission_code, defn_id, current_user.id, "update",
            data.model_dump(exclude_unset=True),
        )
        if approval_resp:
            return approval_resp

        changes = scheduled_service.apply_definition_update(
            db, defn, data.model_dump(exclude_unset=True), direction
        )
        if not changes:
            return _defn_response(defn, include_entries=True)

        log_action(
            db, current_user.id, "update", source_type, defn.id,
            json.dumps(changes, ensure_ascii=False),
            get_client_ip(request),
        )
        db.commit()
        broadcast_finance_update(background_tasks, broadcast_module, "update")
        db.refresh(defn)
        return _defn_response(defn, include_entries=True)

    # ─── DELETE ──────────────────────────────────────────

    @router.delete("/{defn_id}")
    def delete_definition(
        defn_id: int,
        request: Request,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        current_user: User = Depends(require_permission(permission_code, "use")),
    ):
        defn = db.query(ScheduledDefinition).filter(
            ScheduledDefinition.id == defn_id,
            ScheduledDefinition.source_type == source_type,
        ).first()
        if not defn:
            raise HTTPException(status_code=404, detail=f"{entity_label} bulunamadı")

        # Onay kontrolü
        approval_resp = check_approval(
            db, permission_code, defn_id, current_user.id, "delete", {},
        )
        if approval_resp:
            return approval_resp

        log_action(
            db, current_user.id, "delete", source_type, defn.id,
            json.dumps({"name": defn.name, "amount": float(defn.amount)}, ensure_ascii=False),
            get_client_ip(request),
        )
        scheduled_service.delete_definition(db, defn)  # FE invalidate + CASCADE
        db.commit()
        broadcast_finance_update(background_tasks, broadcast_module, "delete")
        return {"detail": f"{entity_label} silindi"}

    # ─── UPDATE ENTRY (tek giriş düzenleme) ──────────────

    @router.patch("/entries/{entry_id}")
    def update_entry(
        entry_id: int,
        data: EntryUpdate,
        request: Request,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        current_user: User = Depends(require_permission(permission_code, "use")),
    ):
        entry = db.query(ScheduledEntry).filter(
            ScheduledEntry.id == entry_id,
            ScheduledEntry.source_type == source_type,
        ).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Giriş bulunamadı")

        # Onay kontrolü
        entry_payload = {"_target": "entry", **data.model_dump(exclude_unset=True)}
        approval_resp = check_approval(
            db, permission_code, entry_id, current_user.id, "update",
            entry_payload,
        )
        if approval_resp:
            return approval_resp

        changes = scheduled_service.apply_entry_update(
            db, entry, data.model_dump(exclude_unset=True), direction
        )
        if not changes:
            return _entry_response(entry)

        log_action(
            db, current_user.id, "update", f"{source_type}_entry", entry.id,
            json.dumps(changes, ensure_ascii=False),
            get_client_ip(request),
        )
        db.commit()
        broadcast_finance_update(background_tasks, broadcast_module, "update")
        db.refresh(entry)
        return _entry_response(entry)

    # ─── SUMMARY ─────────────────────────────────────────

    @router.get("/summary/totals")
    def get_summary(
        db: Session = Depends(get_db),
        _: User = Depends(require_permission(permission_code, "view")),
        year: Optional[int] = Query(None),
    ):
        target_year = year or date.today().year
        q = db.query(ScheduledEntry).filter(
            ScheduledEntry.source_type == source_type,
        ).join(ScheduledDefinition).filter(
            ScheduledDefinition.year == target_year,
            ScheduledDefinition.is_active == True,  # noqa: E712
        )

        total = q.with_entities(func.sum(ScheduledEntry.amount)).scalar() or 0
        paid = q.filter(
            ScheduledEntry.is_paid == True  # noqa: E712
        ).with_entities(func.sum(ScheduledEntry.amount)).scalar() or 0
        pending = float(total) - float(paid)
        count = q.count()
        paid_count = q.filter(ScheduledEntry.is_paid == True).count()  # noqa: E712

        return {
            "year": target_year,
            "total": float(total),
            "paid": float(paid),
            "pending": pending,
            "count": count,
            "paid_count": paid_count,
        }

    # ─── CARI SENKRON (yalnız vendor-sync etkin modüller, ör. recurring) ──

    if enable_vendor_sync:

        @router.post("/sync-vendors")
        def sync_vendors(
            request: Request,
            background_tasks: BackgroundTasks,
            db: Session = Depends(get_db),
            current_user: User = Depends(require_permission(permission_code, "use")),
        ):
            """Cari-bağlı tanımların aylık girişlerini cari gerçek fatura + ödeme durumuyla senkronla.

            Faturası gelen aylar GERÇEK tutara çekilir + ödeme durumu cariden alınır + çift
            sayım önlemek için recurring finance_event'i silinir. Gelecek aylar tahmini kalır.
            """
            result = run_recurring_vendor_sync(db, current_user, get_client_ip(request))
            broadcast_finance_update(background_tasks, broadcast_module, "update")
            return result

    return router
