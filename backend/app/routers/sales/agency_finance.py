"""Acente Finansal Takip — ay × acente salt-okuma raporu."""
from datetime import datetime
from typing import Optional

import pytz
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.services.agency_finance_service import compute_agency_finance

router = APIRouter()
_TZ_ISTANBUL = pytz.timezone("Europe/Istanbul")


@router.get("/")
def agency_finance_report(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.acente_mahsup", "view")),
):
    """Avans, tahsilat, rezervasyon ve hak edişleri acente/ay bazında döndürür (EUR)."""
    selected_year = year or datetime.now(_TZ_ISTANBUL).year
    return compute_agency_finance(db, selected_year)
