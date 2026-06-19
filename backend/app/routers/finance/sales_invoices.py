"""Otel satış faturaları (120/Alıcılar) — Sedna kaynaklı, FIFO tahsil takibi.

Cariler'in (320) aynası: fatura = 120 Borç (DocumentType=1); tahsilat = 120 Alacak.
Tahsil durumu müşteri bazında tahsilatların faturalara FIFO düşülmesiyle hesaplanır.
Münferit (120.03.*) ve acente ayrı filtrelenir. Onaydan muaf (operasyonel import), audit'li.
"""
import hashlib
import logging
import math
import threading
import time
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
    SalesAdvance,
    SalesCollection,
    SalesInvoice,
)
from app.models.user import User
from app.utils.audit import log_action
from app.utils.sedna_client import (
    SednaUnavailable,
    fetch_advance_accounts,
    fetch_sales_invoices,
    sedna_configured,
)

from .advances import _norm_tokens  # acente adı token eşleştirme (340 ↔ 120 mükerrer önleme)

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


def _native(amount_tl: float, currency, amt_cur) -> tuple:
    """(currency, amount_currency) — döviz ise (Curr, CurrDebit/Credit); değilse ('TL', TL tutarı)."""
    cur = (currency or "TL").strip() or "TL"
    nat = _f(amt_cur)
    if cur != "TL" and nat > 0:
        return cur, round(nat, 2)
    return "TL", round(amount_tl, 2)


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
    def _amt(o):  # native (döviz) tutar — yoksa TL'ye düş
        n = _f(o.amount_currency)
        return n if n > _EPS else _f(o.amount)

    # (müşteri, para birimi) bazında grupla — EUR avans yalnız EUR faturayı kapatır
    inv_by: dict = defaultdict(list)
    col_by: dict = defaultdict(list)
    for inv in db.query(SalesInvoice).all():
        inv_by[(inv.customer_code, inv.currency)].append(inv)
    for col in db.query(SalesCollection).all():
        col_by[(col.customer_code, col.currency)].append(col)

    inv_map: dict = {}
    advance_balance: dict = {}   # (code, currency) -> native leftover (net avans)

    for key in set(inv_by) | set(col_by):
        invs = inv_by.get(key, [])
        events = [(inv.invoice_date, 0, "inv", inv) for inv in invs]
        events += [(col.collection_date, 1, "col", col) for col in col_by.get(key, [])]
        events.sort(key=lambda e: (e[0], e[1]))

        pool = 0.0           # mevcut avans/kredi havuzu (native)
        open_q: list = []    # açık faturalar FIFO: [(inv, remaining_native)]
        state: dict = {}     # inv.id -> [collected_native, advance_native]
        for _d, _t, kind, obj in events:
            if kind == "col":
                pool += _amt(obj)
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
                amount = _amt(obj)
                adv = min(pool, amount) if pool > _EPS else 0.0
                pool -= adv
                state[obj.id] = [adv, adv]
                if amount - adv > _EPS:
                    open_q.append((obj, amount - adv))

        for inv in invs:
            collected, adv = state.get(inv.id, [0.0, 0.0])
            nat_amt = _amt(inv)
            ratio = (collected / nat_amt) if nat_amt > _EPS else 0.0
            if collected >= nat_amt - _EPS:
                st = STATUS_PAID
            elif collected > _EPS:
                st = STATUS_PARTIAL
            else:
                st = STATUS_OPEN
            inv_map[inv.id] = {
                "collected": round(collected, 2),           # native
                "collected_tl": round(_f(inv.amount) * ratio, 2),
                "advance": round(adv, 2),                   # native
                "status": st,
            }
        if pool > _EPS:
            advance_balance[key] = round(pool, 2)
    return inv_map, advance_balance


# ─── _compute TTL cache ─────────────────────────────────
# _compute her çağrıda iki tam tabloyu (faturalar + tahsilatlar) belleğe çekip FIFO yapar.
# 4 endpoint (list/summary/advances + yonetim/dashboard) aynı sonucu kullanır ve veri yalnız
# Sedna içe aktarmada değişir → 30sn süreç-içi cache tekrar hesaplamayı önler (mizan deseni).
_COMPUTE_TTL = 30.0  # saniye
_compute_cache: dict = {"ts": 0.0, "data": None}
_compute_lock = threading.Lock()


def _compute_cached(db: Session):
    """_compute sonucunu 30sn cache'ler. İçe aktarma _invalidate_compute_cache() çağırır."""
    now = time.monotonic()
    data = _compute_cache["data"]
    if data is not None and (now - _compute_cache["ts"]) < _COMPUTE_TTL:
        return data
    data = _compute(db)
    with _compute_lock:
        _compute_cache["data"] = data
        _compute_cache["ts"] = now
    return data


