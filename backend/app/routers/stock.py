"""Stok / Depo Maliyet modülü — Sedna içe aktarma + maliyet analizi API'si.

Veri Sedna muhasebeden çekilir (Store/Product/StockOwner/StockTrans). Maliyet odaklı:
departman tüketimi, aylık alım/tüketim trendi, tedarikçi bazında alım, anlık stok değeri.
İçe aktarma merkezi "Sedna" butonuna bağlıdır (sedna_sync.py:_STEPS).
"""
import logging
import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.stock import (
    COST_GROUP_LABELS,
    StockDepot,
    StockMovement,
    StockProduct,
    type_label,
)
from app.models.user import User
from app.utils.sedna_client import SednaUnavailable, sedna_configured

from app.services.stock_service import (
    compute_operational_kpi,
    compute_price_anomalies,
    compute_price_variance,
    get_product_purchases,
    run_stock_import,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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
            func.max(StockDepot.cost_group).label("cost_group"),
            func.sum(StockMovement.net_amount).label("total"),
            func.count(StockMovement.id).label("n"),
        )
        .outerjoin(StockDepot, StockMovement.cons_depot == StockDepot.code)
        .filter(StockMovement.direction == "consume", StockMovement.cons_depot.isnot(None))
    )
    if period:
        q = q.filter(StockMovement.period == period)
    rows = q.group_by(StockMovement.cons_depot).order_by(desc("total")).all()
    return {"items": [{"code": r.code, "name": r.name or r.code, "cost_group": r.cost_group,
                       "group_label": COST_GROUP_LABELS.get(r.cost_group, r.cost_group),
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


@router.get("/operational-kpi")
def operational_kpi(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
):
    """Operasyonel maliyet KPI'ları (doluluk füzyonu) — bk. compute_operational_kpi."""
    return compute_operational_kpi(db)


@router.get("/price-variance")
def price_variance(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
    limit: int = Query(100, ge=0, le=5000),
):
    """Fiyat sapması: gerçek hareketler (`items`) + olası birim/miktar anomalileri (`anomalies`).

    `limit=0` → cap yok (tüm hareketler). `items` fiyatı artanlar üstte / azalanlar altta sıralı.
    """
    lim = limit or None  # 0 → None (tümü)
    return {
        "items": compute_price_variance(db, lim),
        "anomalies": compute_price_anomalies(db, lim),
    }


@router.get("/product-purchases/{product_id}")
def product_purchases(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
    limit: int = Query(200, ge=1, le=500),
):
    """Bir ürünün alış hareketleri (tarih/fiyat/miktar/tedarikçi) — fiyat paneli detay tıklaması."""
    return get_product_purchases(db, product_id, limit)


@router.get("/product-purchases/{product_id}/pdf")
def product_purchases_pdf(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("stok.maliyet", "view")),
    limit: int = Query(500, ge=1, le=500),
):
    """Ürün alış hareketlerini PDF olarak döndürür (modal 'Yazdır' butonu)."""
    import io
    from datetime import date as date_cls
    from html import escape

    from fastapi.responses import Response
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.utils.pdf_fonts import register_turkish_fonts

    data = get_product_purchases(db, product_id, limit)
    base_font, bold_font = register_turkish_fonts()

    def _tl(v):
        s = f"{float(v or 0):,.2f}"  # 1,234.56 → TR: 1.234,56
        return "₺" + s.replace(",", "X").replace(".", ",").replace("X", ".")

    def _num(v):
        s = f"{float(v or 0):,.2f}".rstrip("0").rstrip(".")
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    def _eff(it):  # birim fiyat = net ÷ miktar (modal ile aynı)
        return (it["net_amount"] / it["quantity"]) if it.get("quantity") else (it.get("unit_cost") or 0)

    def _date_tr(s):
        return ".".join(reversed(s.split("-"))) if s else "—"

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4,
        topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=14 * mm, rightMargin=14 * mm,
    )
    title_style = ParagraphStyle("t", fontName=bold_font, fontSize=14, spaceAfter=4)
    sub_style = ParagraphStyle("s", fontName=base_font, fontSize=9, textColor=colors.grey, spaceAfter=10)
    cell_style = ParagraphStyle("cell", fontName=base_font, fontSize=8, leading=10)

    today = date_cls.today()
    elems = [
        Paragraph(escape(data.get("name") or "Ürün"), title_style),
        Paragraph(
            f"{data['count']} alış &nbsp;·&nbsp; medyan birim {_tl(data['median_cost'])} "
            f"&nbsp;·&nbsp; Birim fiyat = net ÷ miktar (gerçek ödenen) "
            f"&nbsp;·&nbsp; Rapor: {today.strftime('%d.%m.%Y')}",
            sub_style,
        ),
    ]

    rows = [["#", "Tarih", "Tedarikçi", "Miktar", "Birim Fiyat", "Net Tutar"]]
    for i, it in enumerate(data["items"], 1):
        rows.append([
            str(i),
            _date_tr(it["date"]),
            Paragraph(escape(it.get("supplier_name") or "—"), cell_style),
            _num(it["quantity"]),
            _tl(_eff(it)),
            _tl(it["net_amount"]),
        ])

    if len(rows) == 1:
        elems.append(Paragraph("Bu ürün için kayıtlı alış bulunamadı.", sub_style))
    else:
        # Portrait A4 kullanılabilir genişlik ≈ 182mm
        table = Table(rows, colWidths=[10 * mm, 26 * mm, 72 * mm, 24 * mm, 26 * mm, 24 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), base_font),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D9488")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (3, 0), (5, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#0D9488")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        elems.append(table)

    doc.build(elems)
    output.seek(0)
    # NOT: HTTP header'ları latin-1 olmalı → ürün adını (Türkçe karakterli, ör. "CİLA") header'a
    # KOYMA. Dosya adı ASCII tutulur; ürün adı zaten PDF gövdesinde başlık olarak var.
    return Response(
        content=output.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=alis-{product_id}.pdf"},
    )


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
