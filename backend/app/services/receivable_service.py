"""Hak ediş takibi domain servisi (HTTP'siz).

Rezervasyon → konaklama → çıkışta kesilen fatura = HAK EDİŞ (120.* alacak).
Firmalar anlaşma gereği 30/45 gün içinde ödemeli. Sedna'da vade YOK
(Invoice.DueDate=InvoiceDate, Agency.Days=0 — 2026-07-02 keşfi) → vadeler yerelde
(`receivable_terms`) tutulur; tanımsız firma DEFAULT_TERM_DAYS (30) sayılır.

Veri kaynağı: `sales_invoices`/`sales_collections` (Sedna 120 muhasebe import'u) +
`sales_invoice_service._compute_cached` FIFO'su (hangi fatura açık/kısmi/ödendi).
Bu servis üstüne yalnız VADE katmanı ekler: vade = fatura_tarihi + vade_gunu →
gecikme günü → yaşlandırma kovaları.

`upsert_term` router + onay executor'ının ORTAK çağrısıdır (D1-2 deseni).
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.agency_code_map import AgencyCodeMap
from app.models.agency_code_override import AgencyCodeOverride
from app.models.agency_group import AgencyGroup
from app.models.exchange_rate import ExchangeRate
from app.models.receivable_term import DEFAULT_TERM_DAYS, ReceivableTerm
from app.models.sales_invoice import SalesAdvance, SalesCollection, SalesInvoice
from app.services.sales_invoice_service import _compute_cached, _f
from app.utils.text_match import _norm_tokens

# Yaşlandırma kovaları (gecikme gününe göre)
BUCKET_NOT_DUE = "not_due"        # vadesi gelmemiş
BUCKET_1_7 = "overdue_1_7"        # 1-7 gün gecikmiş
BUCKET_8_30 = "overdue_8_30"      # 8-30 gün gecikmiş
BUCKET_30_PLUS = "overdue_30_plus"  # 30+ gün gecikmiş


def _bucket(overdue_days: int) -> str:
    if overdue_days <= 0:
        return BUCKET_NOT_DUE
    if overdue_days <= 7:
        return BUCKET_1_7
    if overdue_days <= 30:
        return BUCKET_8_30
    return BUCKET_30_PLUS


# ─── Vade tanımı (router + executor ORTAK) ───────────────

def upsert_term(db: Session, customer_code: str, term_days: int,
                notes: Optional[str] = None) -> ReceivableTerm:
    """Firma vade tanımı upsert (customer_code doğal anahtar). Commit ETMEZ (çağıran eder)."""
    code = (customer_code or "").strip()
    if not code:
        raise ValueError("Cari kodu boş olamaz.")
    if term_days < 0 or term_days > 365:
        raise ValueError("Vade 0-365 gün aralığında olmalıdır.")
    term = db.query(ReceivableTerm).filter(ReceivableTerm.customer_code == code).first()
    if term:
        term.term_days = term_days
        if notes is not None:
            term.notes = notes
    else:
        term = ReceivableTerm(customer_code=code, term_days=term_days, notes=notes)
        db.add(term)
    db.flush()
    return term


def get_terms_map(db: Session) -> dict:
    """customer_code → term_days sözlüğü (yalnız tanımlı firmalar)."""
    return {t.customer_code: t.term_days
            for t in db.query(ReceivableTerm).all()}


# ─── Yardımcılar: kur, grup, avans ───────────────────────

def _latest_rates(db: Session) -> dict:
    """currency_code → TL kuru (son tarihli TCMB forex_buying / unit). TL=1."""
    rates = {"TL": 1.0, "TRY": 1.0}
    for r in (db.query(ExchangeRate)
              .order_by(ExchangeRate.currency_code, ExchangeRate.date.desc()).all()):
        if r.currency_code not in rates:
            unit = float(r.unit or 1) or 1
            sell = _f(r.forex_buying)
            if sell > 0:
                rates[r.currency_code] = sell / unit
    return rates


def _group_map(db: Session) -> dict:
    """customer_code (120.*) → {'id', 'name'} grup eşlemesi.

    Zincir: agency_groups.members (PMS acente adları) → agency_code_map (PMS adı → 120 kodu,
    Sedna PMS Agency/AgencyAccCode köprüsü, sales import'unda tazelenir) → firma kodu.
    İsimle doğrudan eşleme YAPILMAZ (PMS adları ↔ muhasebe adları farklı evren — 2026-07-02 keşfi:
    'CORAL PL' ↔ 'CORAL SEYAHAT A.Ş.' token kesişmez; köprü tek güvenilir yol).
    """
    name_to_code = {m.pms_name.strip().upper(): m.acc_code
                    for m in db.query(AgencyCodeMap).all()}
    # Yerel düzeltme katmanı Sedna haritasının ÜZERİNE yazılır (agency_code_overrides —
    # Sedna senkronu agency_code_map'i silip yeniden yüklediğinden kalıcı ekler buradadır)
    name_to_code.update({o.pms_name.strip().upper(): o.acc_code
                         for o in db.query(AgencyCodeOverride).all()})
    out: dict = {}
    for g in db.query(AgencyGroup).all():
        for member in (g.members or []):
            code = name_to_code.get((member or "").strip().upper())
            if code:
                out[code] = {"id": g.id, "name": g.name}
    return out


def _advance_by_code(db: Session, firm_names: dict, rates: dict) -> dict:
    """customer_code → {"tl": TL karşılığı toplam, "native": {para_birimi: native kalan}}.

    340 'Alınan Avanslar' (SalesAdvance) kayıtları muhasebe cari ADLARIYLA tutulur ve 120
    adlarıyla aynı evrendir → `_norm_tokens` alt-küme eşlemesi güvenilir (satis-faturalari
    `_merged_advances` ile aynı desen). TL karşılığı son TCMB forex_buying ile; native kırılım
    tek-para-birimli firmalarda € gösterim için taşınır.
    """
    firm_tokens = {code: _norm_tokens(name or code) for code, name in firm_names.items()}
    out: dict = {}
    for a in db.query(SalesAdvance).all():
        received = _f(a.received)
        consumed = _f(a.consumed)
        if received <= 0 and consumed <= 0:
            continue
        rem = round(received - consumed, 2)
        at = _norm_tokens(a.name or a.code)
        if not at:
            continue
        best, best_score = None, 0
        for code, ft in firm_tokens.items():
            if not ft:
                continue
            if at <= ft or ft <= at:
                score = len(at & ft) + 10  # alt-küme = güçlü eşleşme
            else:
                score = len(at & ft) if len(at & ft) >= 2 else 0
            if score > best_score:
                best, best_score = code, score
        if best:
            cur = (a.currency or "TL").strip() or "TL"
            rate = rates.get(cur, 1.0)
            slot = out.setdefault(best, {"tl": 0.0, "native": {},
                                         "received_tl": 0.0, "consumed_tl": 0.0})
            # Alınan/mahsup istatistikleri — "avans mahsup edilmiş mi?" satırdan okunsun
            slot["received_tl"] = round(slot["received_tl"] + received * rate, 2)
            slot["consumed_tl"] = round(slot["consumed_tl"] + consumed * rate, 2)
            # Netleme havuzu (kalan) — davranış değişmedi: yalnız >1 kalan sayılır
            if rem > 1:
                slot["tl"] = round(slot["tl"] + rem * rate, 2)
                slot["native"][cur] = round(slot["native"].get(cur, 0.0) + rem, 2)
    return out


def _collections_by_code(db: Session) -> dict:
    """customer_code → tahsilat istatistikleri (satırdaki 'Tahsilat' kolonu için).

    {count, tl (toplam TL karşılığı), by_currency: {birim: native toplam},
     last_date, last_amount (native), last_currency}
    """
    out: dict = {}
    for c in db.query(SalesCollection).all():
        s = out.setdefault(c.customer_code, {
            "count": 0, "tl": 0.0, "by_currency": {},
            "last_date": None, "last_amount": 0.0, "last_currency": "TL", "_last_id": 0,
        })
        cur = (c.currency or "TL").strip() or "TL"
        native = _f(c.amount_currency) or _f(c.amount)
        s["count"] += 1
        s["tl"] = round(s["tl"] + _f(c.amount), 2)
        s["by_currency"][cur] = round(s["by_currency"].get(cur, 0.0) + native, 2)
        # (tarih, id) karşılaştırması: aynı-gün birden çok tahsilatta seçim deterministik
        if s["last_date"] is None or (c.collection_date, c.id) > (s["last_date"], s["_last_id"]):
            s["last_date"] = c.collection_date
            s["_last_id"] = c.id
            s["last_amount"] = round(native, 2)
            s["last_currency"] = cur
    return out


# ─── Hak ediş hesaplama ──────────────────────────────────

def compute_receivables(db: Session, today: Optional[date] = None) -> dict:
    """Firma bazlı açık hak ediş + vade/yaşlandırma hesabı.

    Döner: {
      "firms": [{code, name, term_days, is_default_term, currency'ler,
                 open_tl, overdue_tl, max_overdue_days, next_due_date,
                 invoice_count, buckets:{...tl}}...],  # overdue_tl azalan sıralı
      "summary": {open_tl, overdue_tl, due_7d_tl, firm_count, overdue_firm_count,
                  buckets:{not_due, overdue_1_7, overdue_8_30, overdue_30_plus}},
    }
    Tutarlar TL karşılığıdır (kartlar/toplama için); fatura detayında native de döner.
    """
    today = today or date.today()
    inv_map, adv_pool = _compute_cached(db)
    terms = get_terms_map(db)

    firms: dict = {}
    summary_buckets = {BUCKET_NOT_DUE: 0.0, BUCKET_1_7: 0.0, BUCKET_8_30: 0.0, BUCKET_30_PLUS: 0.0}
    due_7d_tl = 0.0

    # MÜNFERİT HARİÇ (2026-07-02 kanıtı): walk-in misafir çıkışta kart/nakit/havale ile öder
    # (PMS folio bakiyeleri 0 — 259/259 doğrulandı) ama muhasebe 120.03.* hesabına tahsilat
    # kaydı işlemez → 120 alacak sinyali münferitte GÜVENİLMEZ, sahte "açık" üretir.
    # Hak ediş takibi yalnız ACENTE (anlaşmalı firma) alacaklarını izler.
    # kod → kesilen TÜM faturaların toplamı (ödenmişler DAHİL) — "Faturalanan" kolonu
    invoiced_by_code: dict = {}
    for inv in db.query(SalesInvoice).filter(SalesInvoice.is_munferit.is_(False)).all():
        agg = invoiced_by_code.setdefault(inv.customer_code, {"tl": 0.0, "count": 0, "by_cur": {}})
        agg["tl"] = round(agg["tl"] + _f(inv.amount), 2)
        agg["count"] += 1
        _nat = _f(inv.amount_currency) or _f(inv.amount)
        agg["by_cur"][inv.currency] = round(agg["by_cur"].get(inv.currency, 0.0) + _nat, 2)

        st = inv_map.get(inv.id, {})
        if st.get("status") == "paid":
            continue
        remaining_tl = round(_f(inv.amount) - _f(st.get("collected_tl", 0)), 2)
        if remaining_tl <= 0.01:
            continue

        term_days = terms.get(inv.customer_code, DEFAULT_TERM_DAYS)
        due = inv.invoice_date + timedelta(days=term_days)
        overdue = (today - due).days
        bucket = _bucket(overdue)

        f = firms.setdefault(inv.customer_code, {
            "code": inv.customer_code,
            "name": inv.customer_name,
            "term_days": term_days,
            "is_default_term": inv.customer_code not in terms,
            "currencies": set(),
            "open_tl": 0.0, "overdue_tl": 0.0,
            "open_native": 0.0, "overdue_native": 0.0,  # tek para birimli firmada € gösterim için
            "max_overdue_days": 0, "next_due_date": None,
            "invoice_count": 0,
            "buckets": {BUCKET_NOT_DUE: 0.0, BUCKET_1_7: 0.0, BUCKET_8_30: 0.0, BUCKET_30_PLUS: 0.0},
            "due_by_month": {},  # 'YYYY-MM' → {tl, native} — ay sonu tahsilat planı
        })
        native_amt = _f(inv.amount_currency) or _f(inv.amount)
        remaining_native = round(native_amt - _f(st.get("collected", 0)), 2)
        f["currencies"].add(inv.currency)
        f["open_tl"] = round(f["open_tl"] + remaining_tl, 2)
        f["open_native"] = round(f["open_native"] + remaining_native, 2)
        f["invoice_count"] += 1
        f["buckets"][bucket] = round(f["buckets"][bucket] + remaining_tl, 2)
        summary_buckets[bucket] = round(summary_buckets[bucket] + remaining_tl, 2)
        md = f["due_by_month"].setdefault(due.strftime("%Y-%m"), {"tl": 0.0, "native": 0.0})
        md["tl"] = round(md["tl"] + remaining_tl, 2)
        md["native"] = round(md["native"] + remaining_native, 2)
        if overdue > 0:
            f["overdue_tl"] = round(f["overdue_tl"] + remaining_tl, 2)
            f["overdue_native"] = round(f["overdue_native"] + remaining_native, 2)
            f["max_overdue_days"] = max(f["max_overdue_days"], overdue)
        else:
            if f["next_due_date"] is None or due < f["next_due_date"]:
                f["next_due_date"] = due
            if (due - today).days <= 7:
                due_7d_tl = round(due_7d_tl + remaining_tl, 2)

    # Avans düşme: firma bazlı kalan avans (340, isim-eşli) → net açık.
    # TEK para birimli firmada tutarlar NATIVE (€) de taşınır — fatura detayı ile aynı birim
    # (TL karşılığı fatura-tarihi kurundandır, kullanıcıya karışık görünüyordu; 2026-07-02 geri bildirimi).
    rates = _latest_rates(db)
    advances = _advance_by_code(db, {c: f["name"] for c, f in firms.items()}, rates)
    collections = _collections_by_code(db)
    # FIFO havuzunda artan (hiçbir faturaya eşlenmemiş) tahsilat — tipik neden çapraz kur:
    # faturaları EUR olan firmaya TL tahsilat gelirse havuzda askıda kalır ve açık tutardan
    # DÜŞÜLMEZ (canlı örnek 2026-07-03: FUN AND SUN ₺213.959 TL EFT, faturalar EUR).
    pool_by_code: dict = {}
    for (pcode, pcur), leftover in adv_pool.items():
        if leftover > 0.01:
            pool_by_code.setdefault(pcode, {})[pcur] = round(leftover, 2)
    for code, f in firms.items():
        adv = advances.get(code)
        f["advance_tl"] = adv["tl"] if adv else 0.0
        f["net_open_tl"] = round(max(0.0, f["open_tl"] - f["advance_tl"]), 2)
        f["currencies"] = sorted(f["currencies"])
        f["next_due_date"] = f["next_due_date"].isoformat() if f["next_due_date"] else None
        f["is_group"] = False
        f["members"] = []

        # display_currency: firmanın TÜM faturaları tek (TRY-dışı) para birimindeyse o birim
        single = f["currencies"][0] if len(f["currencies"]) == 1 else None
        f["display_currency"] = single if single not in (None, "TL", "TRY") else None
        if f["display_currency"]:
            cur = f["display_currency"]
            if adv:
                nat = adv["native"]
                if set(nat) <= {cur}:  # avans da aynı birimde → birebir native
                    adv_native = nat.get(cur, 0.0)
                else:  # farklı birimde avans → güncel kurla firma birimine çevir (yaklaşık)
                    rate = rates.get(cur, 0.0)
                    adv_native = (adv["tl"] / rate) if rate else 0.0
            else:
                adv_native = 0.0
            f["advance_native"] = round(adv_native, 2)
            f["net_open_native"] = round(max(0.0, f["open_native"] - adv_native), 2)
        else:
            f["open_native"] = None
            f["overdue_native"] = None
            f["advance_native"] = None
            f["net_open_native"] = None

        # Tahsilat görünürlüğü (2026-07-03): "bu firmadan hiç tahsilat yapılmış mı?"
        # sorusu satırdan okunabilsin — toplam + son tahsilat + eşlenmemiş havuz.
        col = collections.get(code)
        f["collected_tl"] = col["tl"] if col else 0.0
        f["collection_count"] = col["count"] if col else 0
        f["last_collection_date"] = (col["last_date"].isoformat()
                                     if col and col["last_date"] else None)
        f["last_collection_amount"] = col["last_amount"] if col else 0.0
        f["last_collection_currency"] = col["last_currency"] if col else None
        if f["display_currency"]:
            f["collected_native"] = round(
                col["by_currency"].get(f["display_currency"], 0.0), 2) if col else 0.0
        else:
            f["collected_native"] = None
        unap = pool_by_code.get(code, {})
        f["unapplied_by_currency"] = unap
        f["unapplied_tl"] = round(
            sum(v * rates.get(cur_, 1.0) for cur_, v in unap.items()), 2)

        # Faturalanan (kesilen TÜM faturalar — ödenmişler dahil)
        agg = invoiced_by_code.get(code, {"tl": 0.0, "count": 0, "by_cur": {}})
        f["invoiced_tl"] = agg["tl"]
        f["total_invoice_count"] = agg["count"]
        f["invoiced_native"] = (round(agg["by_cur"].get(f["display_currency"], 0.0), 2)
                                if f["display_currency"] else None)

        # Avans mahsup durumu (340: alınan / faturayla mahsup edilen — güncel kurla TL)
        f["advance_received_tl"] = adv["received_tl"] if adv else 0.0
        f["advance_consumed_tl"] = adv["consumed_tl"] if adv else 0.0

        # Ay sonu tahsilat planı: ay içi vadesi dolan + kümülatif (gecikmişler ilk aya devreder)
        sched = []
        cum_tl = 0.0
        cum_nat = 0.0
        for mk in sorted(f["due_by_month"].keys()):
            v = f["due_by_month"][mk]
            cum_tl = round(cum_tl + v["tl"], 2)
            cum_nat = round(cum_nat + v["native"], 2)
            sched.append({
                "month": mk,
                "due_tl": v["tl"], "cum_tl": cum_tl,
                "due_native": round(v["native"], 2) if f["display_currency"] else None,
                "cum_native": cum_nat if f["display_currency"] else None,
            })
        f["monthly_due"] = sched
        del f["due_by_month"]

    # Gruplama: rezervasyon acente grupları (agency_groups) → PMS-ad köprüsüyle 120 kodları
    gmap = _group_map(db)
    grouped: dict = {}
    firm_list = []
    for code, f in firms.items():
        g = gmap.get(code)
        if not g:
            firm_list.append(f)
            continue
        row = grouped.get(g["id"])
        if row is None:
            row = grouped[g["id"]] = {
                "code": f"group-{g['id']}", "name": g["name"],
                "is_group": True, "members": [],
                "term_days": f["term_days"], "is_default_term": f["is_default_term"],
                "currencies": set(),
                "open_tl": 0.0, "overdue_tl": 0.0, "advance_tl": 0.0, "net_open_tl": 0.0,
                "max_overdue_days": 0, "next_due_date": None, "invoice_count": 0,
                "buckets": {BUCKET_NOT_DUE: 0.0, BUCKET_1_7: 0.0, BUCKET_8_30: 0.0, BUCKET_30_PLUS: 0.0},
            }
        row["members"].append({
            "code": f["code"], "name": f["name"], "term_days": f["term_days"],
            "is_default_term": f["is_default_term"], "open_tl": f["open_tl"],
            "overdue_tl": f["overdue_tl"], "advance_tl": f["advance_tl"],
            "max_overdue_days": f["max_overdue_days"],
        })
        row["currencies"].update(f["currencies"])
        for k in ("open_tl", "overdue_tl", "advance_tl", "invoice_count"):
            row[k] = round(row[k] + f[k], 2) if k != "invoice_count" else row[k] + f[k]
        for b, v in f["buckets"].items():
            row["buckets"][b] = round(row["buckets"][b] + v, 2)
        row["max_overdue_days"] = max(row["max_overdue_days"], f["max_overdue_days"])
        if f["next_due_date"] and (row["next_due_date"] is None or f["next_due_date"] < row["next_due_date"]):
            row["next_due_date"] = f["next_due_date"]
        if f["term_days"] != row["term_days"]:
            row["term_days"] = None  # üyeler farklı vadede → "karma" (UI gösterir)

    for row in grouped.values():
        row["currencies"] = sorted(row["currencies"])
        row["net_open_tl"] = round(max(0.0, row["open_tl"] - row["advance_tl"]), 2)
        # Grup native gösterimi: TÜM üyeler aynı (TRY-dışı) tek para birimindeyse üye native'leri topla
        member_codes = [m["code"] for m in row["members"]]
        member_fs = [firms[c] for c in member_codes]
        dcs = {mf["display_currency"] for mf in member_fs}
        if len(dcs) == 1 and None not in dcs:
            row["display_currency"] = dcs.pop()
            row["open_native"] = round(sum(mf["open_native"] for mf in member_fs), 2)
            row["overdue_native"] = round(sum(mf["overdue_native"] for mf in member_fs), 2)
            row["advance_native"] = round(sum(mf["advance_native"] for mf in member_fs), 2)
            row["net_open_native"] = round(max(0.0, row["open_native"] - row["advance_native"]), 2)
        else:
            row["display_currency"] = None
            row["open_native"] = row["overdue_native"] = None
            row["advance_native"] = row["net_open_native"] = None

        # Grup tahsilat toplamları (üyelerden)
        row["collected_tl"] = round(sum(mf["collected_tl"] for mf in member_fs), 2)
        row["collection_count"] = sum(mf["collection_count"] for mf in member_fs)
        row["unapplied_tl"] = round(sum(mf["unapplied_tl"] for mf in member_fs), 2)
        merged_unap: dict = {}
        for mf in member_fs:
            for cur_, v in mf["unapplied_by_currency"].items():
                merged_unap[cur_] = round(merged_unap.get(cur_, 0.0) + v, 2)
        row["unapplied_by_currency"] = merged_unap
        last_mf = max((mf for mf in member_fs if mf["last_collection_date"]),
                      key=lambda mf: mf["last_collection_date"], default=None)
        row["last_collection_date"] = last_mf["last_collection_date"] if last_mf else None
        row["last_collection_amount"] = last_mf["last_collection_amount"] if last_mf else 0.0
        row["last_collection_currency"] = last_mf["last_collection_currency"] if last_mf else None
        row["collected_native"] = (round(sum(mf["collected_native"] or 0.0 for mf in member_fs), 2)
                                   if row["display_currency"] else None)

        # Grup: faturalanan + avans mahsup + ay sonu planı (üyelerden)
        row["invoiced_tl"] = round(sum(mf["invoiced_tl"] for mf in member_fs), 2)
        row["total_invoice_count"] = sum(mf["total_invoice_count"] for mf in member_fs)
        row["invoiced_native"] = (round(sum(mf["invoiced_native"] or 0.0 for mf in member_fs), 2)
                                  if row["display_currency"] else None)
        row["advance_received_tl"] = round(sum(mf["advance_received_tl"] for mf in member_fs), 2)
        row["advance_consumed_tl"] = round(sum(mf["advance_consumed_tl"] for mf in member_fs), 2)
        gm: dict = {}
        for mf in member_fs:
            for e in mf["monthly_due"]:
                slot = gm.setdefault(e["month"], {"tl": 0.0, "native": 0.0})
                slot["tl"] = round(slot["tl"] + e["due_tl"], 2)
                slot["native"] = round(slot["native"] + (e["due_native"] or 0.0), 2)
        g_sched = []
        g_cum_tl = 0.0
        g_cum_nat = 0.0
        for mk in sorted(gm.keys()):
            v = gm[mk]
            g_cum_tl = round(g_cum_tl + v["tl"], 2)
            g_cum_nat = round(g_cum_nat + v["native"], 2)
            g_sched.append({
                "month": mk,
                "due_tl": v["tl"], "cum_tl": g_cum_tl,
                "due_native": v["native"] if row["display_currency"] else None,
                "cum_native": g_cum_nat if row["display_currency"] else None,
            })
        row["monthly_due"] = g_sched
        firm_list.append(row)

    # En sorunlu (gecikmiş tutarı en yüksek) üstte; eşitlikte net açık tutara göre
    firm_list.sort(key=lambda x: (-x["overdue_tl"], -x["net_open_tl"]))

    overdue_tl = round(summary_buckets[BUCKET_1_7] + summary_buckets[BUCKET_8_30]
                       + summary_buckets[BUCKET_30_PLUS], 2)
    advance_total = round(sum(x["advance_tl"] for x in firm_list), 2)
    open_total = round(sum(x["open_tl"] for x in firm_list), 2)
    # Para birimi kırılımı (kartlarda "€X + ₺Y" ipucu için): tek-birimli firmalar native,
    # karışık firmalar TL karşılığıyla TRY kovasına
    open_by_currency: dict = {}
    for x in firm_list:
        if x["display_currency"]:
            k = x["display_currency"]
            open_by_currency[k] = round(open_by_currency.get(k, 0.0) + x["open_native"], 2)
        else:
            open_by_currency["TRY"] = round(open_by_currency.get("TRY", 0.0) + x["open_tl"], 2)
    return {
        "firms": firm_list,
        "summary": {
            "open_tl": open_total,
            "open_by_currency": open_by_currency,
            "advance_tl": advance_total,
            "net_open_tl": round(sum(x["net_open_tl"] for x in firm_list), 2),
            "overdue_tl": overdue_tl,
            "due_7d_tl": due_7d_tl,
            "collected_tl": round(sum(x["collected_tl"] for x in firm_list), 2),
            "unapplied_tl": round(sum(x["unapplied_tl"] for x in firm_list), 2),
            "firm_count": len(firm_list),
            "overdue_firm_count": sum(1 for x in firm_list if x["overdue_tl"] > 0),
            "buckets": summary_buckets,
        },
    }


def group_member_codes(db: Session, group_id: int) -> list:
    """Bir grubun 120 kodları (köprü üzerinden) — grup fatura detayı için."""
    gmap = _group_map(db)
    return [code for code, g in gmap.items() if g["id"] == group_id]


def _resolve_codes(db: Session, customer_code: str) -> list:
    """`group-{id}` → üye 120 kodları; düz kod → tek elemanlı liste."""
    if customer_code.startswith("group-"):
        try:
            return group_member_codes(db, int(customer_code.split("-", 1)[1]))
        except (ValueError, IndexError):
            return []
    return [customer_code]


def firm_collections(db: Session, customer_code: str) -> list:
    """Bir firmanın (veya `group-{id}` grubunun) tahsilat dökümü — yeniden eskiye.

    Satır genişletildiğinde fatura listesinin yanında gösterilir: "bu firmadan
    hiç/ne zaman tahsilat yapılmış?" sorusunun kanıtı.
    """
    codes = _resolve_codes(db, customer_code)
    if not codes:
        return []
    items = []
    for c in (db.query(SalesCollection)
              .filter(SalesCollection.customer_code.in_(codes))
              .order_by(SalesCollection.collection_date.desc(), SalesCollection.id.desc())
              .all()):
        native = _f(c.amount_currency) or _f(c.amount)
        items.append({
            "id": c.id,
            "customer_code": c.customer_code,
            "customer_name": c.customer_name,
            "collection_date": c.collection_date.isoformat(),
            "currency": (c.currency or "TL").strip() or "TL",
            "amount": round(native, 2),
            "amount_tl": round(_f(c.amount), 2),
            "description": c.description,
        })
    return items


def firm_open_invoices(db: Session, customer_code: str, today: Optional[date] = None) -> list:
    """Bir firmanın (veya `group-{id}` ile bir GRUBUN tüm üyelerinin) açık/kısmi faturaları —
    vade + gecikme + kalan (native ve TL). Grup modunda her fatura kendi firmasının vadesiyle."""
    today = today or date.today()
    inv_map, _adv = _compute_cached(db)
    terms = get_terms_map(db)

    codes = _resolve_codes(db, customer_code)
    if not codes:
        return []

    items = []
    for inv in (db.query(SalesInvoice)
                .filter(SalesInvoice.customer_code.in_(codes),
                        SalesInvoice.is_munferit.is_(False))  # münferit hariç (bkz. compute_receivables)
                .order_by(SalesInvoice.invoice_date).all()):
        term_days = terms.get(inv.customer_code, DEFAULT_TERM_DAYS)
        st = inv_map.get(inv.id, {})
        if st.get("status") == "paid":
            continue
        remaining_tl = round(_f(inv.amount) - _f(st.get("collected_tl", 0)), 2)
        if remaining_tl <= 0.01:
            continue
        native_amt = _f(inv.amount_currency) or _f(inv.amount)
        due = inv.invoice_date + timedelta(days=term_days)
        overdue = (today - due).days
        items.append({
            "id": inv.id,
            "customer_code": inv.customer_code,
            "customer_name": inv.customer_name,
            "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date.isoformat(),
            "due_date": due.isoformat(),
            "overdue_days": max(0, overdue),
            "bucket": _bucket(overdue),
            "currency": inv.currency,
            "amount": round(native_amt, 2),
            "collected": round(_f(st.get("collected", 0)), 2),
            "remaining": round(native_amt - _f(st.get("collected", 0)), 2),
            "remaining_tl": remaining_tl,
            "status": st.get("status", "open"),
            "description": inv.description,
        })
    return items
