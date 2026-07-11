"""Alınan Avanslar modülü — Acente/operatör avansları CRUD."""

import json
import re
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.advance import Advance
from app.models.user import User
from app.schemas.advance import (
    AdvanceCreate,
    AdvanceMatchRequest,
    AdvanceResponse,
    AdvanceUpdate,
)
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.pagination import page_meta
from app.constants import BroadcastModule
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.services import advance_service
from app.utils.sedna_client import SednaUnavailable, fetch_advance_accounts, sedna_configured
from app.utils.sql_search import like_pattern
from app.utils.text_match import _norm_tokens

router = APIRouter(prefix="/avanslar")


def _agency_code_map(db) -> dict:
    """Faz C: acente adı (küçük harf) → Sedna 340 kod listesi (agency_groups eşlemesinden).

    Grup adı ve üyeleri anahtar olur; kod-öncelikli eşleşme ad-fuzzy'den önce denenir.
    """
    from app.models import AgencyGroup

    out: dict = {}
    for g in db.query(AgencyGroup).filter(AgencyGroup.sedna_account_codes.isnot(None)).all():
        codes = list(g.sedna_account_codes or [])
        if not codes:
            continue
        for key in [g.name] + list(g.members or []):
            k = (str(key) or "").strip().lower()
            if k:
                out.setdefault(k, codes)
    return out


def _match_account(agency_name: str, currency: str, accounts: list, used: set,
                   code_map=None):
    """Manuel acente adını Sedna 340 hesabıyla eşleştir.

    Faz C: önce KOD-ÖNCELİKLİ (agency_groups.sedna_account_codes — deterministik);
    kod eşlemesi yoksa mevcut ad-fuzzy (token örtüşmesi + para birimi) fallback.
    """
    if code_map:
        codes = code_map.get((agency_name or "").strip().lower())
        if codes:
            cands = [a for a in accounts if a["code"] in codes and a["code"] not in used]
            if cands:
                exact = [a for a in cands if a.get("currency") == currency]
                return (exact or cands)[0]
    mt = _norm_tokens(agency_name)
    if not mt:
        return None
    best, best_score = None, 0.0
    for a in accounts:
        if a["code"] in used:
            continue
        overlap = len(mt & _norm_tokens(a["name"]))
        if overlap < 1:
            continue
        score = overlap + (0.5 if a.get("currency") == currency else 0.0)
        if score > best_score:
            best_score, best = score, a
    return best


# ─── Yardımcı ────────────────────────────────────────────


def _build_response(adv: Advance) -> dict:
    """Avans kaydından yanıt oluştur."""
    return AdvanceResponse(
        id=adv.id,
        agency_name=adv.agency_name,
        amount=float(adv.amount),
        currency=adv.currency,
        advance_date=adv.advance_date,
        status=adv.status,
        notes=adv.notes,
        bank_transaction_id=adv.bank_transaction_id,
        received_date=adv.received_date,
        received_amount=float(adv.received_amount) if adv.received_amount is not None else None,
        created_by=adv.created_by,
        creator_name=adv.creator.full_name if adv.creator else None,
        created_at=adv.created_at,
        updated_at=adv.updated_at,
    ).model_dump()


# ─── LIST ─────────────────────────────────────────────────


