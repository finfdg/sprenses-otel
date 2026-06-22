"""Yönetim Paneli — GM/Finans için üst düzey KPI + uyarı aggregasyonu.

Mevcut modüllerin verisini birleştirir (yeni hesap mantığı YOK, servisleri çağırır):
operasyonel maliyet (stok×doluluk füzyonu), oda geliri, tedarikçi borcu, acente avansı,
sabit/değişken sınıflama, uyarılar (fiyat sapması, kritik stok). Banka/nakit/90-gün projeksiyon
ve vadesi gelen çek/kredi gibi ağır KPI'ları frontend mevcut endpoint'lerden çeker.
"""
import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.sales_invoice import SalesCollection, SalesInvoice
from app.models.scheduled import ScheduledEntry
from app.models.user import User
from app.models.vendor import Vendor
from app.routers.finance.sales_invoices import _merged_advances
from app.services.stock_service import compute_operational_kpi, compute_price_variance
from app.models.stock import StockProduct
from app.models.stock import StockMovement
from app.utils.occupancy import occupancy_metrics
from app.utils.vendor_fifo import _get_vendor_net_debts

router = APIRouter()

# Dashboard ağır agregasyon zinciridir (occupancy + operasyonel KPI + FIFO avans + tedarikçi
# borcu). Veri yalnız Sedna/dosya içe aktarmada değişir → 60sn TTL cache (mizan deseni).
_CACHE_TTL = 60
_cache: dict = {}  # key → (expiry_ts, value)


def _cached(key, producer):
    """Basit süreç-içi TTL cache — yönetim paneli KPI'sı 60sn boyunca yeniden hesaplanmaz."""
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    val = producer()
    _cache[key] = (now + _CACHE_TTL, val)
    if len(_cache) > 16:  # sınırsız büyümeyi önle
        for k in [k for k, (exp, _v) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
    return val


def _scheduled_total(db: Session, source_types: list, year: int) -> float:
    """Planlı gider (ScheduledEntry) yıl toplamı, source_type'lara göre."""
    return float(
        db.query(func.coalesce(func.sum(ScheduledEntry.amount), 0))
        .filter(ScheduledEntry.source_type.in_(source_types), ScheduledEntry.period_year == year)
        .scalar() or 0
    )


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("yonetim.panel", "view")),
):
    """Üst düzey KPI: doluluk + operasyonel maliyet + oda geliri + tedarikçi borcu + avans + GOP."""
    return _cached("dashboard", lambda: _compute_dashboard(db))


def _compute_dashboard(db: Session) -> dict:
    occ = occupancy_metrics(db)
    op = compute_operational_kpi(db)
    op_kpi = op.get("kpi", {})
    op_cons = op.get("consumption", {})

    room_invoiced = float(db.query(func.coalesce(func.sum(SalesInvoice.amount), 0)).scalar() or 0)
    room_collected = float(db.query(func.coalesce(func.sum(SalesCollection.amount), 0)).scalar() or 0)

    supplier_debt = round(sum(_get_vendor_net_debts(db).values()), 2)
    _, adv_by_cur = _merged_advances(db)

    consumption = float(op_cons.get("total", 0) or 0)
    gop_approx = round(room_invoiced - consumption, 2)  # kaba: oda geliri − operasyonel tüketim

    return {
        "occupancy": {
            "occupancy_pct": occ["occupancy_pct"], "adr_eur": occ["adr_eur"],
            "revpar_eur": occ["revpar_eur"], "guest_nights": occ["guest_nights"],
            "room_nights": occ["room_nights"], "revenue_eur": occ["revenue_eur"],
        },
        "cost": {
            "cost_per_guest_night_try": op_kpi.get("cost_per_guest_night_try", 0),
            "cost_per_guest_night_eur": op_kpi.get("cost_per_guest_night_eur"),
            "cpor_try": op_kpi.get("cpor_try", 0),
            "inventory_turnover": op_kpi.get("inventory_turnover", 0),
            "waste_pct": op_kpi.get("waste_pct", 0),
            "consumption_total_try": consumption,
            "fb_try": op_cons.get("fb", 0), "rooms_try": op_cons.get("rooms", 0),
            "staff_try": op_cons.get("staff", 0),
            "matched_periods": op_kpi.get("matched_periods", []),
        },
        "revenue": {"room_invoiced_try": round(room_invoiced, 2), "room_collected_try": round(room_collected, 2)},
        "finance": {"supplier_debt_try": supplier_debt, "agency_advance_by_currency": adv_by_cur},
        "gop_approx_try": gop_approx,
        # All-inclusive'de F&B geliri pakete gömülü (ayrı F&B geliri yok) → klasik Food Cost %
        # uygulanmaz; doğru metrik kişi başı F&B maliyeti (cost). Alan geri uyum için None bırakıldı.
        "food_cost_pct": None,
    }


