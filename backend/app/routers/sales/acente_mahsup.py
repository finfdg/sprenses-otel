"""Acente Mahsup & Nakit Akım — salt-okuma projeksiyon endpoint'i.

Rezervasyon cirosu (EUR) + acente konfig (vade/kickback) + gerçek avanslar +
yıl sonu ciro hedefi senaryosu → 5 sekmelik projeksiyon. Yönetim Paneli deseni:
GET-only, 60sn TTL cache, mutasyon YOK → onaydan muaf (salt-okuma).

Vade/kickback konfigü `agency_groups` üzerindedir; düzenleme mevcut
`PATCH /sales/agency-groups/{id}` (sales.hotel_reservation use) ile yapılır.
"""
import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.services.agency_settlement_service import compute_settlement

router = APIRouter()

# Projeksiyon rezervasyon + avans (compute_receivables) agregasyonu içerir;
# veri yalnız içe aktarmalarda değişir → 60sn TTL cache (yönetim paneli deseni).
_CACHE_TTL = 60
_cache: dict = {}  # key → (expiry_ts, value)


def _cached(key, producer):
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    val = producer()
    _cache[key] = (now + _CACHE_TTL, val)
    if len(_cache) > 32:  # senaryo-parametreli anahtarlarda sınırsız büyümeyi önle
        for k in [k for k, (exp, _v) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
    return val


@router.get("/")
def settlement(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    year_target: Optional[float] = Query(None, ge=0),
    opening_cash: float = Query(0.0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.acente_mahsup", "view")),
):
    """Acente Mahsup & Nakit Akım projeksiyonu (EUR).

    - year: projeksiyon yılı (varsayılan içinde bulunulan yıl)
    - year_target: yıl sonu ciro hedefi (EUR); boşsa gerçek ciro toplamı (forecast=0)
    - opening_cash: nakit akım açılış bakiyesi (EUR, avanslar dahil)
    """
    y = year or date.today().year
    key = ("settlement", y, year_target, opening_cash)
    return _cached(key, lambda: compute_settlement(db, y, year_target, opening_cash))
