"""Otel satış faturaları (120/Alıcılar) — Sedna kaynaklı, FIFO tahsil takibi.

Cariler'in (320) aynası: fatura = 120 Borç (DocumentType=1); tahsilat = 120 Alacak.
Tahsil durumu müşteri bazında tahsilatların faturalara FIFO düşülmesiyle hesaplanır.
Münferit (120.03.*) ve acente ayrı filtrelenir. Onaydan muaf (operasyonel import), audit'li.
"""
import hashlib
import logging
import math
from datetime import datetime
from typing import Optional

import pytz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.sales_invoice import (
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_PARTIAL,
    SalesCollection,
    SalesInvoice,
)
from app.models.user import User
from app.utils.audit import log_action
from app.utils.sedna_client import SednaUnavailable, fetch_sales_invoices, sedna_configured

logger = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Istanbul")
router = APIRouter(prefix="/sales-invoices")

_EPS = 0.01  # float kırıntı eşiği


# ─── Yardımcılar ────────────────────────────────────────


def _is_munferit(code: str, name: str) -> bool:
    """Münferit (bireysel/walk-in) mi — 120.03.* veya adında MÜNFERİT geçen."""
    c = code or ""
    n = (name or "").upper()
    return c.startswith("120.03") or "MÜNFERİT" in n or "MUNFERIT" in n


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _hash(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _status_map(db: Session) -> dict:
    """Her fatura için FIFO tahsil durumu hesapla → {invoice_id: (collected, status)}.

    Müşteri bazında: tahsilat havuzu faturalara en eskiden (FIFO) dağıtılır.
    """
    invoices = (
        db.query(SalesInvoice)
        .order_by(SalesInvoice.customer_code, SalesInvoice.invoice_date, SalesInvoice.id)
        .all()
    )
    # müşteri → toplam tahsilat
    pool: dict = {}
    for c_code, amt in db.query(SalesCollection.customer_code, SalesCollection.amount).all():
        pool[c_code] = pool.get(c_code, 0.0) + _f(amt)

    result: dict = {}
    for inv in invoices:
        avail = pool.get(inv.customer_code, 0.0)
        amount = _f(inv.amount)
        applied = min(amount, avail) if avail > 0 else 0.0
        pool[inv.customer_code] = avail - applied
        if applied >= amount - _EPS:
            status = STATUS_PAID
        elif applied > _EPS:
            status = STATUS_PARTIAL
        else:
            status = STATUS_OPEN
        result[inv.id] = (round(applied, 2), status)
    return result


# ─── İçe aktarma (servis fonksiyonu — merkezi Sedna sync kullanır) ───


def run_sales_invoice_import(db: Session, current_user: User, ip=None) -> dict:
    """Sedna'dan satış faturalarını + tahsilatları çek → upsert (tx_hash dedup).

    Servis fonksiyonu (HTTP'siz, broadcast'siz). Hata → HTTPException.
    """
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        data = fetch_sales_invoices()
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Sedna satış faturası sorgu hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Sedna satış faturası verisi alınamadı.")

    inv_rows = data.get("invoices", [])
    col_rows = data.get("collections", [])

    inv_new = inv_skip = col_new = col_skip = 0
    try:
        existing_inv = {h for (h,) in db.query(SalesInvoice.tx_hash).all()}
        for r in inv_rows:
            code = (r.get("customer_code") or "").strip()
            d = r.get("invoice_date")
            if not code or not d:
                continue
            no = (r.get("invoice_no") or "").strip() or None
            amt = _f(r.get("amount"))
            h = _hash("sinv", code, d, no, amt)
            if h in existing_inv:
                inv_skip += 1
                continue
            name = (r.get("customer_name") or "").strip()
            db.add(SalesInvoice(
                customer_code=code, customer_name=name, is_munferit=_is_munferit(code, name),
                invoice_no=no, invoice_date=d, amount=amt, currency="TL",
                description=(r.get("aciklama") or None), tx_hash=h,
            ))
            existing_inv.add(h)
            inv_new += 1

        existing_col = {h for (h,) in db.query(SalesCollection.tx_hash).all()}
        for r in col_rows:
            code = (r.get("customer_code") or "").strip()
            d = r.get("collection_date")
            if not code or not d:
                continue
            amt = _f(r.get("amount"))
            fis = r.get("fis_no")
            h = _hash("scol", code, d, amt, fis)
            if h in existing_col:
                col_skip += 1
                continue
            db.add(SalesCollection(
                customer_code=code, collection_date=d, amount=amt,
                description=(r.get("aciklama") or None), tx_hash=h,
            ))
            existing_col.add(h)
            col_new += 1

        log_action(
            db, current_user.id, "create", "sales_invoice", entity_id=None,
            details=f"Sedna satış faturası: {inv_new} yeni fatura, {col_new} yeni tahsilat",
            ip_address=ip,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Satış faturası içe aktarma DB hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Satış faturası içe aktarma sırasında veritabanı hatası.")

    return {
        "invoices_total": len(inv_rows), "invoices_new": inv_new, "invoices_skipped": inv_skip,
        "collections_total": len(col_rows), "collections_new": col_new, "collections_skipped": col_skip,
    }


# ─── Endpoint'ler ───────────────────────────────────────


@router.get("/")
def list_invoices(
    customer_type: Optional[str] = Query(None, description="munferit | agency"),
    status: Optional[str] = Query(None, description="paid | partial | open"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.sales_invoices", "view")),
):
    """Satış faturaları listesi (FIFO tahsil durumu + filtre + sayfalama)."""
    smap = _status_map(db)
    q = db.query(SalesInvoice)
    if customer_type == "munferit":
        q = q.filter(SalesInvoice.is_munferit.is_(True))
    elif customer_type == "agency":
        q = q.filter(SalesInvoice.is_munferit.is_(False))
    if start_date:
        q = q.filter(SalesInvoice.invoice_date >= start_date)
    if end_date:
        q = q.filter(SalesInvoice.invoice_date <= end_date)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            SalesInvoice.invoice_no.ilike(term)
            | SalesInvoice.customer_name.ilike(term)
            | SalesInvoice.customer_code.ilike(term)
        )
    rows = q.order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.id.desc()).all()

    items = []
    for inv in rows:
        collected, st = smap.get(inv.id, (0.0, STATUS_OPEN))
        if status and st != status:
            continue
        amt = _f(inv.amount)
        items.append({
            "id": inv.id, "customer_code": inv.customer_code, "customer_name": inv.customer_name,
            "is_munferit": inv.is_munferit, "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "amount": amt, "currency": inv.currency,
            "collected": collected, "remaining": round(amt - collected, 2), "status": st,
            "description": inv.description,
        })

    total = len(items)
    pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "total": total, "page": page, "page_size": page_size, "pages": pages,
    }


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.sales_invoices", "view")),
):
    """Satış faturası özeti: toplam faturalanan/tahsil/açık + durum + münferit/acente kırılımı."""
    smap = _status_map(db)
    invoices = db.query(SalesInvoice).all()
    agg = {
        "total": {"invoiced": 0.0, "collected": 0.0, "count": 0},
        "munferit": {"invoiced": 0.0, "collected": 0.0, "count": 0},
        "agency": {"invoiced": 0.0, "collected": 0.0, "count": 0},
    }
    status_counts = {STATUS_PAID: 0, STATUS_PARTIAL: 0, STATUS_OPEN: 0}
    for inv in invoices:
        collected, st = smap.get(inv.id, (0.0, STATUS_OPEN))
        amt = _f(inv.amount)
        bucket = "munferit" if inv.is_munferit else "agency"
        for key in ("total", bucket):
            agg[key]["invoiced"] += amt
            agg[key]["collected"] += collected
            agg[key]["count"] += 1
        status_counts[st] += 1
    for key in agg:
        agg[key]["invoiced"] = round(agg[key]["invoiced"], 2)
        agg[key]["collected"] = round(agg[key]["collected"], 2)
        agg[key]["outstanding"] = round(agg[key]["invoiced"] - agg[key]["collected"], 2)
    return {**agg, "status_counts": status_counts}


@router.post("/sedna-import")
def sedna_import_sales(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.sales_invoices", "use")),
):
    """Sedna satış faturası içe aktarma (tekil endpoint)."""
    return run_sales_invoice_import(db, current_user, get_client_ip(request))
