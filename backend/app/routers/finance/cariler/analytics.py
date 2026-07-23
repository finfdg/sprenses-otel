"""Cari analitik görünümleri — Aylık Bakiye (FIFO Kalan / Dönem Sonu) ve Yıllık Ciro.

2026-07-23 "Cariler modülü yeniden tasarımı" ile eklendi. Salt-okuma GET'ler —
onaydan muaf, finance.cariler view yeterli. Satır sayısı cari sayısıyla sınırlı
(≈300) olduğundan sayfalama yoktur; sıralama frontend'de yapılır.
"""

import calendar
from collections import defaultdict
from datetime import date as date_type
from typing import Dict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.middleware.auth import require_permission
from app.utils.vendor_fifo import calculate_fifo_amounts

# Devir/açılış kayıtları ciro sayılmaz (match_number=-1 işareti veya işlem tipi)
_DEVIR_MATCH = -1
_MIN_AMOUNT = 0.005

router = APIRouter()


def _vendor_map(db: Session, vendor_ids) -> Dict[int, tuple]:
    """vendor_id → (hesap_kodu, hesap_adi) haritası."""
    if not vendor_ids:
        return {}
    rows = (
        db.query(Vendor.id, Vendor.hesap_kodu, Vendor.hesap_adi)
        .filter(Vendor.id.in_(list(vendor_ids)))
        .all()
    )
    return {r.id: (r.hesap_kodu, r.hesap_adi) for r in rows}


