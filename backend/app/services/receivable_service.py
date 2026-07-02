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
from app.models.agency_group import AgencyGroup
from app.models.exchange_rate import ExchangeRate
from app.models.receivable_term import DEFAULT_TERM_DAYS, ReceivableTerm
from app.models.sales_invoice import SalesAdvance, SalesInvoice
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
    """currency_code → TL kuru (son tarihli TCMB forex_selling / unit). TL=1."""
    rates = {"TL": 1.0, "TRY": 1.0}
    for r in (db.query(ExchangeRate)
              .order_by(ExchangeRate.currency_code, ExchangeRate.date.desc()).all()):
        if r.currency_code not in rates:
            unit = float(r.unit or 1) or 1
            sell = _f(r.forex_selling)
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
    out: dict = {}
    for g in db.query(AgencyGroup).all():
        for member in (g.members or []):
            code = name_to_code.get((member or "").strip().upper())
            if code:
                out[code] = {"id": g.id, "name": g.name}
    return out


def _advance_by_code(db: Session, firm_names: dict, rates: dict) -> dict:
    """customer_code → kalan avans TL karşılığı.

    340 'Alınan Avanslar' (SalesAdvance) kayıtları muhasebe cari ADLARIYLA tutulur ve 120
    adlarıyla aynı evrendir → `_norm_tokens` alt-küme eşlemesi güvenilir (satis-faturalari
    `_merged_advances` ile aynı desen). Native kalan → son TCMB forex_selling ile TL'ye çevrilir.
    """
    firm_tokens = {code: _norm_tokens(name or code) for code, name in firm_names.items()}
    out: dict = {}
    for a in db.query(SalesAdvance).all():
        rem = round(_f(a.received) - _f(a.consumed), 2)
        if rem <= 1:
            continue
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
            rate = rates.get((a.currency or "TL").strip() or "TL", 1.0)
            out[best] = round(out.get(best, 0.0) + rem * rate, 2)
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
    inv_map, _adv = _compute_cached(db)
    terms = get_terms_map(db)

    firms: dict = {}
    summary_buckets = {BUCKET_NOT_DUE: 0.0, BUCKET_1_7: 0.0, BUCKET_8_30: 0.0, BUCKET_30_PLUS: 0.0}
    due_7d_tl = 0.0

    # MÜNFERİT HARİÇ (2026-07-02 kanıtı): walk-in misafir çıkışta kart/nakit/havale ile öder
    # (PMS folio bakiyeleri 0 — 259/259 doğrulandı) ama muhasebe 120.03.* hesabına tahsilat
    # kaydı işlemez → 120 alacak sinyali münferitte GÜVENİLMEZ, sahte "açık" üretir.
    # Hak ediş takibi yalnız ACENTE (anlaşmalı firma) alacaklarını izler.
    for inv in db.query(SalesInvoice).filter(SalesInvoice.is_munferit.is_(False)).all():
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
            "max_overdue_days": 0, "next_due_date": None,
            "invoice_count": 0,
            "buckets": {BUCKET_NOT_DUE: 0.0, BUCKET_1_7: 0.0, BUCKET_8_30: 0.0, BUCKET_30_PLUS: 0.0},
        })
        f["currencies"].add(inv.currency)
        f["open_tl"] = round(f["open_tl"] + remaining_tl, 2)
        f["invoice_count"] += 1
        f["buckets"][bucket] = round(f["buckets"][bucket] + remaining_tl, 2)
        summary_buckets[bucket] = round(summary_buckets[bucket] + remaining_tl, 2)
        if overdue > 0:
            f["overdue_tl"] = round(f["overdue_tl"] + remaining_tl, 2)
            f["max_overdue_days"] = max(f["max_overdue_days"], overdue)
        else:
            if f["next_due_date"] is None or due < f["next_due_date"]:
                f["next_due_date"] = due
            if (due - today).days <= 7:
                due_7d_tl = round(due_7d_tl + remaining_tl, 2)

    # Avans düşme: firma bazlı kalan avans (340, isim-eşli) TL karşılığı → net açık
    rates = _latest_rates(db)
    advances = _advance_by_code(db, {c: f["name"] for c, f in firms.items()}, rates)
    for code, f in firms.items():
        f["advance_tl"] = advances.get(code, 0.0)
        f["net_open_tl"] = round(max(0.0, f["open_tl"] - f["advance_tl"]), 2)
        f["currencies"] = sorted(f["currencies"])
        f["next_due_date"] = f["next_due_date"].isoformat() if f["next_due_date"] else None
        f["is_group"] = False
        f["members"] = []

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
        firm_list.append(row)

    # En sorunlu (gecikmiş tutarı en yüksek) üstte; eşitlikte net açık tutara göre
    firm_list.sort(key=lambda x: (-x["overdue_tl"], -x["net_open_tl"]))

    overdue_tl = round(summary_buckets[BUCKET_1_7] + summary_buckets[BUCKET_8_30]
                       + summary_buckets[BUCKET_30_PLUS], 2)
    advance_total = round(sum(x["advance_tl"] for x in firm_list), 2)
    open_total = round(sum(x["open_tl"] for x in firm_list), 2)
    return {
        "firms": firm_list,
        "summary": {
            "open_tl": open_total,
            "advance_tl": advance_total,
            "net_open_tl": round(sum(x["net_open_tl"] for x in firm_list), 2),
            "overdue_tl": overdue_tl,
            "due_7d_tl": due_7d_tl,
            "firm_count": len(firm_list),
            "overdue_firm_count": sum(1 for x in firm_list if x["overdue_tl"] > 0),
            "buckets": summary_buckets,
        },
    }


def group_member_codes(db: Session, group_id: int) -> list:
    """Bir grubun 120 kodları (köprü üzerinden) — grup fatura detayı için."""
    gmap = _group_map(db)
    return [code for code, g in gmap.items() if g["id"] == group_id]


def firm_open_invoices(db: Session, customer_code: str, today: Optional[date] = None) -> list:
    """Bir firmanın (veya `group-{id}` ile bir GRUBUN tüm üyelerinin) açık/kısmi faturaları —
    vade + gecikme + kalan (native ve TL). Grup modunda her fatura kendi firmasının vadesiyle."""
    today = today or date.today()
    inv_map, _adv = _compute_cached(db)
    terms = get_terms_map(db)

    if customer_code.startswith("group-"):
        try:
            codes = group_member_codes(db, int(customer_code.split("-", 1)[1]))
        except (ValueError, IndexError):
            codes = []
        if not codes:
            return []
    else:
        codes = [customer_code]

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
