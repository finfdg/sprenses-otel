"""Kredi kartı ekstresi projeksiyon endpoint'i.

Yüklü ekstresi olmayan aylar için tahmini kredi kartı ekstre kalemleri döner (cari ay =
kart limiti, ileri aylar = 0). Salt-okuma — onaydan muaf GET. Frontend bunları nakit akım
ay akordiyonuna karıştırır. Detay + kural: `app/services/cc_projection_service.py`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.services.cc_projection_service import compute_cc_projections

router = APIRouter()


@router.get("/cash-flow/cc-projections")
def cc_projections(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Aktif kredi kartları için tahmini gelecek ekstre kalemleri."""
    return {"items": compute_cc_projections(db)}
