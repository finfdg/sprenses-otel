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
    hem "avans girişi" hem "ciro tahsilatı" olarak iki kez sayılmaz. HAM vadesi geçmiş
    rezervasyon cirosu seriye girmez; yerine GERÇEK vadesi geçmiş alacak (hakediş
    fatura FIFO'su — tahsilat+avans netlenmiş `overdue_tl`) grubun bir sonraki ödeme
    gününe ayrı "Vadesi geçmiş hakediş tahsilatı" kalemi olarak yazılır (2026-08-13).
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
from app.models.agency_group import (
    PAYMENT_ALIGN_CHECKIN,
    PAYMENT_ALIGN_DAY_PREFIX,
    PAYMENT_ALIGN_FRIDAY,
    PAYMENT_ALIGN_MONTH_END,
    AgencyGroup,
)
from app.models.contract import (
    INSTALLMENT_PENDING,
    PLAN_TYPE_GUARANTEE_CHECK,
    AgencyContract,
    ContractDeduction,
    ContractInstallment,
    ContractPaymentPlan,
)
from app.models.reservation import Reservation
from app.services.vendor_fifo import _next_friday

# 30 sn TTL süreç-içi cache (cc_projection/settlement desenleriyle tutarlı)
_CACHE: dict = {"t": 0.0, "key": None, "val": None}
_TTL = 30.0


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _align_due(align: str, raw: date) -> date:
    """Ham vade gününü acentenin ödeme günü konvansiyonuna hizala.

    friday (varsayılan): sonraki ilk Cuma · month_end: ayın son günü ·
    day_N: ayın N'i (ham vade N'i geçtiyse ertesi ayın N'i).
    """
    if align == PAYMENT_ALIGN_MONTH_END:
        return date(raw.year, raw.month, monthrange(raw.year, raw.month)[1])
    if align.startswith(PAYMENT_ALIGN_DAY_PREFIX):
        try:
            pday = int(align[len(PAYMENT_ALIGN_DAY_PREFIX):])
        except ValueError:
            pday = 0
        if pday >= 1:
            y, m = raw.year, raw.month
            if raw.day > pday:
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            return date(y, m, min(pday, monthrange(y, m)[1]))
    return _next_friday(raw)


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
    from app.services.agency_settlement_service import _OTHER_ID, _agency_group_maps
    from app.services.agency_settlement_service import _norm as _agency_norm
    from app.services.receivable_service import _latest_rates, compute_receivables
    ciro_items = []
    ciro_total = 0.0
    try:
        gmeta, member_to_gid = _agency_group_maps(db)
        # ── YAKIN PENCERE = GERÇEK FATURA EVRENİ (2026-08-13 v2, kullanıcı denetimi) ──
        # Bir grubun BİR SONRAKİ ödeme gününe kadar vadesi dolan/dolmuş alacağı
        # rezervasyon tahmini DEĞİL, hakediş fatura FIFO'sundan okunur
        # (`firm_open_invoices` — gerçek fatura vadesi, tahsilat+avans netlenmiş):
        #   · vadesi geçmiş kalan → "Vadesi geçmiş hakediş tahsilatı"
        #   · bugün→sonraki-ödeme-günü vadeli kalan → "Fatura vadeli hakediş tahsilatı"
        # Rezervasyon serisi o pencereyi ATLAR (sınır = next_pay; iki evren çakışmaz).
        # Faturası olmayan gruplar (Münferit/Diğer vb.) eski davranışla rezervasyondan
        # beslenmeye devam eder (ham vadesi geçmişleri yine hariç).
        rates = _latest_rates(db)
        eur_rate = float(rates.get("EUR", 0.0) or 0.0)
        adv_left: dict = defaultdict(float)
        inv_window: dict = {}       # gid → ("due", next_pay) | ("month", ay_başı) — rezervasyon atlama sınırı
        inv_near: dict = {}         # gid → {"overdue": €, "due": €, "next_pay": date}
        # Fatura-başı % kesinti (contract_deductions.applies='per_invoice' — ör. Nordic
        # %2 rehber+web; pro forma 260731111316 ile kanıtlandı: brüt 74.908 − %2 = 73.410
        # ödendi). Aktif kontratlardan grup başına en yüksek yüzde alınır; hem fatura
        # hem rezervasyon ciro kalemlerine NET uygulanır.
        ded_pct: dict = {}
        for ded_gid, ded_p in (
            db.query(AgencyContract.agency_group_id, func.max(ContractDeduction.percent))
            .join(ContractDeduction, ContractDeduction.contract_id == AgencyContract.id)
            .filter(AgencyContract.status == "active",
                    ContractDeduction.applies == "per_invoice",
                    ContractDeduction.percent.isnot(None))
            .group_by(AgencyContract.agency_group_id).all()
        ):
            if ded_gid is not None and ded_p:
                ded_pct[ded_gid] = float(ded_p)
        month_start = date(today.year, today.month, 1)
        if eur_rate > 0:
            from app.services.receivable_service import firm_open_invoices
            rec = compute_receivables(db, today)
            inv_gids = set()
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
                if float(f.get("invoiced_tl", 0) or 0) > 0 and fgid in gmeta:
                    inv_gids.add(fgid)
            for fgid in inv_gids:
                _align = gmeta[fgid].get("payment_alignment") or PAYMENT_ALIGN_FRIDAY
                next_pay = _align_due(_align, today + timedelta(days=1))
                # AYLIK ödeyen acente (day_N/month_end) partiyi FATURA AYINA göre kurar
                # (self-billing kanıtı: NLTG bir ayın çıkışlarını izleyen ay sonunda tek
                # pro formada öder) → önceki ay(lar) kesimli TÜM açık faturalar bu
                # partiye girer (vadesi ödeme gününü birkaç gün aşsa bile — SPA...1644).
                # Haftalık (friday) ve girişte-ödeyen (checkin) acentede pencere vade bazlı.
                monthly_batch = (_align == PAYMENT_ALIGN_MONTH_END
                                 or _align.startswith(PAYMENT_ALIGN_DAY_PREFIX))
                inv_window[fgid] = ("month", month_start) if monthly_batch else ("due", next_pay)
                ovd = due_amt = 0.0
                for row in firm_open_invoices(db, f"group-{fgid}", today):
                    try:
                        ddt = date.fromisoformat(row["due_date"])
                        idt = date.fromisoformat(row["invoice_date"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if monthly_batch:
                        if idt >= month_start:
                            continue  # cari ay kesimliler bir sonraki partinin konusu
                    elif ddt > next_pay:
                        continue  # sonraki ödemelerin konusu → rezervasyon serisi kapsar
                    if (row.get("currency") or "").upper() == "EUR":
                        val = float(row.get("remaining") or 0)  # native — kur sapmasız
                    else:
                        val = float(row.get("remaining_tl") or 0) / eur_rate
                    if not monthly_batch and ddt < today:
                        # yalnız vade-bazlı (friday) acentede gecikme ayrımı anlamlı;
                        # aylık partide fatura-başı vade sözleşmesel değil (self-billing)
                        # → tek kalemde birleşir, gün geçtikçe satırlar arası kayma olmaz
                        ovd += val
                    else:
                        due_amt += val
                if ovd > 0.5 or due_amt > 0.5:
                    inv_near[fgid] = {"overdue": round(ovd, 2), "due": round(due_amt, 2),
                                      "next_pay": next_pay}

        # ── Rezervasyon bazlı ciro serisi (fatura penceresinin ÖTESİ) ──
        agg: dict = defaultdict(float)
        res_rows = (
            db.query(
                Reservation.agency, Reservation.checkin_date,
                Reservation.checkout_date,
                func.coalesce(func.sum(Reservation.eur_total), 0))
            .filter(extract("year", Reservation.checkout_date) == today.year)
            .group_by(Reservation.agency, Reservation.checkin_date,
                      Reservation.checkout_date)
            .all()
        )
        for agency, ci_date, co_date, eur in res_rows:
            amt = float(eur or 0)
            if amt <= 0 or co_date is None:
                continue
            gid = member_to_gid.get(_agency_norm(agency), _OTHER_ID)
            gm = gmeta.get(gid) or {}
            align = gm.get("payment_alignment") or PAYMENT_ALIGN_FRIDAY
            if align == PAYMENT_ALIGN_CHECKIN:
                # GİRİŞTE ödeyen acente (Expedia POS, Münferit havale/POS —
                # kullanıcı 2026-08-14): tahsilat GİRİŞ GÜNÜNE günlük yazılır;
                # girişi geçmiş misafir zaten ödedi (POS/banka gerçekleşmesi).
                if ci_date is None or ci_date <= today:
                    continue
                agg[(gid, ci_date)] += amt
                continue
            term = int(gm.get("term_days") or 30)
            raw = co_date + timedelta(days=term)
            if raw <= today:
                # HAM vadesi geçmiş ciro projeksiyona GİRMEZ: ödenmiş kısmı zaten
                # tahsil edildi, ödenmemiş kısmı fatura evreninin "vadesi geçmiş"
                # kaleminde — çift sayım yok.
                continue
            if gid in inv_window:
                mode, bound = inv_window[gid]
                if mode == "month" and co_date < bound:
                    continue  # önceki ay çıkışları fatura partisinden gelir
                if mode == "due" and raw <= bound:
                    continue  # bu pencere gerçek fatura kalemlerinden gelir
            due = _align_due(align, raw)
            agg[(gid, due)] += amt
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
        # Ciro + fatura-penceresi kalemleri tek seride, tarih sırasıyla işlenir.
        # adv_left (= grup 340 received − consumed, yani HENÜZ MAHSUP EDİLMEMİŞ avans)
        # TÜM kalem türlerine uygulanır (2026-08-14, Odeon vakası — kullanıcı: "avans
        # alındı, hâlâ borcumuz var; nakit tahsilat beklenmez"): grubun açık faturası
        # vadesi geçse bile karşılığı avanstan mahsup edilecektir. FIFO'nun zaten
        # tükettiği avans 'consumed' içinde olduğundan adv_left'te YOKTUR → çift
        # netleme olmaz. Koruma-[3] kırpmaları (pending advance kaydı) ayrıca uygulanır.
        entries = [(due, gid, "ciro", amount)
                   for (gid, due), amount in agg.items()]
        for gid, near in inv_near.items():
            if near["overdue"] > 0.5:
                entries.append((near["next_pay"], gid, "overdue", near["overdue"]))
            if near["due"] > 0.5:
                entries.append((near["next_pay"], gid, "invoice_due", near["due"]))
        for due, gid, kind, amount in sorted(entries, key=lambda e: (e[0], e[1], e[2])):
            pct = ded_pct.get(gid)
            if pct:
                amount *= (1 - pct / 100.0)  # fatura-başı kesinti — net nakit beklentisi
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
            label = {
                "overdue": f"Vadesi geçmiş hakediş tahsilatı ({gname})",
                "invoice_due": f"Fatura vadeli hakediş tahsilatı ({gname})",
            }.get(kind, f"Beklenen ciro tahsilatı ({gname})")
            ciro_items.append({
                "key": f"{gid}:{kind}:{due.isoformat()}",
                "month": f"{due.year}-{due.month:02d}",
                "date": due.isoformat(),
                "amount_eur": round(amount, 2),
                "label": label,
                "agency": gname,
                "kind": kind,
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
