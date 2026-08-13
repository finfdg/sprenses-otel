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
[3] TAM CİRO serisi GÜN HASSASİYETLİ üretilir (2026-08-13, kullanıcı kararı): her
    grubun rezervasyon cirosu çıkış tarihi + anlaşma vadesi (term_days) sonrası İLK
    CUMA'ya acente adıyla yazılır; Sedna 340 kalan avans bakiyesi grup içi vade-FIFO
    mahsup edilir, GELECEK sözleşmesel girişler (pending advances + cari yıl net
    taksitleri) GRUP BAZLI vade-FIFO kırpılır (grupsuz avanslar global) — aynı para
    hem "avans girişi" hem "ciro tahsilatı" olarak iki kez sayılmaz.
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
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.models.advance import Advance
from app.models.agency_group import AgencyGroup
from app.models.contract import (
    INSTALLMENT_PENDING, PLAN_TYPE_GUARANTEE_CHECK, AgencyContract,
    ContractInstallment, ContractPaymentPlan,
)
from app.models.reservation import Reservation
from app.utils.vendor_fifo import _next_friday

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
    inst_net_by_gid: dict = defaultdict(float)  # cari yıl net taksit → grup bazlı ciro kırpması
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
        if inst.due_date.year == today.year and gid is not None:
            inst_net_by_gid[gid] += net
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

    # ── TAM CİRO tahsilat serisi — GÜN HASSASİYETLİ, ACENTE BAZLI (2026-08-13) ──
    # Kullanıcı kararı: aylık ay-sonu toplu kalem yerine her grubun cirosu ÇIKIŞ
    # (fatura kesim) tarihi + anlaşma vadesi (agency_groups.term_days) sonrası İLK
    # CUMA'ya (cariler `_next_friday` konvansiyonu — ör. PEGAS 21g: çıkış+21 gün
    # sonrası ilk Cuma) ACENTE ADIYLA yazılır. Avans mahsubu (Sedna 340 kalan
    # bakiyesi = received − consumed, compute_receivables grup satırları) grup içi
    # vade-FIFO düşülür; sözleşmesel girişlerin çift-sayım kırpması (koruma [3],
    # pending advances + CARİ YIL net taksitleri) tarih-FIFO olarak AYNEN uygulanır.
    # Kas/Ara cirosunun ertesi yıla taşan tahsilatı doğal olarak Ocak Cumalarına düşer.
    from app.services.agency_settlement_service import (
        _OTHER_ID, _agency_group_maps)
    from app.services.agency_settlement_service import _norm as _agency_norm
    from app.services.receivable_service import _latest_rates, compute_receivables
    ciro_items = []
    ciro_total = 0.0
    try:
        gmeta, member_to_gid = _agency_group_maps(db)
        # (grup, vade-Cuma) → EUR ciro
        agg: dict = defaultdict(float)
        res_rows = (
            db.query(
                Reservation.agency, Reservation.checkout_date,
                func.coalesce(func.sum(Reservation.eur_total), 0))
            .filter(extract("year", Reservation.checkout_date) == today.year)
            .group_by(Reservation.agency, Reservation.checkout_date)
            .all()
        )
        for agency, co_date, eur in res_rows:
            amt = float(eur or 0)
            if amt <= 0 or co_date is None:
                continue
            gid = member_to_gid.get(_agency_norm(agency), _OTHER_ID)
            gm = gmeta.get(gid) or {}
            term = int(gm.get("term_days") or 30)
            raw = co_date + timedelta(days=term)
            if gm.get("payment_alignment") == "month_end":
                # ör. Nordic: vade hangi aya düşerse o ayın SON GÜNÜ öder (Cuma değil)
                due = date(raw.year, raw.month, monthrange(raw.year, raw.month)[1])
            else:
                due = _next_friday(raw)
            if due <= today:
                continue  # vadesi geçmiş tahsilat projeksiyona girmez (hakediş alanı)
            agg[(gid, due)] += amt
        # Grup başına kalan (mahsup edilmemiş) avans havuzu — peşin ödenen ciro
        # vadede tekrar tahsil edilmez; grubun en erken vadelerinden FIFO düşülür.
        rates = _latest_rates(db)
        eur_rate = float(rates.get("EUR", 0.0) or 0.0)
        adv_left: dict = defaultdict(float)
        if eur_rate > 0:
            rec = compute_receivables(db, today)
            for f in rec.get("firms", []):
                code = str(f.get("code", ""))
                if not (f.get("is_group") and code.startswith("group-")):
                    continue
                try:
                    fgid = int(code.split("-", 1)[1])
                except (ValueError, IndexError):
                    continue
                left = (float(f.get("advance_received_tl", 0) or 0)
                        - float(f.get("advance_consumed_tl", 0) or 0)) / eur_rate
                if left > 0:
                    adv_left[fgid] = round(left, 2)
        # Çift-sayım kırpması (koruma [3]) — GRUP BAZLI (2026-08-13): bir grubun
        # sözleşmesel girişleri (pending advances + CARİ YIL net taksitleri) yalnız
        # O GRUBUN ciro kalemlerinden vade-FIFO düşülür — Nordic'in avansı Pegas'ın
        # cirosunu silmez. Gruba eşlenemeyen pending advances eski davranışla tüm
        # seriden tarih-FIFO düşülür. 2027+ taksitleri 2027 cirosundan mahsup edilecek.
        group_trim: dict = defaultdict(float)
        for tgid, amt_p in adv_pool.items():
            group_trim[tgid] += amt_p
        for tgid, amt_i in inst_net_by_gid.items():
            group_trim[tgid] += amt_i
        global_trim = round(adv_pending_total - sum(adv_pool.values()), 2)  # grupsuz avanslar
        for (gid, due), amount in sorted(agg.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            avail = adv_left.get(gid, 0.0)
            if avail > 0:
                cut = min(avail, amount)
                amount -= cut
                adv_left[gid] = round(avail - cut, 2)
            if amount <= 0.01:
                continue
            gt = group_trim.get(gid, 0.0)
            if gt > 0:
                cut = min(gt, amount)
                amount -= cut
                group_trim[gid] = gt - cut
            if amount <= 0.01:
                continue
            if global_trim > 0:
                cut = min(global_trim, amount)
                amount -= cut
                global_trim -= cut
            if amount <= 0.01:
                continue
            gname = (gmeta.get(gid) or {}).get("name") or "Diğer"
            ciro_items.append({
                "key": f"{gid}:{due.isoformat()}",
                "month": f"{due.year}-{due.month:02d}",
                "date": due.isoformat(),
                "amount_eur": round(amount, 2),
                "label": f"Beklenen ciro tahsilatı ({gname})",
                "agency": gname,
            })
            ciro_total += amount
    except Exception:  # ciro serisi üretilemezse taksitler yine döner
        import logging
        logging.getLogger(__name__).error(
            "Ciro projeksiyonu üretilemedi (gün bazlı seri)", exc_info=True)

    return {
        "installments": installments,
        "ciro_items": ciro_items,
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
