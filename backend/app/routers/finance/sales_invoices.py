"""Otel satış faturaları (120/Alıcılar) — Sedna kaynaklı, FIFO tahsil takibi.

Cariler'in (320) aynası: fatura = 120 Borç (DocumentType=1); tahsilat = 120 Alacak.
Tahsil durumu müşteri bazında tahsilatların faturalara FIFO düşülmesiyle hesaplanır.
Münferit (120.03.*) ve acente ayrı filtrelenir. Onaydan muaf (operasyonel import), audit'li.
"""
import hashlib
import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Optional

import pytz
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func
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


def _compute(db: Session):
    """Tarih-sıralı FIFO. Döner: (inv_map, advance_balance).

    inv_map[invoice_id] = {"collected", "advance", "status"}
      - advance = faturanın **kesildiği anda mevcut avansla** karşılanan kısmı (prepaid).
    advance_balance[customer_code] = kullanılmamış net avans (tüm faturalardan artan tahsilat).

    Müşteri bazında olaylar tarih sırasıyla işlenir. Aynı gün **önce fatura sonra tahsilat**
    (aynı-gün ödeme avans sayılmaz — münferit walk-in). Tahsilat geldiğinde en eski açık
    faturaya backfill (sonradan gelen = normal tahsilat); fatura kesildiğinde önce mevcut
    avans havuzundan karşılanır (prepaid).
    """
    inv_by: dict = defaultdict(list)
    col_by: dict = defaultdict(list)
    for inv in db.query(SalesInvoice).all():
        inv_by[inv.customer_code].append(inv)
    for col in db.query(SalesCollection).all():
        col_by[col.customer_code].append(col)

    inv_map: dict = {}
    advance_balance: dict = {}

    for code in set(inv_by) | set(col_by):
        events = [(inv.invoice_date, 0, "inv", inv) for inv in inv_by.get(code, [])]
        events += [(col.collection_date, 1, "col", col) for col in col_by.get(code, [])]
        events.sort(key=lambda e: (e[0], e[1]))

        pool = 0.0           # mevcut avans/kredi havuzu
        open_q: list = []    # açık faturalar FIFO: [(inv, remaining)]
        state: dict = {}     # inv.id -> [collected, advance_covered]
        for _d, _t, kind, obj in events:
            if kind == "col":
                pool += _f(obj.amount)
                i = 0
                while i < len(open_q) and pool > _EPS:
                    inv, rem = open_q[i]
                    apply = min(rem, pool)
                    pool -= apply
                    rem -= apply
                    state[inv.id][0] += apply
                    open_q[i] = (inv, rem)
                    if rem <= _EPS:
                        i += 1
                    else:
                        break
                open_q = open_q[i:]
            else:
                amount = _f(obj.amount)
                adv = min(pool, amount) if pool > _EPS else 0.0
                pool -= adv
                state[obj.id] = [adv, adv]
                if amount - adv > _EPS:
                    open_q.append((obj, amount - adv))

        for inv in inv_by.get(code, []):
            collected, adv = state.get(inv.id, [0.0, 0.0])
            amount = _f(inv.amount)
            if collected >= amount - _EPS:
                st = STATUS_PAID
            elif collected > _EPS:
                st = STATUS_PARTIAL
            else:
                st = STATUS_OPEN
            inv_map[inv.id] = {"collected": round(collected, 2), "advance": round(adv, 2), "status": st}
        if pool > _EPS:
            advance_balance[code] = round(pool, 2)
    return inv_map, advance_balance


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

        existing_col = {c.tx_hash: c for c in db.query(SalesCollection).all()}
        for r in col_rows:
            code = (r.get("customer_code") or "").strip()
            d = r.get("collection_date")
            if not code or not d:
                continue
            amt = _f(r.get("amount"))
            fis = r.get("fis_no")
            name = (r.get("customer_name") or "").strip() or None
            h = _hash("scol", code, d, amt, fis)
            ex = existing_col.get(h)
            if ex is not None:
                if name and not (ex.customer_name or "").strip():
                    ex.customer_name = name   # boş ismi Sedna'dan doldur
                col_skip += 1
                continue
            col = SalesCollection(
                customer_code=code, customer_name=name, collection_date=d, amount=amt,
                description=(r.get("aciklama") or None), tx_hash=h,
            )
            db.add(col)
            existing_col[h] = col
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
    smap, _ = _compute(db)
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
        entry = smap.get(inv.id, {"collected": 0.0, "advance": 0.0, "status": STATUS_OPEN})
        st = entry["status"]
        if status and st != status:
            continue
        amt = _f(inv.amount)
        items.append({
            "id": inv.id, "customer_code": inv.customer_code, "customer_name": inv.customer_name,
            "is_munferit": inv.is_munferit, "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "amount": amt, "currency": inv.currency,
            "collected": entry["collected"], "remaining": round(amt - entry["collected"], 2),
            "status": st, "advance_covered": entry["advance"], "by_advance": entry["advance"] > _EPS,
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
    """Satış faturası özeti: toplam faturalanan/tahsil/açık + durum + münferit/acente kırılımı + avans."""
    smap, adv_bal = _compute(db)
    invoices = db.query(SalesInvoice).all()
    agg = {
        "total": {"invoiced": 0.0, "collected": 0.0, "count": 0},
        "munferit": {"invoiced": 0.0, "collected": 0.0, "count": 0},
        "agency": {"invoiced": 0.0, "collected": 0.0, "count": 0},
    }
    status_counts = {STATUS_PAID: 0, STATUS_PARTIAL: 0, STATUS_OPEN: 0}
    for inv in invoices:
        entry = smap.get(inv.id, {"collected": 0.0, "status": STATUS_OPEN})
        amt = _f(inv.amount)
        bucket = "munferit" if inv.is_munferit else "agency"
        for key in ("total", bucket):
            agg[key]["invoiced"] += amt
            agg[key]["collected"] += entry["collected"]
            agg[key]["count"] += 1
        status_counts[entry["status"]] += 1
    for key in agg:
        agg[key]["invoiced"] = round(agg[key]["invoiced"], 2)
        agg[key]["collected"] = round(agg[key]["collected"], 2)
        agg[key]["outstanding"] = round(agg[key]["invoiced"] - agg[key]["collected"], 2)
    return {
        **agg,
        "status_counts": status_counts,
        "advance": {  # kullanılmamış net avans (acentelerin yatırıp henüz fatura ile kapatmadığı)
            "balance": round(sum(adv_bal.values()), 2),
            "agency_count": len(adv_bal),
        },
    }


@router.get("/advances")
def advance_balances(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.sales_invoices", "view")),
):
    """Net avans bakiyesi olan müşteriler (acente prepaid) — yatırılan / faturayla kapanan / kalan.

    Avans = müşterinin 120 hesabına yatırdığı, henüz fatura ile mahsup edilmemiş tutar
    (toplam tahsilat > toplam fatura). Faturalar kesildikçe avans kapanır.
    """
    _, adv_bal = _compute(db)
    if not adv_bal:
        return {"items": [], "total_balance": 0.0, "count": 0}

    # müşteri adı/tür + toplam fatura (faturalardan) ve tahsilat/ad (tahsilatlardan)
    info: dict = {}
    for code, name, ism, inv in (
        db.query(SalesInvoice.customer_code, func.max(SalesInvoice.customer_name),
                 func.bool_or(SalesInvoice.is_munferit), func.sum(SalesInvoice.amount))
        .group_by(SalesInvoice.customer_code).all()
    ):
        info[code] = {"name": name, "ism": bool(ism), "invoiced": _f(inv)}
    col_info: dict = {}
    for code, name, tot in (
        db.query(SalesCollection.customer_code, func.max(SalesCollection.customer_name),
                 func.sum(SalesCollection.amount))
        .group_by(SalesCollection.customer_code).all()
    ):
        col_info[code] = {"name": name, "amount": _f(tot)}

    items = []
    for code, net in sorted(adv_bal.items(), key=lambda x: -x[1]):
        inv_meta = info.get(code)
        col_meta = col_info.get(code, {})
        name = (inv_meta["name"] if inv_meta else None) or col_meta.get("name") or code
        ism = inv_meta["ism"] if inv_meta else code.startswith("120.03")
        invoiced = inv_meta["invoiced"] if inv_meta else 0.0
        collected = col_meta.get("amount", 0.0)
        items.append({
            "customer_code": code, "customer_name": name, "is_munferit": ism,
            "total_collected": round(collected, 2),          # yatırılan (avans + tahsilat)
            "consumed": round(min(collected, invoiced), 2),  # faturayla kapanan
            "net_advance": net,                              # kalan (kullanılmamış avans)
        })
    return {"items": items, "total_balance": round(sum(adv_bal.values()), 2), "count": len(items)}


@router.post("/sedna-import")
def sedna_import_sales(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.sales_invoices", "use")),
):
    """Sedna satış faturası içe aktarma (tekil endpoint)."""
    return run_sales_invoice_import(db, current_user, get_client_ip(request))