@router.get("/")
def list_advances(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.avanslar", "view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, pattern="^(pending|received|cancelled)$"),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
):
    """Avans listesi (sayfalı, filtrelenebilir)."""
    q = db.query(Advance)

    if status:
        q = q.filter(Advance.status == status)
    if currency:
        q = q.filter(Advance.currency == currency)
    if search:
        q = q.filter(Advance.agency_name.ilike(like_pattern(search), escape="\\"))
    if date_from:
        q = q.filter(Advance.advance_date >= date_from)
    if date_to:
        q = q.filter(Advance.advance_date <= date_to)

    total = q.count()
    items = (
        q.order_by(desc(Advance.advance_date), desc(Advance.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return page_meta([_build_response(adv) for adv in items], total, page, page_size)


# ─── CREATE ───────────────────────────────────────────────


@router.post("/", status_code=201)
def create_advance(
    data: AdvanceCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.avanslar", "use")),
):
    """Yeni avans kaydı oluştur."""
    approval_resp = check_approval(db, "finance.avanslar", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    adv = advance_service.create_advance(db, data.model_dump(), current_user.id)

    log_action(
        db, current_user.id, "create", "advance", adv.id,
        json.dumps({"agency_name": data.agency_name, "amount": data.amount, "currency": data.currency}, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ADVANCES, "create")
    db.refresh(adv)
    return _build_response(adv)


# ─── UPDATE ───────────────────────────────────────────────


@router.patch("/{advance_id}")
def update_advance(
    advance_id: int,
    data: AdvanceUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.avanslar", "use")),
):
    """Avans kaydını güncelle."""
    adv = db.query(Advance).filter(Advance.id == advance_id).first()
    if not adv:
        raise HTTPException(status_code=404, detail="Avans kaydı bulunamadı")

    approval_resp = check_approval(db, "finance.avanslar", advance_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp

    changes = advance_service.apply_advance_update(db, adv, data.model_dump(exclude_unset=True))

    if not changes:
        return _build_response(adv)

    log_action(
        db, current_user.id, "update", "advance", adv.id,
        json.dumps(changes, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ADVANCES, "update")
    db.refresh(adv)
    return _build_response(adv)


# ─── DELETE ───────────────────────────────────────────────


@router.delete("/{advance_id}")
def delete_advance(
    advance_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.avanslar", "use")),
):
    """Avans kaydını sil (sadece bekleyen kayıtlar)."""
    adv = db.query(Advance).filter(Advance.id == advance_id).first()
    if not adv:
        raise HTTPException(status_code=404, detail="Avans kaydı bulunamadı")

    approval_resp = check_approval(db, "finance.avanslar", advance_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    if adv.status == "received":
        raise HTTPException(status_code=400, detail="Alınmış avanslar silinemez")

    log_action(
        db, current_user.id, "delete", "advance", adv.id,
        json.dumps({"agency_name": adv.agency_name, "amount": float(adv.amount), "currency": adv.currency}, ensure_ascii=False),
        get_client_ip(request),
    )
    advance_service.delete_advance(db, adv)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ADVANCES, "delete")
    return {"detail": "Avans kaydı silindi"}


# ─── MATCH (Banka Eşleştirme) ────────────────────────────


@router.post("/{advance_id}/match")
def match_advance(
    advance_id: int,
    data: AdvanceMatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.avanslar", "use")),
):
    """Avansı banka işlemiyle eşleştir (durum -> alındı)."""
    adv = db.query(Advance).filter(Advance.id == advance_id).first()
    if not adv:
        raise HTTPException(status_code=404, detail="Avans kaydı bulunamadı")

    if adv.status == "cancelled":
        raise HTTPException(status_code=400, detail="İptal edilmiş avans eşleştirilemez")

    adv.status = "received"
    adv.received_date = data.received_date
    adv.received_amount = data.received_amount
    if data.bank_transaction_id:
        adv.bank_transaction_id = data.bank_transaction_id

    log_action(
        db, current_user.id, "update", "advance", adv.id,
        json.dumps({
            "action": "match",
            "received_date": str(data.received_date),
            "received_amount": data.received_amount,
            "bank_transaction_id": data.bank_transaction_id,
        }, ensure_ascii=False),
        get_client_ip(request),
    )
    db.flush()
    if data.bank_transaction_id:
        finance_event_svc.match(db, "bank", data.bank_transaction_id, "advance", adv.id)
    else:
        finance_event_svc.upsert_advance(db, adv)
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.ADVANCES, "match")
    db.refresh(adv)
    return _build_response(adv)


# ─── SUMMARY ──────────────────────────────────────────────


@router.get("/summary")
def advance_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.avanslar", "view")),
):
    """Özet: bekleyen ve alınan toplam tutarlar (para birimine göre)."""
    rows = (
        db.query(
            Advance.currency,
            Advance.status,
            func.sum(Advance.amount).label("total_amount"),
            func.count(Advance.id).label("count"),
        )
        .filter(Advance.status != "cancelled")
        .group_by(Advance.currency, Advance.status)
        .all()
    )

    result = {}
    for currency, status, total_amount, count in rows:
        if currency not in result:
            result[currency] = {"pending": 0.0, "received": 0.0, "pending_count": 0, "received_count": 0}
        if status == "pending":
            result[currency]["pending"] = float(total_amount or 0)
            result[currency]["pending_count"] = count
        elif status == "received":
            result[currency]["received"] = float(total_amount or 0)
            result[currency]["received_count"] = count

    return result


# ─── SEDNA MUTABAKAT (340 Alınan Avanslar ile) ───────────


@router.get("/sedna-reconciliation")
def sedna_reconciliation(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.avanslar", "view")),
):
    """Manuel avanslar ↔ Sedna 340 'Alınan Avanslar' mutabakatı.

    Manuel modüldeki acente bazında ALINAN avanslar, Sedna'nın 340 hesaplarıyla (acente adı
    eşleştirmeli) kıyaslanır: beklenen (manuel) vs gerçekleşen (Sedna) + kalan avans + fark.
    Sedna'da olup manuelde olmayan avans hesapları da raporlanır (eksik kayıtlar). Canlı 340 çekilir.
    """
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")
    try:
        accounts = fetch_advance_accounts()
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail="Sedna avans verisi alınamadı. Lütfen tekrar deneyin.")

    for a in accounts:
        a["received"] = float(a.get("received") or 0)
        a["consumed"] = float(a.get("consumed") or 0)
        a["currency"] = (a.get("currency") or "TL").strip() or "TL"

    manual = (
        db.query(
            Advance.agency_name, Advance.currency,
            func.sum(case((Advance.status == "received", Advance.received_amount), else_=0)),
            func.sum(case((Advance.status == "pending", Advance.amount), else_=0)),
        )
        .group_by(Advance.agency_name, Advance.currency)
        .all()
    )

    used: set = set()
    matched = []
    code_map = _agency_code_map(db)  # Faz C: kod-öncelikli eşleşme
    for name, cur, rec, pend in manual:
        cur = (cur or "EUR")
        m = _match_account(name, cur, accounts, used, code_map=code_map)
        if m:
            used.add(m["code"])
        s_rec = m["received"] if m else 0.0
        s_rem = (m["received"] - m["consumed"]) if m else 0.0
        matched.append({
            "agency_name": name, "currency": cur,
            "manual_received": round(float(rec or 0), 2),
            "manual_pending": round(float(pend or 0), 2),
            "matched": m is not None,
            "sedna_account": m["name"] if m else None,
            "sedna_code": m["code"] if m else None,
            "sedna_currency": m["currency"] if m else None,
            "sedna_received": round(s_rec, 2),
            "sedna_remaining": round(s_rem, 2),
            "variance": round(s_rec - float(rec or 0), 2),
        })

    sedna_only = sorted(
        [
            {"agency_name": a["name"], "sedna_code": a["code"], "currency": a["currency"],
             "received": round(a["received"], 2), "remaining": round(a["received"] - a["consumed"], 2)}
            for a in accounts if a["code"] not in used and (a["received"] - a["consumed"]) > 1
        ],
        key=lambda x: -x["remaining"],
    )
    return {"matched": matched, "sedna_only": sedna_only, "sedna_account_count": len(accounts)}
