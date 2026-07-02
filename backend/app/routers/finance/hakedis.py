"""Hak Ediş Takibi — acente/firma (120.*) fatura alacaklarının vade takibi.

Çıkışta kesilen fatura = hak ediş; firma anlaşma vadesi (30/45 gün, yerelde
`receivable_terms`) içinde ödemeli. Bu router `receivable_service` üzerinden
firma bazlı yaşlandırma + fatura detayını sunar; vade tanımı mutasyonu onay
akışına tabidir (executor da AYNI service'i çağırır — D1-2).
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.receivable_term import ReceivableTerm
from app.models.user import User
from app.schemas.receivable import ReceivableTermUpdate
from app.services import receivable_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action

router = APIRouter(prefix="/hakedis", tags=["Hak Ediş Takibi"])


@router.get("/")
def list_receivables(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.hakedis", "view")),
):
    """Firma bazlı açık hak ediş listesi + yaşlandırma + özet (tek çağrı)."""
    return receivable_service.compute_receivables(db)


@router.get("/firms/{customer_code}/invoices")
def firm_invoices(
    customer_code: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.hakedis", "view")),
):
    """Bir firmanın açık/kısmi faturaları — vade, gecikme, kalan tutar."""
    items = receivable_service.firm_open_invoices(db, customer_code)
    return {"items": items, "count": len(items)}


@router.patch("/terms/{customer_code}")
def update_term(
    customer_code: str,
    data: ReceivableTermUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.hakedis", "use")),
):
    """Firma vade tanımı upsert (30/45 gün anlaşma vadesi)."""
    existing = db.query(ReceivableTerm).filter(
        ReceivableTerm.customer_code == customer_code).first()

    approval_resp = check_approval(
        db, "finance.hakedis", existing.id if existing else 0, current_user.id,
        "update" if existing else "create",
        {"customer_code": customer_code, **data.model_dump()},
    )
    if approval_resp:
        return approval_resp

    try:
        term = receivable_service.upsert_term(db, customer_code, data.term_days, data.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        db, current_user.id, "update" if existing else "create", "receivable_term",
        term.id,
        json.dumps({"customer_code": customer_code, "term_days": data.term_days,
                    "notes": data.notes}, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    db.refresh(term)
    return {"id": term.id, "customer_code": term.customer_code,
            "term_days": term.term_days, "notes": term.notes}
