"""Döviz kuru API endpoint'leri."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.exchange_rate import ExchangeRate
from app.models.user import User
from app.schemas.exchange_rate import ExchangeRateResponse
from app.utils.pagination import page_meta

router = APIRouter(prefix="/exchange-rates")


def _build_response(er: ExchangeRate) -> dict:
    """ExchangeRate kaydından yanıt oluştur."""
    return ExchangeRateResponse(
        id=er.id,
        date=er.date,
        currency_code=er.currency_code,
        currency_name=er.currency_name,
        unit=er.unit,
        forex_buying=float(er.forex_buying) if er.forex_buying is not None else None,
        forex_selling=float(er.forex_selling) if er.forex_selling is not None else None,
        banknote_buying=float(er.banknote_buying) if er.banknote_buying is not None else None,
        banknote_selling=float(er.banknote_selling) if er.banknote_selling is not None else None,
        source=er.source,
    ).model_dump()


def _calculate_parity(eur_selling: Optional[float], usd_selling: Optional[float]) -> Optional[float]:
    """EUR/USD paritesini hesapla."""
    if eur_selling and usd_selling and usd_selling > 0:
        return round(eur_selling / usd_selling, 4)
    return None


@router.get("/latest")
def get_latest_rates(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.doviz", "view")),
):
    """En son kurları getir (bugün veya en yakın tarih)."""

    latest_date = db.query(func.max(ExchangeRate.date)).scalar()
    if not latest_date:
        return {"date": None, "rates": [], "eur_usd_parity": None}

    rates = db.query(ExchangeRate).filter(
        ExchangeRate.date == latest_date,
    ).order_by(ExchangeRate.currency_code).all()

    eur_rate = next((r for r in rates if r.currency_code == "EUR"), None)
    usd_rate = next((r for r in rates if r.currency_code == "USD"), None)

    parity = _calculate_parity(
        float(eur_rate.forex_selling) if eur_rate and eur_rate.forex_selling else None,
        float(usd_rate.forex_selling) if usd_rate and usd_rate.forex_selling else None,
    )

    return {
        "date": latest_date,
        "rates": [_build_response(r) for r in rates],
        "eur_usd_parity": parity,
    }


@router.get("/history")
def get_rate_history(
    currency_code: str = Query(..., pattern="^(USD|EUR|GBP)$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.doviz", "view")),
):
    """Belirli döviz için tarihçe (paginated, en yeniden eskiye)."""
    query = db.query(ExchangeRate).filter(
        ExchangeRate.currency_code == currency_code,
    )

    if start_date:
        query = query.filter(ExchangeRate.date >= start_date)
    if end_date:
        query = query.filter(ExchangeRate.date <= end_date)

    total = query.count()
    items = (
        query.order_by(desc(ExchangeRate.date))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return page_meta([_build_response(er) for er in items], total, page, page_size)


@router.get("/chart")
def get_chart_data(
    currency_code: str = Query(..., pattern="^(USD|EUR|GBP)$"),
    days: int = Query(90, ge=7, le=1095),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.doviz", "view")),
):
    """Grafik için tarihçe verisi (sadece tarih + alış/satış)."""
    since = date.today() - timedelta(days=days)

    rows = (
        db.query(ExchangeRate.date, ExchangeRate.forex_buying, ExchangeRate.forex_selling)
        .filter(
            ExchangeRate.currency_code == currency_code,
            ExchangeRate.date >= since,
        )
        .order_by(ExchangeRate.date)
        .all()
    )

    return [
        {
            "date": r.date,
            "forex_buying": float(r.forex_buying) if r.forex_buying is not None else None,
            "forex_selling": float(r.forex_selling) if r.forex_selling is not None else None,
        }
        for r in rows
    ]


@router.get("/parity/history")
def get_parity_history(
    days: int = Query(90, ge=7, le=1095),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.doviz", "view")),
):
    """EUR/USD parite tarihçesi (grafik için)."""
    since = date.today() - timedelta(days=days)

    eur = aliased(ExchangeRate)
    usd = aliased(ExchangeRate)

    rows = (
        db.query(
            eur.date,
            eur.forex_selling.label("eur_selling"),
            usd.forex_selling.label("usd_selling"),
        )
        .join(usd, (eur.date == usd.date))
        .filter(
            eur.currency_code == "EUR",
            usd.currency_code == "USD",
            eur.date >= since,
        )
        .order_by(eur.date)
        .all()
    )

    return [
        {
            "date": r.date,
            "parity": round(float(r.eur_selling) / float(r.usd_selling), 4)
            if r.eur_selling and r.usd_selling and float(r.usd_selling) > 0
            else None,
        }
        for r in rows
    ]