@router.get("/cost-classification")
def cost_classification(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("yonetim.panel", "view")),
):
    """Sabit / değişken / yarı-değişken maliyet göstergesi (başabaş için) — yıllık TRY."""
    year = date.today().year
    variable = float(
        db.query(func.coalesce(func.sum(StockMovement.net_amount), 0))
        .filter(StockMovement.direction == "consume").scalar() or 0
    )
    semi = _scheduled_total(db, ["recurring", "salary", "sgk", "withholding"], year)
    fixed = _scheduled_total(db, ["rent_expense", "tax"], year)
    total = variable + semi + fixed
    return {
        "year": year,
        "items": [
            {"key": "variable", "label": "Değişken (stok tüketim)", "total": round(variable, 2)},
            {"key": "semi", "label": "Yarı-değişken (enerji + maaş + SGK + stopaj)", "total": round(semi, 2)},
            {"key": "fixed", "label": "Sabit (kira + vergi)", "total": round(fixed, 2)},
        ],
        "total": round(total, 2),
        "note": "Gösterge — kredi taksitleri ve çekirdek personel ayrıştırması ileride detaylanır.",
    }


@router.get("/alerts")
def alerts(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("yonetim.panel", "view")),
):
    """Yönetim uyarıları: fiyat sapması, tedarikçi borcu (en yüksek), kritik stok."""
    variance = [v for v in compute_price_variance(db, 8) if abs(v["variance_pct"]) >= 25]

    # Tedarikçi borcu — en yüksek 6
    debts = _get_vendor_net_debts(db)
    top_ids = sorted(debts, key=lambda k: -debts[k])[:6]
    names = {v.id: v.hesap_adi for v in db.query(Vendor).filter(Vendor.id.in_(top_ids)).all()} if top_ids else {}
    supplier_top = [{"vendor": names.get(i, str(i)), "debt_try": round(debts[i], 2)} for i in top_ids]

    # Kritik stok: yakın zamanda tüketilmiş ama anlık stok ≈ 0 (yeniden sipariş adayı)
    consumed_ids = {
        r[0] for r in db.query(StockMovement.product_sedna_id)
        .filter(StockMovement.direction == "consume", StockMovement.product_sedna_id.isnot(None))
        .distinct().all()
    }
    critical = (
        db.query(StockProduct.name, StockProduct.last_cost)
        .filter(StockProduct.current_stock <= 0, StockProduct.sedna_id.in_(consumed_ids))
        .order_by(StockProduct.last_cost.desc()).limit(10).all()
        if consumed_ids else []
    )
    critical_stock = [{"name": n, "last_cost": float(c or 0)} for n, c in critical]

    return {
        "price_variance": variance,
        "supplier_debt_top": supplier_top,
        "supplier_debt_total_try": round(sum(debts.values()), 2),
        "critical_stock": critical_stock,
        "critical_stock_count": len(critical_stock),
    }
