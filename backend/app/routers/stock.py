"""Stok / Depo Maliyet modülü — Sedna içe aktarma + maliyet analizi API'si.

Veri Sedna muhasebeden çekilir (Store/Product/StockOwner/StockTrans). Maliyet odaklı:
departman tüketimi, aylık alım/tüketim trendi, tedarikçi bazında alım, anlık stok değeri.
İçe aktarma merkezi "Sedna" butonuna bağlıdır (sedna_sync.py:_STEPS).
"""
import json
import math
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.stock import StockDepot, StockMovement, StockProduct, type_direction, type_label
from app.models.user import User
from app.utils.audit import log_action
from app.utils.sedna_client import (
    SednaUnavailable,
    fetch_stock_depots,
    fetch_stock_movements,
    fetch_stock_products,
    sedna_configured,
)

router = APIRouter()


# ─── İçe aktarma servisi (merkezi Sedna sync + tekil endpoint) ──────────────

def run_stock_import(db: Session, current_user: User, ip: Optional[str] = None) -> dict:
    """Sedna'dan depo/ürün/hareket çekip upsert eder (hareketler sedna_line_id ile dedup).

    Commit eder, audit'ler. HTTP'siz — orchestrator + tekil endpoint çağırır.
    """
    depots = fetch_stock_depots()
    products = fetch_stock_products()
    movements = fetch_stock_movements()

    # Depolar — code ile upsert
    existing_d = {d.code: d for d in db.query(StockDepot).all()}
    d_new = 0
    for r in depots:
        code = (r["code"] or "").strip()
        if not code:
            continue
        d = existing_d.get(code)
        if d:
            d.name = r["name"]
            d.no_consumption = bool(r["no_consumption"])
            d.is_expense = bool(r["is_expense"])
        else:
            db.add(StockDepot(code=code, name=r["name"],
                              no_consumption=bool(r["no_consumption"]), is_expense=bool(r["is_expense"])))
            d_new += 1
    db.flush()

    # Ürünler — sedna_id ile upsert + anlık değer
    existing_p = {p.sedna_id: p for p in db.query(StockProduct).all()}
    p_new = 0
    for r in products:
        sid = r["sedna_id"]
        cs = float(r["current_stock"] or 0)
        lc = float(r["last_cost"] or 0)
        cv = round(cs * lc, 2)
        p = existing_p.get(sid)
        if p:
            p.code = r["code"]
            p.name = r["name"]
            p.currency = r["currency"]
            p.stock_type = r["stock_type"]
            p.current_stock = cs
            p.last_cost = lc
            p.current_value = cv
        else:
            db.add(StockProduct(sedna_id=sid, code=r["code"], name=r["name"], currency=r["currency"],
                                stock_type=r["stock_type"], current_stock=cs, last_cost=lc, current_value=cv))
            p_new += 1
    db.flush()

    # Hareketler — sedna_line_id ile dedup, yalnız yenileri ekle (hareketler değişmez)
    existing_m = {row[0] for row in db.query(StockMovement.sedna_line_id).all()}
    batch = []
    for r in movements:
        lid = r["line_id"]
        if lid in existing_m:
            continue
        existing_m.add(lid)
        dt = r["date"]
        d_only = dt.date() if isinstance(dt, datetime) else dt
        tc = r["type_code"]
        batch.append({
            "sedna_line_id": lid, "sedna_owner_id": r["owner_id"], "date": d_only,
            "period": d_only.strftime("%Y-%m") if d_only else None,
            "type_code": tc, "type_label": type_label(tc), "direction": type_direction(tc),
            "product_sedna_id": r["product_id"], "product_code": r["product_code"], "product_name": r["product_name"],
            "entry_depot": (r["entry_depot"] or "").strip() or None,
            "exit_depot": (r["exit_depot"] or "").strip() or None,
            "cons_depot": (r["cons_depot"] or "").strip() or None,
            "quantity": float(r["quantity"] or 0), "unit_cost": float(r["unit_cost"] or 0),
            "net_amount": float(r["net_amount"] or 0),
            "supplier_code": r["supplier_code"], "supplier_name": r["supplier_name"], "doc_no": r["doc_no"],
        })
    if batch:
        db.bulk_insert_mappings(StockMovement, batch)

    result = {
        "depots": len(depots), "depots_new": d_new,
        "products": len(products), "products_new": p_new,
        "movements_new": len(batch), "movements_total": len(movements),
    }
    log_action(db, current_user.id, "create", "stock", None,
               json.dumps(result, ensure_ascii=False), ip)
    db.commit()
    return result