@router.get("/monthly-balances")
def get_monthly_balances(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    mode: str = Query("fifo", pattern="^(fifo|period)$"),
    hide_zero: bool = Query(True),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Ay bazlı cari bakiye görünümü (Aylık Bakiye sekmesi).

    mode=fifo  → **FIFO Kalan**: seçilen ayın faturalarından (alacak) FIFO sonrası
                 kalanı olan cariler. Ödemeler (havale/EFT, çek, kredi kartı) en eski
                 faturadan düşülür — Ödeme Planı / Vadesi Geçmiş kartıyla AYNI
                 `calculate_fifo_amounts` kaynağı. Tamamen kapananlar listelenmez.
    mode=period→ **Dönem Sonu Bakiye**: ay sonu itibarıyla yürüyen bakiye
                 (o tarihe kadarki tüm borç/alacak toplamları). `hide_zero`
                 sıfır bakiyeli carileri gizler (yalnız bu modda anlamlı).
    """
    month_start = date_type(year, month, 1)
    month_end = date_type(year, month, calendar.monthrange(year, month)[1])

    if mode == "fifo":
        fifo = calculate_fifo_amounts(db)  # {vtx_id: ödenmemiş tutar}
        rows = (
            db.query(
                VendorTransaction.id,
                VendorTransaction.vendor_id,
                VendorTransaction.alacak,
            )
            .filter(
                VendorTransaction.alacak > 0,
                VendorTransaction.date >= month_start,
                VendorTransaction.date <= month_end,
            )
            .all()
        )
        acc: Dict[int, Dict[str, float]] = defaultdict(lambda: {"invoiced": 0.0, "remaining": 0.0})
        for r in rows:
            slot = acc[r.vendor_id]
            slot["invoiced"] += float(r.alacak)
            slot["remaining"] += float(fifo.get(r.id, 0.0))

        vmap = _vendor_map(db, [vid for vid, s in acc.items() if s["remaining"] > _MIN_AMOUNT])
        items = []
        for vid, s in acc.items():
            if s["remaining"] <= _MIN_AMOUNT or vid not in vmap:
                continue
            invoiced = round(s["invoiced"], 2)
            remaining = round(s["remaining"], 2)
            items.append({
                "vendor_id": vid,
                "hesap_kodu": vmap[vid][0],
                "hesap_adi": vmap[vid][1],
                "invoiced": invoiced,
                "closed": round(invoiced - remaining, 2),
                "remaining": remaining,
            })
        items.sort(key=lambda x: -x["remaining"])
        totals = {
            "invoiced": round(sum(i["invoiced"] for i in items), 2),
            "closed": round(sum(i["closed"] for i in items), 2),
            "remaining": round(sum(i["remaining"] for i in items), 2),
        }
        return {"mode": mode, "year": year, "month": month, "items": items, "totals": totals}

    # mode == "period" — ay sonu itibarıyla yürüyen bakiye
    rows = (
        db.query(
            VendorTransaction.vendor_id,
            func.coalesce(func.sum(VendorTransaction.borc), 0).label("total_borc"),
            func.coalesce(func.sum(VendorTransaction.alacak), 0).label("total_alacak"),
        )
        .filter(VendorTransaction.date <= month_end)
        .group_by(VendorTransaction.vendor_id)
        .all()
    )
    vmap = _vendor_map(db, [r.vendor_id for r in rows])
    items = []
    for r in rows:
        borc = float(r.total_borc)
        alacak = float(r.total_alacak)
        if borc <= _MIN_AMOUNT and alacak <= _MIN_AMOUNT:
            continue
        balance = round(borc - alacak, 2)
        if hide_zero and abs(balance) <= _MIN_AMOUNT:
            continue
        if r.vendor_id not in vmap:
            continue
        items.append({
            "vendor_id": r.vendor_id,
            "hesap_kodu": vmap[r.vendor_id][0],
            "hesap_adi": vmap[r.vendor_id][1],
            "total_borc": round(borc, 2),
            "total_alacak": round(alacak, 2),
            "balance": balance,
        })
    items.sort(key=lambda x: x["balance"])
    totals = {
        "total_borc": round(sum(i["total_borc"] for i in items), 2),
        "total_alacak": round(sum(i["total_alacak"] for i in items), 2),
        "balance": round(sum(i["balance"] for i in items), 2),
    }
    return {"mode": mode, "year": year, "month": month, "items": items, "totals": totals}


@router.get("/yearly-turnover")
def get_yearly_turnover(
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Yıllık Ciro sekmesi — firma bazında yıl içi fatura (alacak) hacmi.

    Devir/açılış kayıtları hariç (match_number=-1 veya işlem tipinde devir/açılış).
    Aylık dağılım (12 kalem) + fatura sayısı + toplam ciro döner.
    """
    type_col = func.coalesce(VendorTransaction.transaction_type, "")
    rows = (
        db.query(
            VendorTransaction.vendor_id,
            extract("month", VendorTransaction.date).label("m"),
            func.coalesce(func.sum(VendorTransaction.alacak), 0).label("total"),
            func.count(VendorTransaction.id).label("cnt"),
        )
        .filter(
            VendorTransaction.alacak > 0,
            extract("year", VendorTransaction.date) == year,
            (VendorTransaction.match_number.is_(None)) | (VendorTransaction.match_number != _DEVIR_MATCH),
            ~type_col.ilike("%devir%"),
            ~type_col.ilike("%açılış%"),
        )
        .group_by(VendorTransaction.vendor_id, extract("month", VendorTransaction.date))
        .all()
    )

    acc: Dict[int, Dict] = {}
    for r in rows:
        slot = acc.setdefault(r.vendor_id, {"monthly": [0.0] * 12, "invoice_count": 0, "turnover": 0.0})
        m_idx = int(r.m) - 1
        amount = float(r.total)
        slot["monthly"][m_idx] += amount
        slot["invoice_count"] += int(r.cnt)
        slot["turnover"] += amount

    vmap = _vendor_map(db, [vid for vid, s in acc.items() if s["turnover"] > _MIN_AMOUNT])
    items = []
    for vid, s in acc.items():
        if s["turnover"] <= _MIN_AMOUNT or vid not in vmap:
            continue
        items.append({
            "vendor_id": vid,
            "hesap_kodu": vmap[vid][0],
            "hesap_adi": vmap[vid][1],
            "monthly": [round(m, 2) for m in s["monthly"]],
            "invoice_count": s["invoice_count"],
            "turnover": round(s["turnover"], 2),
        })
    items.sort(key=lambda x: -x["turnover"])
    total_turnover = round(sum(i["turnover"] for i in items), 2)
    total_invoices = sum(i["invoice_count"] for i in items)
    return {
        "year": year,
        "items": items,
        "total_turnover": total_turnover,
        "total_invoices": total_invoices,
    }
