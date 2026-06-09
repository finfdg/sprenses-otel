"""Mizan (Geçici Mizan / Trial Balance) — Sedna muhasebe hesaplarının dönem borç/alacak/bakiyesi.

Canlı Sedna sorgusu (yerel saklama yok): `AccountingTrans` (borç/alacak) + `Accounting` (hesap adı).
Leaf hesaplar çekilir, KADEME (ana hesap → alt hesap) bazında Python'da toplanır. Tek mizan fetch tüm
kademeleri + drill-down'ı besler (60sn TTL cache → kademe değiştirme/drill Sedna'yı tekrar yormaz).
Salt-okunur; tünel kapalıysa 503. Çift taraflı kayıt → toplam borç = toplam alacak (denge kontrolü).
"""

import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.utils.sedna_client import (
    SednaUnavailable,
    fetch_account_names,
    fetch_account_transactions,
    fetch_mizan,
    sedna_configured,
)

logger = logging.getLogger(__name__)

_MAX_RANGE_DAYS = 800           # mizan birikimli olabilir (çok yıl) ama sınır koy
_CODE_RE = re.compile(r"^[A-Za-z0-9.]{1,40}$")  # hesap kodu — SQL'e gömülmeden önce güvenli karakter doğrulaması
_CACHE_TTL = 60                 # saniye — kademe/drill arası Sedna round-trip'i azalt (mizan ~60sn'de değişmez)
_TX_LIMIT = 1000

_cache: dict = {}               # key → (expiry_ts, value)

router = APIRouter()


def _cached(key, producer):
    """Basit süreç-içi TTL cache — mizan/ad haritası 60sn boyunca yeniden çekilmez."""
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    val = producer()
    _cache[key] = (now + _CACHE_TTL, val)
    if len(_cache) > 32:  # sınırsız büyümeyi önle — süresi dolmuş girdileri temizle
        for k in [k for k, (exp, _v) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
    return val


def _parse_iso(value, name) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"Geçersiz tarih ({name}): YYYY-AA-GG bekleniyor.")


def _validate_range(start_date: str, end_date: str):
    sd = _parse_iso(start_date, "start_date")
    ed = _parse_iso(end_date, "end_date")
    if ed < sd:
        raise HTTPException(status_code=422, detail="Bitiş tarihi başlangıçtan önce olamaz.")
    if (ed - sd).days > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"Tarih aralığı en fazla {_MAX_RANGE_DAYS} gün olabilir.")
    return sd, ed


def _prefix(code: str, level: int) -> str:
    """Hesap kodunun ilk `level` nokta-segmenti (kademe). '320.01.01.P033', 2 → '320.01'."""
    return ".".join((code or "").split(".")[:level])


def _search_norm(s: str) -> str:
    """Türkçe-duyarsız arama normalizasyonu: küçük harf + birleşik işaretleri at + I/ı/İ/i → 'i'.

    Python `lower()` Türkçe casing yapmaz ('SATIŞLAR'.lower() noktalı i üretir, 'satış' noktasız ı
    içerir → eşleşmez). NFKD + birleşik-işaret atımı aksanı da yoksayar → 'satis' ↔ 'SATIŞLAR' eşleşir.
    """
    out = []
    for ch in unicodedata.normalize("NFKD", (s or "").lower()):
        if unicodedata.combining(ch):
            continue
        out.append("i" if ch in ("ı", "i") else ch)
    return "".join(out)


def _aggregate(rows, names, level: int, parent: Optional[str] = None) -> list:
    """Leaf mizan satırlarını kademe-`level` bazında topla. parent verilirse yalnız o prefix altı."""
    acc: dict = {}
    for r in rows:
        code = (r["code"] or "").strip()
        if not code:
            continue
        if parent and not (code == parent or code.startswith(parent + ".")):
            continue
        key = _prefix(code, level)
        if not key:
            continue
        a = acc.get(key)
        if a is None:
            a = {"code": key, "name": names.get(key, ""), "borc": 0.0, "alacak": 0.0, "maxseg": 0}
            acc[key] = a
        a["borc"] += float(r["borc"] or 0)
        a["alacak"] += float(r["alacak"] or 0)
        a["maxseg"] = max(a["maxseg"], len(code.split(".")))
    out = []
    for a in acc.values():
        borc = round(a["borc"], 2)
        alacak = round(a["alacak"], 2)
        bakiye = round(borc - alacak, 2)
        out.append({
            "code": a["code"],
            "name": a["name"],
            "borc": borc,
            "alacak": alacak,
            "borc_bakiye": bakiye if bakiye > 0 else 0.0,
            "alacak_bakiye": -bakiye if bakiye < 0 else 0.0,
            "bakiye": bakiye,
            "has_children": a["maxseg"] > level,
        })
    out.sort(key=lambda x: x["code"])
    return out


