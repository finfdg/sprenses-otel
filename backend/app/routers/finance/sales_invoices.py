"""Otel satış faturaları (120/Alıcılar) — Sedna kaynaklı, FIFO tahsil takibi.

Cariler'in (320) aynası: fatura = 120 Borç (DocumentType=1); tahsilat = 120 Alacak.
Tahsil durumu müşteri bazında tahsilatların faturalara FIFO düşülmesiyle hesaplanır.
Münferit (120.03.*) ve acente ayrı filtrelenir. Onaydan muaf (operasyonel import), audit'li.
"""
import hashlib
import logging
import math
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
    SalesAdvance,
    SalesCollection,
    SalesInvoice,
)
from app.models.user import User
from app.utils.audit import log_action
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.sedna_client import (
    SednaUnavailable,
    fetch_advance_accounts,
    fetch_sales_invoices,
    sedna_configured,
)


from app.services.sales_invoice_service import (
    _EPS,
    _compute_cached,
    _f,
    _invalidate_compute_cache,
    _merged_advances,
)

logger = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Istanbul")
router = APIRouter(prefix="/sales-invoices")


# ─── Yardımcılar ────────────────────────────────────────


# Faz B aynalama güvenlik tavanı: tek koşuda bundan fazla rec_id'li satır Sedna'dan
# kaybolmuşsa (olası kısmi veri / mantık hatası) silme İPTAL edilir, yalnız loglanır.
_MIRROR_SWEEP_CAP = 300


def _is_munferit(code: str, name: str) -> bool:
    """Münferit (bireysel/walk-in) mi — 120.03.* veya adında MÜNFERİT geçen."""
    c = code or ""
    n = (name or "").upper()
    return c.startswith("120.03") or "MÜNFERİT" in n or "MUNFERIT" in n


