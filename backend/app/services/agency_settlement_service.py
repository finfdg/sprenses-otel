"""Acente Mahsup & Nakit Akım projeksiyon servisi (HTTP'siz, salt-okuma).

"Rezervasyon → Fatura → Avans Mahsubu → Vadeli Tahsilat" zincirinin acente bazlı
EUR projeksiyonu. Tasarımın (Sprenses Tasarımlar/"Acente Mahsup & Nakit Akım")
hesap modeli KORUNUR; yalnız GİRDİLER gerçek veriye bağlanır:

  - Ciro omurgası: `reservations.eur_total` — çıkış (checkout) ayında tanınır
    ("fatura konaklama tamamlanınca kesilir"). Geçmiş aylar GERÇEKLEŞEN, gelecek
    aylar MEVCUT İLERİ REZERVASYON.
  - Acenteler: `agency_groups` (PMS üye adları). Grup dışı acenteler → "Diğer".
  - Vade + kickback: `agency_groups.term_days` / `kickback_percent` (konfig).
  - Avanslar: `receivable_service.compute_receivables` grup satırlarından (340
    'Alınan Avanslar'), güncel TCMB kuruyla EUR'ya çevrilir.
  - Yıl sonu ciro hedefi + açılış nakit: senaryo girdisi (parametre).

Hak Ediş modülünden (finance.hakedis — TL, GERÇEK fatura yaşlandırması) farkı:
burası İLERİ PROJEKSİYON; kickback ve hedef senaryo katmanı ekler.
"""
from datetime import date
from typing import Optional

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.models.agency_group import DEFAULT_AGENCY_TERM_DAYS, AgencyGroup
from app.models.reservation import Reservation
from app.services.receivable_service import _latest_rates, compute_receivables

# Acente satır/nokta renkleri (lacivert/altın tema ile uyumlu, deterministik sıra)
_PALETTE = ["#bd9a45", "#2c4269", "#6aa583", "#c67a2e", "#8496b3", "#a9862f",
            "#4f7d64", "#7a5c9e", "#b5533a", "#3a5a82", "#d8b24a", "#5a6b8c"]

_MONTHS_SHORT = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
                 "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]

_OTHER_ID = 0          # "Diğer" (grup dışı acenteler) sözde grup kimliği
_OTHER_NAME = "Diğer"


def _norm(s: Optional[str]) -> str:
    """Üye/acente adı eşleşmesi için: kenar boşluğu kırp + büyük harf.

    İç boşluk KORUNUR (kullanıcı 'BYEBYE  D' çift-boşluğunu bilinçli farklı gruba
    atamış olabilir → daraltma yanlış gruba yazardı)."""
    return (s or "").strip().upper()


def _round2(v) -> float:
    return round(float(v or 0), 2)