@router.get("/status")
def mizan_status(_: User = Depends(get_current_user)):
    """Sedna mizan etkin mi (sayfa gösterimi)."""
    return {"configured": sedna_configured()}


@router.get("/summary")
def mizan_summary(
    start_date: str = Query(..., description="YYYY-AA-GG (dahil)"),
    end_date: str = Query(..., description="YYYY-AA-GG (dahil)"),
    level: int = Query(1, ge=1, le=6, description="Kademe (1=ana hesap, 2=alt hesap, ...)"),
    parent: Optional[str] = Query(None, description="Drill-down: bu hesabın bir alt kademesi"),
    search: Optional[str] = Query(None, description="Kod/ad araması"),
    _: User = Depends(require_permission("accounting.mizan", "view")),
):
    """Kademe bazında mizan (canlı Sedna). parent verilirse o hesabın doğrudan alt hesapları döner."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    sd, ed = _validate_range(start_date, end_date)
    if parent is not None and not _CODE_RE.match(parent):
        raise HTTPException(status_code=422, detail="Geçersiz hesap kodu.")
    end_excl = (ed + timedelta(days=1)).isoformat()
    try:
        rows = _cached(("mizan", sd.isoformat(), end_excl), lambda: fetch_mizan(sd.isoformat(), end_excl))
        names = _cached(("names",), fetch_account_names)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    eff_level = (len(parent.split(".")) + 1) if parent else level
    data = _aggregate(rows, names, eff_level, parent)
    if search and search.strip():
        s = _search_norm(search)
        data = [d for d in data if s in _search_norm(d["code"]) or s in _search_norm(d["name"])]

    # Denge: TÜM mizan üzerinden (parent/search filtresinden bağımsız) — borç=alacak olmalı
    grand_borc = round(sum(float(r["borc"] or 0) for r in rows), 2)
    grand_alacak = round(sum(float(r["alacak"] or 0) for r in rows), 2)
    return {
        "rows": data,
        "level": eff_level,
        "parent": parent,
        "account_count": len(data),
        "total_borc": round(sum(d["borc"] for d in data), 2),
        "total_alacak": round(sum(d["alacak"] for d in data), 2),
        "grand_total_borc": grand_borc,
        "grand_total_alacak": grand_alacak,
        "balanced": abs(grand_borc - grand_alacak) < 0.01,
        "start_date": sd.isoformat(),
        "end_date": ed.isoformat(),
    }


@router.get("/transactions")
def mizan_transactions(
    code: str = Query(..., min_length=1, max_length=40),
    start_date: str = Query(...),
    end_date: str = Query(...),
    _: User = Depends(require_permission("accounting.mizan", "view")),
):
    """Drill-down: bir hesabın (ve alt hesaplarının) dönem hareketleri + yürüyen bakiye (defter)."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    if not _CODE_RE.match(code):
        raise HTTPException(status_code=422, detail="Geçersiz hesap kodu.")
    sd, ed = _validate_range(start_date, end_date)
    end_excl = (ed + timedelta(days=1)).isoformat()
    try:
        rows = fetch_account_transactions(code, sd.isoformat(), end_excl, _TX_LIMIT)
        names = _cached(("names",), fetch_account_names)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    running = 0.0
    txs = []
    for r in rows:
        d = float(r["debit"] or 0)
        c = float(r["credit"] or 0)
        running += d - c
        txs.append({
            "fiche_date": r["fiche_date"].isoformat() if r.get("fiche_date") else None,
            "voucher": r["voucher"],
            "code": (r["code"] or "").strip(),
            "account_name": names.get((r["code"] or "").strip(), ""),
            "remark": r["remark"],
            "debit": round(d, 2),
            "credit": round(c, 2),
            "balance": round(running, 2),
        })
    return {
        "code": code,
        "account_name": names.get(code, ""),
        "count": len(txs),
        "total_debit": round(sum(t["debit"] for t in txs), 2),
        "total_credit": round(sum(t["credit"] for t in txs), 2),
        "balance": round(running, 2),
        "truncated": len(txs) >= _TX_LIMIT,
        "transactions": txs,
    }