def _hash(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _native(amount_tl: float, currency, amt_cur) -> tuple:
    """(currency, amount_currency) — döviz ise (Curr, CurrDebit/Credit); değilse ('TL', TL tutarı)."""
    cur = (currency or "TL").strip() or "TL"
    nat = _f(amt_cur)
    if cur != "TL" and nat > 0:
        return cur, round(nat, 2)
    return "TL", round(amount_tl, 2)


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

    # Faz B (2026-07-11) — TAM AYNALAMA: saf insert-only kaldırıldı. Kalıcı kimlik =
    # Sedna AccountingTrans.RecId. Sırasıyla: (1) rec_id'li yerel satır → alanlar Sedna'dan
    # GÜNCELLENİR (tutar düzeltmesi çift satır üretmez); (2) hash eşleşen rec_id'siz eski
    # satır → rec_id damgalanır (geri-doldurma); (3) yeni satır rec_id'li eklenir;
    # (4) rec_id'li olup Sedna aktif kümesinde artık OLMAYAN yerel satır SİLİNİR
    # (güvenlik tavanı _MIRROR_SWEEP_CAP; rec_id'siz eski satırlara dokunulmaz).
    inv_new = inv_skip = col_new = col_skip = 0
    inv_updated = inv_removed = col_updated = col_removed = 0
    try:
        local_invs = db.query(SalesInvoice).all()
        inv_by_recid = {c.sedna_rec_id: c for c in local_invs if c.sedna_rec_id is not None}
        inv_by_hash = {c.tx_hash: c for c in local_invs}
        seen_inv_recids = set()
        for r in inv_rows:
            code = (r.get("customer_code") or "").strip()
            d = r.get("invoice_date")
            if not code or not d:
                continue
            no = (r.get("invoice_no") or "").strip() or None
            amt = _f(r.get("amount"))
            h = _hash("sinv", code, d, no, amt)
            name = (r.get("customer_name") or "").strip()
            cur, amt_nat = _native(amt, r.get("currency"), r.get("amount_currency"))
            rec_id = int(r["rec_id"]) if r.get("rec_id") is not None else None
            if rec_id is not None:
                seen_inv_recids.add(rec_id)
                row = inv_by_recid.get(rec_id)
                if row is not None:
                    if row.tx_hash != h:  # Sedna'da düzeltilmiş → UPDATE (çift satır yok)
                        row.customer_code = code
                        row.customer_name = name
                        row.is_munferit = _is_munferit(code, name)
                        row.invoice_no = no
                        row.invoice_date = d
                        row.amount = amt
                        row.currency = cur
                        row.amount_currency = amt_nat
                        row.description = (r.get("aciklama") or None)
                        inv_by_hash.pop(row.tx_hash, None)
                        row.tx_hash = h
                        inv_by_hash[h] = row
                        inv_updated += 1
                    else:
                        inv_skip += 1
                    continue
            row = inv_by_hash.get(h)
            if row is not None:
                if rec_id is not None and row.sedna_rec_id is None and rec_id not in inv_by_recid:
                    row.sedna_rec_id = rec_id  # kimlik geri-doldurma
                    inv_by_recid[rec_id] = row
                inv_skip += 1
                continue
            row = SalesInvoice(
                customer_code=code, customer_name=name, is_munferit=_is_munferit(code, name),
                invoice_no=no, invoice_date=d, amount=amt, currency=cur, amount_currency=amt_nat,
                description=(r.get("aciklama") or None), tx_hash=h, sedna_rec_id=rec_id,
            )
            db.add(row)
            inv_by_hash[h] = row
            if rec_id is not None:
                inv_by_recid[rec_id] = row
            inv_new += 1

        # rec_id'li olup Sedna aktifinde artık olmayanlar → bayat (düzeltme/silme)
        stale_invs = [c for rid, c in inv_by_recid.items() if rid not in seen_inv_recids]
        if len(stale_invs) > _MIRROR_SWEEP_CAP:
            logger.error("Satış faturası aynalama süpürmesi İPTAL: %d bayat satır tavanı (%d) aştı",
                         len(stale_invs), _MIRROR_SWEEP_CAP)
        else:
            for c in stale_invs:
                db.delete(c)
                inv_removed += 1

        local_cols = db.query(SalesCollection).all()
        col_by_recid = {c.sedna_rec_id: c for c in local_cols if c.sedna_rec_id is not None}
        existing_col = {c.tx_hash: c for c in local_cols}
        seen_col_recids = set()
        for r in col_rows:
            code = (r.get("customer_code") or "").strip()
            d = r.get("collection_date")
            if not code or not d:
                continue
            amt = _f(r.get("amount"))
            fis = r.get("fis_no")
            name = (r.get("customer_name") or "").strip() or None
            h = _hash("scol", code, d, amt, fis)
            cur, amt_nat = _native(amt, r.get("currency"), r.get("amount_currency"))
            rec_id = int(r["rec_id"]) if r.get("rec_id") is not None else None
            if rec_id is not None:
                seen_col_recids.add(rec_id)
                row = col_by_recid.get(rec_id)
                if row is not None:
                    if row.tx_hash != h:
                        row.customer_code = code
                        row.customer_name = name
                        row.collection_date = d
                        row.amount = amt
                        row.currency = cur
                        row.amount_currency = amt_nat
                        row.description = (r.get("aciklama") or None)
                        existing_col.pop(row.tx_hash, None)
                        row.tx_hash = h
                        existing_col[h] = row
                        col_updated += 1
                    else:
                        if name and not (row.customer_name or "").strip():
                            row.customer_name = name
                        col_skip += 1
                    continue
            ex = existing_col.get(h)
            if ex is not None:
                if name and not (ex.customer_name or "").strip():
                    ex.customer_name = name   # boş ismi Sedna'dan doldur
                if rec_id is not None and ex.sedna_rec_id is None and rec_id not in col_by_recid:
                    ex.sedna_rec_id = rec_id
                    col_by_recid[rec_id] = ex
                col_skip += 1
                continue
            col = SalesCollection(
                customer_code=code, customer_name=name, collection_date=d, amount=amt,
                currency=cur, amount_currency=amt_nat,
                description=(r.get("aciklama") or None), tx_hash=h, sedna_rec_id=rec_id,
            )
            db.add(col)
            existing_col[h] = col
            if rec_id is not None:
                col_by_recid[rec_id] = col
            col_new += 1

        stale_cols = [c for rid, c in col_by_recid.items() if rid not in seen_col_recids]
        if len(stale_cols) > _MIRROR_SWEEP_CAP:
            logger.error("Tahsilat aynalama süpürmesi İPTAL: %d bayat satır tavanı (%d) aştı",
                         len(stale_cols), _MIRROR_SWEEP_CAP)
        else:
            for c in stale_cols:
                db.delete(c)
                col_removed += 1

        log_action(
            db, current_user.id, "create", "sales_invoice", entity_id=None,
            details=(f"Sedna satış faturası: {inv_new} yeni, {inv_updated} güncellendi, "
                     f"{inv_removed} silindi fatura · {col_new} yeni, {col_updated} güncellendi, "
                     f"{col_removed} silindi tahsilat"),
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

    # PMS acente adı → 120 cari kodu köprüsünü tazele (hak ediş gruplaması için; best-effort)
    try:
        from app.models.agency_code_map import AgencyCodeMap
        from app.utils.sedna_client import fetch_agency_acc_codes
        pairs = fetch_agency_acc_codes()
        if pairs:
            db.query(AgencyCodeMap).delete()
            seen = set()
            for p in pairs:
                nm = (p.get("pms_name") or "").strip()
                if nm and nm not in seen:
                    seen.add(nm)
                    db.add(AgencyCodeMap(pms_name=nm[:200], acc_code=(p.get("acc_code") or "")[:50]))
            db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Acente→cari kod köprüsü tazelenemedi: %s", e)

    # Yeni fatura/tahsilat eklendi → FIFO cache'i geçersiz kıl (taze veri anında görünsün)
    _invalidate_compute_cache()

    return {
        "invoices_total": len(inv_rows), "invoices_new": inv_new, "invoices_skipped": inv_skip,
        "invoices_updated": inv_updated, "invoices_removed": inv_removed,
        "collections_total": len(col_rows), "collections_new": col_new, "collections_skipped": col_skip,
        "collections_updated": col_updated, "collections_removed": col_removed,
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
    result = run_sales_invoice_import(db, current_user, get_client_ip(request))
    broadcast_finance_update(background_tasks, BroadcastModule.SALES_INVOICES, "upload")
    return result