def _invalidate_compute_cache() -> None:
    """Satış faturası içe aktarmadan sonra cache'i sıfırla → kullanıcı taze veriyi anında görür."""
    with _compute_lock:
        _compute_cache["data"] = None
        _compute_cache["ts"] = 0.0


def _invoice_item(inv: SalesInvoice, smap: dict) -> dict:
    """Tek fatura satırını liste yanıtı sözlüğüne çevirir (smap = _compute durum haritası)."""
    entry = smap.get(inv.id, {"collected": 0.0, "advance": 0.0, "status": STATUS_OPEN})
    amt_tl = _f(inv.amount)
    amt_nat = _f(inv.amount_currency) or amt_tl     # döviz tutarı (TL ise = TL)
    col = entry["collected"]                          # native
    return {
        "id": inv.id, "customer_code": inv.customer_code, "customer_name": inv.customer_name,
        "is_munferit": inv.is_munferit, "invoice_no": inv.invoice_no,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "amount": amt_nat, "amount_tl": amt_tl, "currency": inv.currency,
        "collected": col, "remaining": round(amt_nat - col, 2),
        "status": entry["status"], "advance_covered": entry["advance"],
        "by_advance": entry["advance"] > _EPS, "description": inv.description,
    }


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
            cur, amt_nat = _native(amt, r.get("currency"), r.get("amount_currency"))
            db.add(SalesInvoice(
                customer_code=code, customer_name=name, is_munferit=_is_munferit(code, name),
                invoice_no=no, invoice_date=d, amount=amt, currency=cur, amount_currency=amt_nat,
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
            cur, amt_nat = _native(amt, r.get("currency"), r.get("amount_currency"))
            col = SalesCollection(
                customer_code=code, customer_name=name, collection_date=d, amount=amt,
                currency=cur, amount_currency=amt_nat,
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

    # 340 'Alınan Avanslar' özetini tazele (truncate + reload) — acente avanslarının asıl defteri
    adv_count = 0
    try:
        accounts = fetch_advance_accounts()
        db.query(SalesAdvance).delete()
        for a in accounts:
            db.add(SalesAdvance(
                code=(a.get("code") or "")[:50], name=(a.get("name") or None),
                currency=(a.get("currency") or "TL").strip() or "TL",
                received=_f(a.get("received")), consumed=_f(a.get("consumed")),
            ))
            adv_count += 1
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("340 avans özeti tazelenemedi: %s", e)

    # Yeni fatura/tahsilat eklendi → FIFO cache'i geçersiz kıl (taze veri anında görünsün)
    _invalidate_compute_cache()

    return {
        "invoices_total": len(inv_rows), "invoices_new": inv_new, "invoices_skipped": inv_skip,
        "collections_total": len(col_rows), "collections_new": col_new, "collections_skipped": col_skip,
        "advance_accounts": adv_count,
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
    smap, _ = _compute_cached(db)
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
    q = q.order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.id.desc())
    start = (page - 1) * page_size

    if status:
        # status FIFO'dan türetilir, SQL'e itilemez → DB-filtreli satırları çek, durum süz,
        # sonra Python'da sayfala (smap cache'li, böylece tekrar FIFO yok).
        rows = [inv for inv in q.all() if smap.get(inv.id, {}).get("status", STATUS_OPEN) == status]
        total = len(rows)
        page_rows = rows[start:start + page_size]
    else:
        # status filtresi yok (yaygın durum) → gerçek SQL sayfalama (count + offset/limit).
        total = q.count()
        page_rows = q.offset(start).limit(page_size).all()

    items = [_invoice_item(inv, smap) for inv in page_rows]
    pages = max(1, math.ceil(total / page_size))
    return {
        "items": items,
        "total": total, "page": page, "page_size": page_size, "pages": pages,
    }


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.sales_invoices", "view")),
):
    """Satış faturası özeti: toplam faturalanan/tahsil/açık + durum + münferit/acente kırılımı + avans."""
    smap, _ = _compute_cached(db)
    invoices = db.query(SalesInvoice).all()
    agg = {
        "total": {"invoiced": 0.0, "collected": 0.0, "count": 0},
        "munferit": {"invoiced": 0.0, "collected": 0.0, "count": 0},
        "agency": {"invoiced": 0.0, "collected": 0.0, "count": 0},
    }
    status_counts = {STATUS_PAID: 0, STATUS_PARTIAL: 0, STATUS_OPEN: 0}
    for inv in invoices:
        entry = smap.get(inv.id, {"collected_tl": 0.0, "status": STATUS_OPEN})
        amt = _f(inv.amount)  # TL karşılığı (konsolide)
        bucket = "munferit" if inv.is_munferit else "agency"
        for key in ("total", bucket):
            agg[key]["invoiced"] += amt
            agg[key]["collected"] += entry.get("collected_tl", 0.0)
            agg[key]["count"] += 1
        status_counts[entry["status"]] += 1
    for key in agg:
        agg[key]["invoiced"] = round(agg[key]["invoiced"], 2)
        agg[key]["collected"] = round(agg[key]["collected"], 2)
        agg[key]["outstanding"] = round(agg[key]["invoiced"] - agg[key]["collected"], 2)

    # net avans — 340 'Alınan Avanslar' + 120 net-alacak birleşik (para birimi bazında)
    merged_adv, adv_by_cur = _merged_advances(db)
    return {
        **agg,
        "status_counts": status_counts,
        "advance": {  # kullanılmamış net avans (340 asıl defter + 120 net-alacak)
            "by_currency": adv_by_cur,                        # {"TL": x, "EUR": y}
            "agency_count": len(merged_adv),
        },
    }


def _merged_advances(db: Session):
    """Acente avans bakiyeleri (EKSİKSİZ): Sedna 340 'Alınan Avanslar' (asıl defter) + 120 net-alacak.
    340'ta adı geçen 120 kaydı atlanır (mükerrer önleme). Döner: (merged_items, total_by_currency)."""
    # 120 net-alacak (offline, import edilmiş veriden)
    _, adv_bal = _compute_cached(db)
    items_120 = []
    if adv_bal:
        inv_info: dict = {}
        for code, cur, name, ism, inv in (
            db.query(SalesInvoice.customer_code, SalesInvoice.currency,
                     func.max(SalesInvoice.customer_name), func.bool_or(SalesInvoice.is_munferit),
                     func.sum(SalesInvoice.amount_currency))
            .group_by(SalesInvoice.customer_code, SalesInvoice.currency).all()
        ):
            inv_info[(code, cur)] = {"name": name, "ism": bool(ism), "invoiced": _f(inv)}
        col_info: dict = {}
        for code, cur, name, tot in (
            db.query(SalesCollection.customer_code, SalesCollection.currency,
                     func.max(SalesCollection.customer_name), func.sum(SalesCollection.amount_currency))
            .group_by(SalesCollection.customer_code, SalesCollection.currency).all()
        ):
            col_info[(code, cur)] = {"name": name, "amount": _f(tot)}
        for (code, cur), net in adv_bal.items():
            im = inv_info.get((code, cur))
            cm = col_info.get((code, cur), {})
            invoiced = im["invoiced"] if im else 0.0
            collected = cm.get("amount", 0.0)
            items_120.append({
                "customer_name": (im["name"] if im else None) or cm.get("name") or code,
                "currency": cur, "source": "120",
                "is_munferit": im["ism"] if im else code.startswith("120.03"),
                "received": round(collected, 2), "consumed": round(min(collected, invoiced), 2),
                "remaining": net,
            })

    # 340 'Alınan Avanslar' (asıl avans defteri; import edilmiş tablodan — offline)
    items_340 = []
    for a in db.query(SalesAdvance).all():
        rem = round(_f(a.received) - _f(a.consumed), 2)
        if rem > 1:
            items_340.append({
                "customer_name": a.name or a.code, "currency": a.currency or "TL", "source": "340",
                "is_munferit": False,
                "received": round(_f(a.received), 2), "consumed": round(_f(a.consumed), 2), "remaining": rem,
            })

    # birleştir — 340 öncelikli; 120'den adı 340'ta geçeni at (mükerrer)
    tok_340 = [_norm_tokens(x["customer_name"]) for x in items_340]
    merged = list(items_340)
    for it in items_120:
        t = _norm_tokens(it["customer_name"])
        if t and any(len(t & n) >= 1 for n in tok_340):
            continue
        merged.append(it)
    # Döviz-bazlı sırala: önce yabancı para grupları (EUR vb.), sonra TL — her grup içinde kalan azalan.
    # Ham `remaining` ile sıralamak farklı para birimlerini (4M € vs 3M ₺) yanlış kıyaslardı.
    merged.sort(key=lambda x: (x["currency"] == "TL", x["currency"], -x["remaining"]))

    total_by_cur: dict = {}
    for x in merged:
        total_by_cur[x["currency"]] = round(total_by_cur.get(x["currency"], 0.0) + x["remaining"], 2)
    return merged, total_by_cur


@router.get("/advances")
def advance_balances(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.sales_invoices", "view")),
):
    """Acente avans bakiyeleri — 340 'Alınan Avanslar' + 120 net-alacak birleşik (source: 340|120)."""
    merged, total_by_cur = _merged_advances(db)
    return {"items": merged, "total_by_currency": total_by_cur, "count": len(merged)}


@router.post("/sedna-import")
def sedna_import_sales(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.sales_invoices", "use")),
):
    """Sedna satış faturası içe aktarma (tekil endpoint)."""
    return run_sales_invoice_import(db, current_user, get_client_ip(request))