# ─── Durum + içe aktarma endpoint'i ─────────────────────────────────────────

@router.get("/sedna-status")
def stock_sedna_status(_: User = Depends(get_current_user)):
    return {"configured": sedna_configured()}


@router.post("/sedna-import")
def stock_sedna_import(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("stok.maliyet", "use")),
):
    """Sedna'dan stok verisini içe aktar (tekil; merkezi sync de çağırır)."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        return run_stock_import(db, current_user, get_client_ip(request))
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


# ─── Maliyet analizi ────────────────────────────────────────────────────────

@router.get("/summary")
def stock_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
):
    """Özet kartlar: anlık stok değeri, ürün sayısı, toplam alım/tüketim, son ay."""
    stock_value = db.query(func.coalesce(func.sum(StockProduct.current_value), 0)).scalar() or 0
    product_count = db.query(func.count(StockProduct.id)).scalar() or 0
    in_stock = db.query(func.count(StockProduct.id)).filter(StockProduct.current_stock > 0).scalar() or 0
    depot_count = db.query(func.count(StockDepot.id)).scalar() or 0

    def _sum(direction):
        return float(db.query(func.coalesce(func.sum(StockMovement.net_amount), 0))
                     .filter(StockMovement.direction == direction).scalar() or 0)

    purchases_total = _sum("in")
    consumption_total = _sum("consume")

    last_period = db.query(func.max(StockMovement.period)).scalar()
    lp_purchases = lp_consumption = 0.0
    if last_period:
        lp_purchases = float(db.query(func.coalesce(func.sum(StockMovement.net_amount), 0))
                             .filter(StockMovement.direction == "in", StockMovement.period == last_period).scalar() or 0)
        lp_consumption = float(db.query(func.coalesce(func.sum(StockMovement.net_amount), 0))
                               .filter(StockMovement.direction == "consume", StockMovement.period == last_period).scalar() or 0)

    return {
        "stock_value": float(stock_value), "product_count": product_count, "in_stock_count": in_stock,
        "depot_count": depot_count, "purchases_total": purchases_total, "consumption_total": consumption_total,
        "last_period": last_period, "last_period_purchases": lp_purchases, "last_period_consumption": lp_consumption,
    }


@router.get("/cost-by-department")
def cost_by_department(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
    period: Optional[str] = Query(None),
):
    """Departman (ConsumptionDepot) bazında tüketim maliyeti — depo adlarıyla."""
    q = (
        db.query(
            StockMovement.cons_depot.label("code"),
            func.max(StockDepot.name).label("name"),
            func.sum(StockMovement.net_amount).label("total"),
            func.count(StockMovement.id).label("n"),
        )
        .outerjoin(StockDepot, StockMovement.cons_depot == StockDepot.code)
        .filter(StockMovement.direction == "consume", StockMovement.cons_depot.isnot(None))
    )
    if period:
        q = q.filter(StockMovement.period == period)
    rows = q.group_by(StockMovement.cons_depot).order_by(desc("total")).all()
    return {"items": [{"code": r.code, "name": r.name or r.code,
                       "total": float(r.total or 0), "count": r.n} for r in rows]}


@router.get("/monthly-trend")
def monthly_trend(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
):
    """Aylık alım vs tüketim trendi (sezon analizi)."""
    rows = db.query(
        StockMovement.period,
        func.sum(StockMovement.net_amount).filter(StockMovement.direction == "in").label("purchases"),
        func.sum(StockMovement.net_amount).filter(StockMovement.direction == "consume").label("consumption"),
    ).filter(StockMovement.period.isnot(None)).group_by(StockMovement.period).order_by(StockMovement.period).all()
    return {"items": [{"period": r.period, "purchases": float(r.purchases or 0),
                       "consumption": float(r.consumption or 0)} for r in rows]}


@router.get("/by-supplier")
def by_supplier(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
    limit: int = Query(15, ge=1, le=100),
):
    """Tedarikçi bazında alım maliyeti (en çok alınan)."""
    rows = (
        db.query(
            StockMovement.supplier_code.label("code"),
            func.max(StockMovement.supplier_name).label("name"),
            func.sum(StockMovement.net_amount).label("total"),
            func.count(StockMovement.id).label("n"),
        )
        .filter(StockMovement.direction == "in", StockMovement.supplier_code.isnot(None))
        .group_by(StockMovement.supplier_code).order_by(desc("total")).limit(limit).all()
    )
    return {"items": [{"code": r.code, "name": r.name or r.code,
                       "total": float(r.total or 0), "count": r.n} for r in rows]}


# ─── Ürünler + Hareketler + Depolar (liste) ─────────────────────────────────

@router.get("/products")
def list_products(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.urunler", "view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    in_stock: bool = Query(False),
):
    q = db.query(StockProduct)
    if search:
        s = f"%{search.strip()}%"
        q = q.filter(or_(StockProduct.name.ilike(s), StockProduct.code.ilike(s)))
    if in_stock:
        q = q.filter(StockProduct.current_stock > 0)
    total = q.count()
    items = (q.order_by(desc(StockProduct.current_value), StockProduct.name)
             .offset((page - 1) * page_size).limit(page_size).all())
    return {
        "items": [{
            "id": p.id, "code": p.code, "name": p.name, "currency": p.currency or "TRY",
            "current_stock": float(p.current_stock or 0), "last_cost": float(p.last_cost or 0),
            "current_value": float(p.current_value or 0),
        } for p in items],
        "total": total, "page": page, "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 1,
    }


@router.get("/movements")
def list_movements(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.hareketler", "view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    direction: Optional[str] = Query(None),
    depot: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    q = db.query(StockMovement)
    if direction:
        q = q.filter(StockMovement.direction == direction)
    if depot:
        q = q.filter(or_(StockMovement.cons_depot == depot, StockMovement.entry_depot == depot,
                         StockMovement.exit_depot == depot))
    if search:
        s = f"%{search.strip()}%"
        q = q.filter(or_(StockMovement.product_name.ilike(s), StockMovement.supplier_name.ilike(s),
                         StockMovement.doc_no.ilike(s)))
    if start_date:
        q = q.filter(StockMovement.date >= start_date)
    if end_date:
        q = q.filter(StockMovement.date <= end_date)
    total = q.count()
    items = (q.order_by(desc(StockMovement.date), desc(StockMovement.id))
             .offset((page - 1) * page_size).limit(page_size).all())
    return {
        "items": [{
            "id": m.id, "date": m.date.isoformat() if m.date else None, "type_label": m.type_label,
            "direction": m.direction, "product_name": m.product_name, "quantity": float(m.quantity or 0),
            "unit_cost": float(m.unit_cost or 0), "net_amount": float(m.net_amount or 0),
            "cons_depot": m.cons_depot, "entry_depot": m.entry_depot, "exit_depot": m.exit_depot,
            "supplier_name": m.supplier_name, "doc_no": m.doc_no,
        } for m in items],
        "total": total, "page": page, "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 1,
    }


@router.get("/depots")
def list_depots(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.depolar", "view")),
):
    """Depo/departman listesi + toplam tüketim maliyeti."""
    cons = dict(
        db.query(StockMovement.cons_depot, func.sum(StockMovement.net_amount))
        .filter(StockMovement.direction == "consume", StockMovement.cons_depot.isnot(None))
        .group_by(StockMovement.cons_depot).all()
    )
    depots = db.query(StockDepot).order_by(StockDepot.code).all()
    return {"items": [{
        "id": d.id, "code": d.code, "name": d.name,
        "no_consumption": d.no_consumption, "is_expense": d.is_expense,
        "consumption_total": float(cons.get(d.code, 0) or 0),
    } for d in depots]}
