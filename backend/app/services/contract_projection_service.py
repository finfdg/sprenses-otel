"""Kontrat + TAM CİRO nakit projeksiyonu servisi (Faz 2, 2026-07-17).

#26 kararı (kullanıcı, varyant iii): beklenen acente tahsilatı ANA nakit projeksiyona
TAM CİRO olarak girer. Uygulama biçimi bilinçli olarak **okuma-anında servis**
(cc_projection_service deseni) — finance_events'e YAZILMAZ: bayat kayıt riski sıfır,
#27 "çift motor" drift'i yok, broadcast sigortası gerekmez. Üç tüketici (eur_balances,
runway, t_account) bu servisten okur.

ÇİFT SAYIM KORUMALARI (4 vektör — kontrat analiz raporu kural seti):
[1] advances tablosu BİRİNCİL kalır (kullanıcı elle işletiyor; pending advance FE'leri
    zaten projeksiyonda gelir sayılıyor). Kontrat taksitleri GRUP bazında kronolojik
    FIFO ile pending-advance havuzuna netlenir — yalnız havuzu AŞAN kısım projeksiyona
    girer (ör. Alltours advances 940k pending ↔ kontrat 2026 taksitleri 1M → net 60k).
[2] guarantee_check planları (otelin VERDİĞİ teminat — Odeon 2×24M TL) HİÇ girmez.
[3] TAM CİRO serisi compute_settlement'tan alınır (avans-MAHSUPLU tahsilat); mevcut
    340 havuzu mahsubuna ek olarak GELECEK sözleşmesel girişler (pending advances +
    net taksitler) ciro serisinin başından FIFO kırpılır — aynı para hem "avans girişi"
    hem "ciro tahsilatı" olarak iki kez sayılmaz.
[4] Banka gerçekleşmesi: taksit paid olunca (elle veya Faz 2 eşleştirici) seriden düşer;
    ciro gerçekleşmeleri compute_settlement'ta zaten geçmiş aylara "collected" yazılır —
    projeksiyon yalnız BUGÜN SONRASI pencereyi besler.

Koşullu taksitler (W2M %70 şartı) `conditional` bayrağıyla döner — tüketici ayrı
gösterebilir; toplamlara dahildir (temkinli senaryo tüketicide filtrelenebilir).
data_confidence bayrağı kalemlerde taşınır (taranmış-belge kaynaklı değerler).
"""
import time
from calendar import monthrange
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.advance import Advance
from app.models.agency_group import AgencyGroup
from app.models.contract import (
    INSTALLMENT_PENDING, PLAN_TYPE_GUARANTEE_CHECK, AgencyContract,
    ContractInstallment, ContractPaymentPlan,
)

# 30 sn TTL süreç-içi cache (cc_projection/settlement desenleriyle tutarlı)
_CACHE: dict = {"t": 0.0, "key": None, "val": None}
_TTL = 30.0


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _advance_group_id(agency_name: str, groups: list) -> Optional[int]:
    """advances.agency_name (serbest metin) → grup id. Grup adı veya üye adıyla
    içerme bazlı eşleşme (advances 'Alltours', grup 'ALLTOURS' yazımları için)."""
    a = _norm(agency_name)
    if not a:
        return None
    for g in groups:
        if a == _norm(g.name) or a in _norm(g.name) or _norm(g.name) in a:
            return g.id
        for m in (g.members or []):
            if a == _norm(m):
                return g.id
    return None


