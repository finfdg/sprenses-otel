"""Otel rezervasyonlarını SednaPrenses (önbüro/PMS) DB'sinden doğrudan içe aktarma.

XLS yüklemenin (Crystal Reports) **canlı** alternatifi: aynı `rec_id` uzayına (RecId) upsert
eder → mükerrer yapmaz, elle dosya gerektirmez. Doluluk (geceleme/pax) maliyet KPI'larını
besler (`occupancy_metrics`). Merkezi Sedna sync'in (`sedna_sync.py`) bir adımı + tekil endpoint.

**Aktif-yalnız değişmezliği (kritik):** `occupancy_metrics` rez_status'a bakmaz — tablodaki HER
rezervasyonu sayar. XLS akışı tabloyu aktif-yalnız tutar (iptaller removal_candidate olur). Bu
senkron da aynı değişmezliği korur: pencere (`checkin >= yıl başı`) içinde **aktif olanları upsert**
eder, **aktif olmayan her kaydı (iptal Status=-1 veya kaynakta silinmiş) siler** → tablo Sedna'nın
aktif rezervasyonlarının birebir aynası olur.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.utils.sales_broadcast import broadcast_sales_update
from app.utils.sedna_client import SednaUnavailable, sedna_configured

from app.services.reservation_service import run_reservation_import

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Durum + içe aktarma endpoint'i (tekil; merkezi sync de çağırır) ─────────

@router.get("/sedna-status")
def reservation_sedna_status(_: User = Depends(get_current_user)):
    """Sedna rezervasyon içe aktarma etkin mi (buton gösterimi)."""
    return {"configured": sedna_configured()}


@router.post("/sedna-import")
def reservation_sedna_import(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales.acente_mahsup", "use")),
):
    """SednaPrenses'ten rezervasyonları içe aktar (tekil; merkezi sync de çağırır)."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        result = run_reservation_import(db, current_user, get_client_ip(request))
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    broadcast_sales_update(background_tasks, BroadcastModule.HOTEL_RESERVATION, "upload")

    return result