def compute_settlement(
    db: Session,
    year: int,
    year_target: Optional[float] = None,
    opening_cash: float = 0.0,
    today: Optional[date] = None,
) -> dict:
    """Acente Mahsup & Nakit Akım projeksiyonunu üretir (5 sekmelik payload).

    year_target None ise gerçek ciro toplamına eşitlenir (forecast = 0).
    """
    today = today or date.today()

    # ── Acente grupları + konfig ─────────────────────────────
    groups = db.query(AgencyGroup).order_by(AgencyGroup.name).all()
    gmeta: dict = {}                 # gid → {name, term_days, kickback_pct, color}
    member_to_gid: dict = {}         # NORM(üye adı) → gid
    for i, g in enumerate(groups):
        gmeta[g.id] = {
            "id": g.id, "name": g.name,
            "term_days": int(g.term_days if g.term_days is not None else DEFAULT_AGENCY_TERM_DAYS),
            "kickback_pct": float(g.kickback_percent or 0),
            "color": _PALETTE[i % len(_PALETTE)],
        }
        for m in (g.members or []):
            member_to_gid[_norm(m)] = g.id
    # "Diğer" sözde grup (grup dışı acenteler)
    gmeta[_OTHER_ID] = {"id": _OTHER_ID, "name": _OTHER_NAME,
                        "term_days": DEFAULT_AGENCY_TERM_DAYS, "kickback_pct": 0.0,
                        "color": "#9aa3b2"}

    # ── Rezervasyon cirosu: (grup, çıkış ayı) EUR ────────────
    # eur_total çıkış (checkout) ayında tanınır. rev[gid][month0-11]
    rev: dict = {gid: [0.0] * 12 for gid in gmeta}
    rows = (
        db.query(
            Reservation.agency,
            extract("month", Reservation.checkout_date).label("m"),
            func.coalesce(func.sum(Reservation.eur_total), 0),
        )
        .filter(extract("year", Reservation.checkout_date) == year)
        .group_by(Reservation.agency, "m")
        .all()
    )
    for agency, m, eur in rows:
        gid = member_to_gid.get(_norm(agency), _OTHER_ID)
        mi = int(m) - 1
        if 0 <= mi < 12:
            rev[gid][mi] += float(eur or 0)

    # ── Gerçekleşen / ileri ay ayrımı ────────────────────────
    # Ay (year, month) bugünden küçükse GERÇEKLEŞEN (çıkış tamamlanmış).
    def _is_realized(m0: int) -> bool:
        return (year, m0 + 1) < (today.year, today.month)

    realized_months = [m for m in range(12) if _is_realized(m)]
    forward_months = [m for m in range(12) if not _is_realized(m)]

    booked_total = [sum(rev[gid][m] for gid in gmeta) for m in range(12)]
    real_total = round(sum(booked_total), 2)
    realized_sum = round(sum(booked_total[m] for m in realized_months), 2)
    forward_booked_sum = round(sum(booked_total[m] for m in forward_months), 2)

    # ── Hedef senaryo → ek tahmin dağıtımı ───────────────────
    target = float(year_target) if year_target is not None else real_total
    grand_total = round(max(target, real_total), 2)
    additional = round(max(0.0, grand_total - real_total), 2)

    # Ek tahmini ileri aylara (grup×ay hücresi) mevcut ileri rezervasyon ağırlığıyla dağıt;
    # ileri rezervasyon yoksa ileri aylara eşit paylaştır.
    extra: dict = {gid: [0.0] * 12 for gid in gmeta}
    if additional > 0:
        fwd_cells = [(gid, m) for gid in gmeta for m in forward_months]
        if forward_booked_sum > 0:
            for gid, m in fwd_cells:
                w = rev[gid][m] / forward_booked_sum
                extra[gid][m] = additional * w
        elif fwd_cells:
            share = additional / len(fwd_cells)
            for gid, m in fwd_cells:
                extra[gid][m] = share

    proj: dict = {gid: [rev[gid][m] + extra[gid][m] for m in range(12)] for gid in gmeta}
    monthly_total = [round(sum(proj[gid][m] for gid in gmeta), 2) for m in range(12)]
    group_year: dict = {gid: round(sum(proj[gid]), 2) for gid in gmeta}

    # ── Avanslar (gerçek, EUR) — compute_receivables grup satırlarından ──
    rates = _latest_rates(db)
    eur_rate = rates.get("EUR", 0.0) or 0.0

    def _to_eur(tl: float) -> float:
        return round(tl / eur_rate, 2) if eur_rate > 0 else 0.0

    adv_received: dict = {gid: 0.0 for gid in gmeta}   # EUR
    adv_consumed: dict = {gid: 0.0 for gid in gmeta}   # EUR (faturayla mahsup)
    rec = compute_receivables(db, today)
    for f in rec.get("firms", []):
        if f.get("is_group") and str(f.get("code", "")).startswith("group-"):
            try:
                gid = int(f["code"].split("-", 1)[1])
            except (ValueError, IndexError):
                gid = _OTHER_ID
            if gid not in gmeta:
                gid = _OTHER_ID
        else:
            gid = _OTHER_ID  # gruba bağlı olmayan muhasebe firması → Diğer
        adv_received[gid] += _to_eur(f.get("advance_received_tl", 0))
        adv_consumed[gid] += _to_eur(f.get("advance_consumed_tl", 0))
    adv_received = {k: round(v, 2) for k, v in adv_received.items()}
    adv_consumed = {k: round(v, 2) for k, v in adv_consumed.items()}

    # ── Acente tablosu (tab 1) ───────────────────────────────
    agencies = []
    for gid in gmeta:
        revenue = group_year[gid]
        received = adv_received[gid]
        consumed = adv_consumed[gid]
        if revenue <= 0 and received <= 0:
            continue  # ne cirosu ne avansı olan grubu gösterme
        kb = round(revenue * gmeta[gid]["kickback_pct"] / 100.0, 2)
        agencies.append({
            "id": gid,
            "name": gmeta[gid]["name"],
            "color": gmeta[gid]["color"],
            "revenue": revenue,
            "share_pct": round(revenue / grand_total * 100, 1) if grand_total > 0 else 0.0,
            "term_days": gmeta[gid]["term_days"],
            "kickback_pct": gmeta[gid]["kickback_pct"],
            "kickback": kb,
            "advance_received": received,
            "advance_applied": consumed,
            "advance_remaining": round(max(0.0, received - consumed), 2),
        })
    agencies.sort(key=lambda a: -a["revenue"])

    advance_total = round(sum(adv_received.values()), 2)
    advance_applied_total = round(sum(adv_consumed.values()), 2)
    advance_remaining_total = round(max(0.0, advance_total - advance_applied_total), 2)
    kickback_total = round(sum(a["kickback"] for a in agencies), 2)

    # ── Aylık ciro (tab 3) ───────────────────────────────────
    monthly = []
    for m in range(12):
        booked = round(booked_total[m], 2)
        total = monthly_total[m]
        monthly.append({
            "month": m + 1,
            "name": _MONTHS_SHORT[m],
            "booked": booked,
            "extra": round(max(0.0, total - booked), 2),
            "total": total,
            "realized": m in realized_months,
        })

    # ── Avans mahsup matrisi (grup × ay) ─────────────────────
    # GERÇEKLEŞEN aylardaki faturalar GERÇEK 'consumed' (faturayla kapatılmış) avansla,
    # İLERİ aylardaki faturalar 'remaining' (kalan/peşin) avansla FIFO (erken ay önce)
    # mahsup edilir. Böylece mahsup edilen kısım vadede TEKRAR tahsil edilmez
    # (avans zaten nakde alınmış, açılış bakiyesine dahil).
    mahsup: dict = {gid: [0.0] * 12 for gid in gmeta}
    for gid in gmeta:
        left_past = adv_consumed[gid]
        for m in realized_months:  # sıralı (range 0..11 kaynaklı → artan)
            ap = min(left_past, proj[gid][m])
            left_past -= ap
            mahsup[gid][m] = ap
        left_fwd = round(max(0.0, adv_received[gid] - adv_consumed[gid]), 2)
        for m in forward_months:
            ap = min(left_fwd, proj[gid][m])
            left_fwd -= ap
            mahsup[gid][m] = ap
    mahsup_total = round(sum(mahsup[gid][m] for gid in gmeta for m in range(12)), 2)

    # ── Nakit akım projeksiyonu (tab 5) ──────────────────────
    # Grup cirosu, vadesine göre ileri aya kaydırılarak tahsilat ayına yazılır
    # (mahsup edilen kısım hariç).
    coll = [0.0] * 15   # 0-11 = yıl ayları; 12-14 = ertesi yıla taşan tahsilat
    for gid in gmeta:
        off = max(0, round(gmeta[gid]["term_days"] / 30.0))
        for m in range(12):
            slot = m + off
            if slot < len(coll):
                coll[slot] += proj[gid][m] - mahsup[gid][m]

    # Açılıştan itibaren kümülatif bakiye (Ara ayında kickback düşülür)
    balances = [round(opening_cash, 2)]
    b = opening_cash
    for t in range(12):
        b += coll[t] - (kickback_total if t == 11 else 0.0)
        balances.append(round(b, 2))

    # Projeksiyon penceresi: cari yılsa bu aydan Aralık'a; gelecek yıl tümü; geçmiş yıl tümü
    if year > today.year:
        start_m = 0
    elif year < today.year:
        start_m = 0
    else:
        start_m = today.month - 1

    cf_rows = []
    for t in range(start_m, 12):
        kb = kickback_total if t == 11 else 0.0
        net = coll[t] - kb
        cf_rows.append({
            "month": t + 1,
            "name": _MONTHS_SHORT[t],
            "collection": round(coll[t], 2),
            "kickback": round(kb, 2),
            "net": round(net, 2),
            "cumulative": balances[t + 1],
        })
    tail = round(coll[12] + coll[13] + coll[14], 2)
    in_total = round(sum(coll[start_m:12]), 2)

    # Runway grafiği için pencere bakiyeleri (açılış + start_m..Ara)
    chart_balances = [balances[0]] + [balances[t + 1] for t in range(start_m, 12)]
    chart_labels = ["Açılış"] + [_MONTHS_SHORT[t] for t in range(start_m, 12)]
    min_val = min(chart_balances) if chart_balances else 0.0
    min_idx = chart_balances.index(min_val) if chart_balances else 0

    # ── Projeksiyon faturaları (tab 4) ───────────────────────
    # Her grup × ciro-lu ay için bir satır: tutar = o ayın grup cirosu,
    # mahsup = avans mahsup matrisinden, net = tutar − mahsup.
    invoices = []
    for gid in gmeta:
        off = max(0, round(gmeta[gid]["term_days"] / 30.0))
        for m in range(12):
            amt = round(proj[gid][m], 2)
            if amt <= 0.01:
                continue
            mah = round(mahsup[gid][m], 2)
            net = round(amt - mah, 2)
            due_m = m + off
            future = not _is_realized(m)
            if net <= 0.01:
                status = "mahsup"       # avansla kapandı
            elif future:
                status = "planned"      # ileri konaklama
            else:
                status = "collected"    # geçmiş konaklama → tahsil varsayılır
            invoices.append({
                "agency_id": gid,
                "agency": gmeta[gid]["name"],
                "color": gmeta[gid]["color"],
                "month": m + 1,
                "month_name": _MONTHS_SHORT[m],
                "due_month": (due_m % 12) + 1,
                "due_name": _MONTHS_SHORT[due_m % 12],
                "amount": amt,
                "mahsup": mah,
                "net": net,
                "status": status,
            })
    invoices.sort(key=lambda x: (x["month"], -x["amount"]))
    inv_amount_total = round(sum(x["amount"] for x in invoices), 2)
    inv_mahsup_total = round(sum(x["mahsup"] for x in invoices), 2)
    inv_net_total = round(sum(x["net"] for x in invoices), 2)

    return {
        "year": year,
        "currency": "EUR",
        "today": today.isoformat(),
        "eur_rate": round(eur_rate, 4),
        "scenario": {"target": round(target, 2), "opening_cash": round(opening_cash, 2)},
        "kpi": {
            "target": round(target, 2),
            "grand_total": grand_total,
            "realized": realized_sum,
            "forecast": round(grand_total - realized_sum, 2),
            "advance_received": advance_total,
            "advance_applied": advance_applied_total,
            "advance_remaining": advance_remaining_total,
            "kickback_total": kickback_total,
            "realized_pct": round(realized_sum / grand_total * 100, 1) if grand_total > 0 else 0.0,
            "forecast_pct": round((grand_total - realized_sum) / grand_total * 100, 1) if grand_total > 0 else 0.0,
        },
        "funnel": {
            "revenue": grand_total,
            "invoiced": grand_total,
            "advance_offset": mahsup_total,
            "net_collection": round(grand_total - mahsup_total, 2),
            "kickback": kickback_total,
        },
        "agencies": agencies,
        "monthly": monthly,
        "monthly_meta": {
            "forward_booked": forward_booked_sum,
            "additional_forecast": additional,
            "realized_sum": realized_sum,
            "grand_total": grand_total,
        },
        "advances": {
            "total_received": advance_total,
            "total_applied": advance_applied_total,
            "total_remaining": advance_remaining_total,
            "rows": [
                {
                    "agency_id": a["id"], "agency": a["name"], "color": a["color"],
                    "received": a["advance_received"], "applied": a["advance_applied"],
                    "remaining": a["advance_remaining"],
                    "pct": round(a["advance_applied"] / a["advance_received"] * 100, 0)
                    if a["advance_received"] > 0 else 0.0,
                }
                for a in agencies if a["advance_received"] > 0
            ],
        },
        "invoices": {
            "total_amount": inv_amount_total,
            "total_mahsup": inv_mahsup_total,
            "total_net": inv_net_total,
            "rows": invoices,
        },
        "cashflow": {
            "opening": round(opening_cash, 2),
            "closing": balances[12],
            "in_total": in_total,
            "tail": tail,
            "kickback_total": kickback_total,
            "rows": cf_rows,
            "chart": {
                "balances": chart_balances,
                "labels": chart_labels,
                "min_value": round(min_val, 2),
                "min_index": min_idx,
                "min_label": chart_labels[min_idx] if chart_labels else "",
            },
        },
    }