def _compute(db: Session, today: date) -> dict:
    groups = db.query(AgencyGroup).all()

    # ── Pending advances (tablo — FE'leri zaten projeksiyonda; burada yalnız
    #    netleme havuzu olarak kullanılır) ─────────────────────────────────
    adv_pool: dict = defaultdict(float)   # group_id → pending EUR toplamı
    adv_pending_total = 0.0
    for a in db.query(Advance).filter(Advance.status == "pending").all():
        if (a.currency or "EUR").upper() != "EUR":
            continue
        gid = _advance_group_id(a.agency_name, groups)
        amt = float(a.amount or 0)
        adv_pending_total += amt
        if gid:
            adv_pool[gid] += amt

    # ── Kontrat taksitleri (pending, EUR, teminat hariç) — grup FIFO netleme ──
    rows = (
        db.query(ContractInstallment, ContractPaymentPlan, AgencyContract)
        .join(ContractPaymentPlan, ContractInstallment.plan_id == ContractPaymentPlan.id)
        .join(AgencyContract, ContractPaymentPlan.contract_id == AgencyContract.id)
        .filter(
            ContractPaymentPlan.plan_type != PLAN_TYPE_GUARANTEE_CHECK,
            ContractInstallment.status == INSTALLMENT_PENDING,
            ContractInstallment.amount.isnot(None),
            ContractInstallment.currency == "EUR",
            ContractInstallment.due_date.isnot(None),
        )
        .order_by(ContractInstallment.due_date.asc(), ContractInstallment.id.asc())
        .all()
    )
    installments = []
    net_installment_total = 0.0
    pool = dict(adv_pool)  # tüketilecek kopya
    for inst, plan, c in rows:
        amt = float(inst.amount)
        gid = c.agency_group_id
        avail = pool.get(gid, 0.0)
        if avail >= amt - 0.01:
            pool[gid] = avail - amt   # advance kaydı bu taksidi temsil ediyor → atla
            continue
        net = round(amt - avail, 2)
        if avail > 0:
            pool[gid] = 0.0
        gname = next((g.name for g in groups if g.id == gid), "?")
        installments.append({
            "installment_id": inst.id,
            "date": inst.due_date.isoformat(),
            "amount_eur": net,
            "gross_eur": round(amt, 2),
            "label": f"{gname} kontrat taksiti ({c.code})",
            "contract_code": c.code,
            "conditional": bool(inst.is_conditional),
            "condition_note": inst.condition_note,
            "data_confidence": inst.data_confidence,
            "overdue": inst.due_date <= today,
            "netted_from_advance": net < amt - 0.01,
        })
        net_installment_total += net

    # ── TAM CİRO tahsilat serisi (compute_settlement — avans-mahsuplu) ────────
    from app.services.agency_settlement_service import compute_settlement
    ciro_monthly = []
    ciro_total = 0.0
    try:
        st = compute_settlement(db, today.year, today=today)
        cf_rows = (st.get("cashflow") or {}).get("rows") or []
        # Gelecek sözleşmesel girişler ciro serisinin başından FIFO kırpılır (koruma [3]).
        # YALNIZ CARİ YIL vadeli girişler sayılır — 2027+ avans taksitleri 2027 cirosundan
        # mahsup edilecek, bu yılın serisini kırpmamalı (aşırı-kırpma düzeltmesi 2026-07-17).
        cur_year_net_inst = sum(
            i["amount_eur"] for i in installments
            if int(i["date"][:4]) == today.year)
        trim = adv_pending_total + cur_year_net_inst
        for r in cf_rows:
            m = int(r["month"])
            # yalnız BUGÜN SONRASI aylar projeksiyona girer (cari ay dahil)
            if m < today.month:
                continue
            amount = max(0.0, float(r.get("collection") or 0))
            if trim > 0:
                cut = min(trim, amount)
                amount -= cut
                trim -= cut
            if amount <= 0:
                continue
            last_day = monthrange(today.year, m)[1]
            ciro_monthly.append({
                "month": f"{today.year}-{m:02d}",
                "date": date(today.year, m, last_day).isoformat(),
                "amount_eur": round(amount, 2),
                "label": f"Beklenen acente ciro tahsilatı ({r.get('name', m)})",
            })
            ciro_total += amount
        # Ertesi yıla taşan tahsilat (vade kaydırması: Kas/Ara cirosu Oca-Mar'da tahsil
        # edilir) — tek kalem, ertesi yıl Ocak sonu (kırpmanın kalanı buradan da düşer)
        tail = max(0.0, float((st.get("cashflow") or {}).get("tail") or 0))
        if tail > 0 and trim < tail:
            tail_net = tail - trim
            trim = 0.0
            ciro_monthly.append({
                "month": f"{today.year + 1}-01",
                "date": date(today.year + 1, 1, 31).isoformat(),
                "amount_eur": round(tail_net, 2),
                "label": f"Beklenen acente ciro tahsilatı ({today.year} devri, Oca-Mar {today.year + 1})",
            })
            ciro_total += tail_net
    except Exception:  # settlement üretilemezse taksitler yine döner
        import logging
        logging.getLogger(__name__).error(
            "Ciro projeksiyonu üretilemedi (compute_settlement)", exc_info=True)

    return {
        "installments": installments,
        "ciro_monthly": ciro_monthly,
        "totals": {
            "net_installments_eur": round(net_installment_total, 2),
            "ciro_eur": round(ciro_total, 2),
            "advance_pool_used_eur": round(
                sum(adv_pool.values()) - sum(pool.values()), 2),
        },
    }


def contract_inflow_projections(db: Session, today: Optional[date] = None) -> dict:
    """Ana projeksiyon tüketicileri için kontrat+ciro gelir kalemleri (30sn TTL cache)."""
    today = today or date.today()
    key = today.isoformat()
    now = time.time()
    if _CACHE["val"] is not None and _CACHE["key"] == key and now - _CACHE["t"] < _TTL:
        return _CACHE["val"]
    val = _compute(db, today)
    _CACHE.update(t=now, key=key, val=val)
    return val


def invalidate_cache() -> None:
    _CACHE.update(t=0.0, key=None, val=None)
