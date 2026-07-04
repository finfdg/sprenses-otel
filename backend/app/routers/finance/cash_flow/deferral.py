"""Nakit Koruma — kalıcı öteleme endpoint'i.

Bir ödeme kalemini (cari ödeme, çek, kredi taksiti, KK ekstresi, planlı gider/gelir)
ileri bir tarihe KALICI olarak öteler veya ötelemeyi kaldırır. Doğrudan uygulanır
(onaysız — kullanıcı kararı 2026-07-04); finance.cash_flow **use** + audit + WS broadcast.
"""

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.services.deferral_service import (
    DEFERRABLE_SOURCE_TYPES,
    apply_deferral,
    clear_deferral,
    resync_deferred_event,
)
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update

router = APIRouter()


class DeferRequest(BaseModel):
    source_type: str
    source_id: int
    deferred_to: Optional[str] = None  # YYYY-MM-DD; null → ötelemeyi kaldır
    note: Optional[str] = None


class DeferItem(BaseModel):
    source_type: str
    source_id: int


class DeferBatchRequest(BaseModel):
    items: List[DeferItem]
    deferred_to: Optional[str] = None  # tüm kalemler için aynı tarih; null → kaldır


def _parse_deferred_to(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Geçersiz tarih (YYYY-MM-DD bekleniyor).")


@router.post("/cash-flow/defer")
def defer_payment(
    data: DeferRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Bir ödeme kalemini kalıcı öteler (deferred_to) veya ötelemeyi kaldırır (null)."""
    if data.source_type not in DEFERRABLE_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Bu kalem türü ötelenemez.")

    parsed: Optional[date] = None
    if data.deferred_to is not None:
        try:
            parsed = datetime.strptime(data.deferred_to, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Geçersiz tarih (YYYY-MM-DD bekleniyor).")

    if parsed is None:
        cleared = clear_deferral(db, data.source_type, data.source_id)
        action_detail = "Öteleme kaldırıldı"
    else:
        apply_deferral(db, data.source_type, data.source_id, parsed, current_user.id, data.note)
        cleared = False
        action_detail = f"Öteleme → {parsed.isoformat()}"

    # FinanceEvent.event_date'i hemen yansıt (cache invalidate edildi → _upsert ertelenmiş/orijinal tarihi okur)
    resync_deferred_event(db, data.source_type, data.source_id)

    log_action(
        db, current_user.id, "update", "payment_deferral",
        entity_id=data.source_id,
        details=f"{data.source_type}/{data.source_id} | {action_detail}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "update")

    return {
        "ok": True,
        "deferred_to": parsed.isoformat() if parsed else None,
        "cleared": cleared,
    }


@router.post("/cash-flow/defer-batch")
def defer_payment_batch(
    data: DeferBatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Çok sayıda kalemi TEK istekte aynı tarihe ötele / ötelemeyi kaldır.

    Gruplu öteleme (ör. bir günün 157 cari ödemesi) için — tek transaction, tek
    commit, tek broadcast (157 ayrı POST yerine). Geçersiz türdeki kalem atlanır.
    """
    parsed = _parse_deferred_to(data.deferred_to)
    if not data.items:
        raise HTTPException(status_code=400, detail="Ötelenecek kalem yok.")
    if len(data.items) > 5000:
        raise HTTPException(status_code=400, detail="Tek seferde en fazla 5000 kalem.")

    applied = 0
    touched_vendor = False
    for it in data.items:
        if it.source_type not in DEFERRABLE_SOURCE_TYPES:
            continue
        if parsed is None:
            clear_deferral(db, it.source_type, it.source_id)
        else:
            apply_deferral(db, it.source_type, it.source_id, parsed, current_user.id, None)
        # vendor_payment resync'i GLOBAL sync_vendor_finance_events (tüm carileri FIFO'lar)
        # → döngü içinde çağrılırsa 157 kalemde 157× tam resync = O(N²). Cariler tek
        # kez döngü SONRASI senkronlanır (güncel deferral_map'ten hepsini işler); diğer
        # türler tek-satır resync (ucuz) → döngüde kalır.
        if it.source_type == "vendor_payment":
            touched_vendor = True
        else:
            resync_deferred_event(db, it.source_type, it.source_id)
        applied += 1

    if touched_vendor:
        from app.utils.sync_vendor_fifo import sync_vendor_finance_events
        sync_vendor_finance_events(db)

    log_action(
        db, current_user.id, "update", "payment_deferral",
        entity_id=None,
        details=f"Toplu öteleme: {applied} kalem | {'kaldırıldı' if parsed is None else parsed.isoformat()}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "update")

    return {
        "ok": True,
        "applied": applied,
        "deferred_to": parsed.isoformat() if parsed else None,
        "cleared": parsed is None,
    }
