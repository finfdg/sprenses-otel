"""Acente Mahsup & Nakit Akım — salt-okuma projeksiyon endpoint'i.

Rezervasyon cirosu (EUR) + acente konfig (vade/kickback) + gerçek avanslar +
yıl sonu ciro hedefi senaryosu → 5 sekmelik projeksiyon. Yönetim Paneli deseni:
GET-only, 60sn TTL cache, mutasyon YOK → onaydan muaf (salt-okuma).

Vade/kickback konfigü `agency_groups` üzerindedir; düzenleme mevcut
`PATCH /sales/agency-groups/{id}` (sales.acente_mahsup use) ile yapılır.
"""
import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.services.agency_settlement_service import compute_agency_status, compute_settlement

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


@router.get("/agency-status")
def agency_status(
    granularity: str = Query("month", pattern="^(day|month|year)$"),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    group_id: Optional[int] = Query(None, ge=0),  # 0 = "Diğer" (grup dışı acenteler)
    agency: Optional[str] = Query(None, max_length=100),
    top_n: int = Query(7, ge=1, le=50),  # kök tabloda tek tek gösterilecek en büyük birim sayısı
    rank_by: str = Query("count", pattern="^(count|amount)$"),  # top-N sıralama ölçütü: adet | ciro
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.acente_mahsup", "view")),
):
    """Acente × Durum (gelen/içeride/çıkış) × dönem kırılımı — EUR tutar + adet.

    - granularity: day | month | year (varsayılan month)
    - year: month/day için dönem yılı (varsayılan içinde bulunulan yıl); year modunda yok sayılır
    - month: yalnız day modunda gerekli (varsayılan içinde bulunulan ay)
    - group_id: acente grubu filtresi (grup üyelerine daralt; tabloyu bireysel gösterir)
    - agency: tek ham acente adı filtresi (grup dışı da olabilir)

    Filtre yoksa tüm acenteler grup bazında; group_id/agency verilirse daraltılır.
    Rezervasyonlar duruma göre doğal tarihine yazılır (gelen/içeride → giriş,
    çıkış → çıkış). Salt-okuma, 60sn TTL cache.
    """
    y = year or date.today().year
    m = month or date.today().month
    key = ("agency_status", granularity, y, m if granularity == "day" else None,
           group_id, agency, top_n, rank_by)
    return _cached(key, lambda: compute_agency_status(db, granularity, y, m, group_id, agency,
                                                      top_n, rank_by))
