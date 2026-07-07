"""Nakit Akım — bekletme (hold) endpoint'i.

Bir veya çok BEKLEYEN kalemi "beklemeye alır" (akım-dışı park) veya bekletmeyi kaldırır.
Held future-pending kalem nakit akım hesaplarından dışlanır, ayrı Bekleme Listesi'nde gösterilir.
Doğrudan uygulanır (onaysız — öteleme gibi operasyonel); finance.cash_flow **use** + audit + WS broadcast.
"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.services.hold_service import HOLDABLE_SOURCE_TYPES, apply_holds_batch
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update

router = APIRouter()


class HoldItem(BaseModel):
    source_type: str
    source_id: int


class HoldBatchRequest(BaseModel):
    items: List[HoldItem]
    held: bool  # True → beklemeye al, False → bekletmeyi kaldır


@router.post("/cash-flow/hold-batch")
def hold_batch(
    data: HoldBatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "use")),
):
    """Çok sayıda BEKLEYEN kalemi TEK istekte beklemeye al (held=True) / çıkar (held=False).

    Toplu cari satırı = altındaki tüm hareketler birlikte. Geçersiz/holdable-dışı tür atlanır.
    """
    if not data.items:
        raise HTTPException(status_code=400, detail="İşlem yapılacak kalem yok.")
    if len(data.items) > 5000:
        raise HTTPException(status_code=400, detail="Tek seferde en fazla 5000 kalem.")

    applied = apply_holds_batch(
        db,
        [(it.source_type, it.source_id) for it in data.items],
        data.held,
        current_user.id,
    )

    log_action(
        db, current_user.id, "update", "cash_flow_hold",
        entity_id=None,
        details=f"Toplu bekletme: {applied} kalem | {'beklemeye alındı' if data.held else 'bekletme kaldırıldı'}",
        ip_address=get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.CASH_FLOW, "update")

    return {"ok": True, "applied": applied, "held": data.held}
