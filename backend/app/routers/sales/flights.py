"""Uçuş arama endpoint'leri — Travelpayouts (Aviasales) API üzerinden.

Travelpayouts affiliate programı: ücretsiz API + tıklama başına komisyon.
Autocomplete public (token gerektirmez), search için TRAVELPAYOUTS_TOKEN gerekli.
Token yoksa mock veri döner — UI test için.

Eski Amadeus client (utils/travelpayouts_client.py) referans olarak duruyor;
17.07.2026'da kapanan Self-Service portali nedeniyle bu projede kullanılmıyor.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.middleware.auth import require_permission
from app.middleware.rate_limit import heavy_limiter
from app.models.user import User
from app.utils.travelpayouts_client import travelpayouts

logger = logging.getLogger(__name__)

router = APIRouter()


class FlightSearchRequest(BaseModel):
    origin: str = Field(..., min_length=3, max_length=3, description="Kalkış havalimanı IATA kodu (örn. IST)")
    destination: str = Field(..., min_length=3, max_length=3, description="Varış havalimanı IATA kodu")
    departure_date: str = Field(..., description="Gidiş tarihi YYYY-MM-DD")
    return_date: Optional[str] = Field(None, description="Dönüş tarihi YYYY-MM-DD (opsiyonel)")
    adults: int = Field(1, ge=1, le=9)
    children: int = Field(0, ge=0, le=9)
    infants: int = Field(0, ge=0, le=9)
    travel_class: Optional[str] = Field(None, description="ECONOMY / PREMIUM_ECONOMY / BUSINESS / FIRST")
    currency: str = Field("TRY", min_length=3, max_length=3)


@router.get("/airports")
def search_airports(
    keyword: str = Query(..., min_length=2, description="Şehir/havalimanı adı veya IATA kodu"),
    current_user: User = Depends(require_permission("sales.flight", "view")),
):
    """Havalimanı autocomplete — Travelpayouts public endpoint (token gerekmez)."""
    heavy_limiter.check(f"airport-search-{current_user.id}")
    try:
        return {"data": travelpayouts.search_airports(keyword)}
    except Exception as e:
        logger.error("Airport search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Havalimanı araması yapılamadı")


@router.post("/search")
def search_flights(
    payload: FlightSearchRequest,
    current_user: User = Depends(require_permission("sales.flight", "view")),
):
    """Uçuş arama — gidiş veya gidiş+dönüş, yolcu sayısı, sınıf seçilebilir."""
    heavy_limiter.check(f"flight-search-{current_user.id}")
    try:
        result = travelpayouts.search_flights(
            origin=payload.origin.upper(),
            destination=payload.destination.upper(),
            departure_date=payload.departure_date,
            return_date=payload.return_date,
            adults=payload.adults,
            children=payload.children,
            infants=payload.infants,
            travel_class=payload.travel_class,
            currency=payload.currency,
        )
        # Frontend'in tek bir yerden mock/gerçek farkını anlayabilmesi için flag
        meta = result.setdefault("meta", {})
        meta["mock"] = not travelpayouts.has_credentials
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Flight search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Uçuş araması yapılamadı — Travelpayouts API hatası")
