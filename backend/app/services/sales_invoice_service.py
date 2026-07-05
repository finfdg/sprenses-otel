"""Satış faturası FIFO servis katmanı — tahsil hesabı + 30sn TTL cache + avans bakiyeleri.

D1-1/D1-5 (2026-06-22): Bu saf FIFO motoru + cache eskiden `routers/finance/sales_invoices.py`
içindeydi; `routers/yonetim.py` (_merged_advances) oradan import ediyordu (router→router).
Artık burada; sales_invoices router'ı + yonetim buradan alır. İçe aktarma sonrası
`_invalidate_compute_cache()` çağrılır (conftest test izolasyonunda da kullanır).
"""
import threading
import time
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sales_invoice import (
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_PARTIAL,
    SalesAdvance,
    SalesCollection,
    SalesInvoice,
)
from app.utils.text_match import _norm_tokens



_EPS = 0.01  # float kırıntı eşiği


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _compute(db: Session):
    """Tarih-sıralı FIFO. Döner: (inv_map, advance_balance).

    inv_map[invoice_id] = {"collected", "advance", "status"}
      - advance = faturanın **kesildiği anda mevcut avansla** karşılanan kısmı (prepaid).
    advance_balance[customer_code] = kullanılmamış net avans (tüm faturalardan artan tahsilat).

    Müşteri bazında olaylar tarih sırasıyla işlenir. Aynı gün **önce fatura sonra tahsilat**
    (aynı-gün ödeme avans sayılmaz — münferit walk-in). Tahsilat geldiğinde en eski açık
    faturaya backfill (sonradan gelen = normal tahsilat); fatura kesildiğinde önce mevcut
    avans havuzundan karşılanır (prepaid).
    """
    def _amt(o):  # native (döviz) tutar — yoksa TL'ye düş
        n = _f(o.amount_currency)
        return n if n > _EPS else _f(o.amount)

    # (müşteri, para birimi) bazında grupla — EUR avans yalnız EUR faturayı kapatır
    inv_by: dict = defaultdict(list)
    col_by: dict = defaultdict(list)
    for inv in db.query(SalesInvoice).all():
        inv_by[(inv.customer_code, inv.currency)].append(inv)
    for col in db.query(SalesCollection).all():
        col_by[(col.customer_code, col.currency)].append(col)

    inv_map: dict = {}
    advance_balance: dict = {}   # (code, currency) -> native leftover (net avans)

    for key in set(inv_by) | set(col_by):
        invs = inv_by.get(key, [])
        events = [(inv.invoice_date, 0, "inv", inv) for inv in invs]
        events += [(col.collection_date, 1, "col", col) for col in col_by.get(key, [])]
        events.sort(key=lambda e: (e[0], e[1]))

        pool = 0.0           # mevcut avans/kredi havuzu (native)
        open_q: list = []    # açık faturalar FIFO: [(inv, remaining_native)]
        state: dict = {}     # inv.id -> [collected_native, advance_native]
        for _d, _t, kind, obj in events:
            if kind == "col":
                pool += _amt(obj)
                i = 0
                while i < len(open_q) and pool > _EPS:
                    inv, rem = open_q[i]
                    apply = min(rem, pool)
                    pool -= apply
                    rem -= apply
                    state[inv.id][0] += apply
                    open_q[i] = (inv, rem)
                    if rem <= _EPS:
                        i += 1
                    else:
                        break
                open_q = open_q[i:]
            else:
                amount = _amt(obj)
                adv = min(pool, amount) if pool > _EPS else 0.0
                pool -= adv
                state[obj.id] = [adv, adv]
                if amount - adv > _EPS:
                    open_q.append((obj, amount - adv))

        for inv in invs:
            collected, adv = state.get(inv.id, [0.0, 0.0])
            nat_amt = _amt(inv)
            ratio = (collected / nat_amt) if nat_amt > _EPS else 0.0
            if collected >= nat_amt - _EPS:
                st = STATUS_PAID
            elif collected > _EPS:
                st = STATUS_PARTIAL
            else:
                st = STATUS_OPEN
            inv_map[inv.id] = {
                "collected": round(collected, 2),           # native
                "collected_tl": round(_f(inv.amount) * ratio, 2),
                "advance": round(adv, 2),                   # native
                "status": st,
            }
        if pool > _EPS:
            advance_balance[key] = round(pool, 2)
    return inv_map, advance_balance


# ─── _compute TTL cache ─────────────────────────────────
# _compute her çağrıda iki tam tabloyu (faturalar + tahsilatlar) belleğe çekip FIFO yapar.
# 3 endpoint (list/summary/advances) aynı sonucu kullanır ve veri yalnız
# Sedna içe aktarmada değişir → 30sn süreç-içi cache tekrar hesaplamayı önler (mizan deseni).
_COMPUTE_TTL = 30.0  # saniye
_compute_cache: dict = {"ts": 0.0, "data": None}
_compute_lock = threading.Lock()


def _compute_cached(db: Session):
    """_compute sonucunu 30sn cache'ler. İçe aktarma _invalidate_compute_cache() çağırır."""
    now = time.monotonic()
    data = _compute_cache["data"]
    if data is not None and (now - _compute_cache["ts"]) < _COMPUTE_TTL:
        return data
    data = _compute(db)
    with _compute_lock:
        _compute_cache["data"] = data
        _compute_cache["ts"] = now
    return data


def _invalidate_compute_cache() -> None:
    """Satış faturası içe aktarmadan sonra cache'i sıfırla → kullanıcı taze veriyi anında görür."""
    with _compute_lock:
        _compute_cache["data"] = None
        _compute_cache["ts"] = 0.0


def _merged_advances(db: Session):
    """Acente avans bakiyeleri (EKSİKSİZ): Sedna 340 'Alınan Avanslar' (asıl defter) + 120 net-alacak.
    340'ta adı geçen 120 kaydı atlanır (mükerrer önleme). Döner: (merged_items, total_by_currency)."""
    # 120 net-alacak (offline, import edilmiş veriden)
    _, adv_bal = _compute_cached(db)
    items_120 = []
    if adv_bal:
        inv_info: dict = {}
        for code, cur, name, ism, inv in (
            db.query(SalesInvoice.customer_code, SalesInvoice.currency,
                     func.max(SalesInvoice.customer_name), func.bool_or(SalesInvoice.is_munferit),
                     func.sum(SalesInvoice.amount_currency))
            .group_by(SalesInvoice.customer_code, SalesInvoice.currency).all()
        ):
            inv_info[(code, cur)] = {"name": name, "ism": bool(ism), "invoiced": _f(inv)}
        col_info: dict = {}
        for code, cur, name, tot in (
            db.query(SalesCollection.customer_code, SalesCollection.currency,
                     func.max(SalesCollection.customer_name), func.sum(SalesCollection.amount_currency))
            .group_by(SalesCollection.customer_code, SalesCollection.currency).all()
        ):
            col_info[(code, cur)] = {"name": name, "amount": _f(tot)}
        for (code, cur), net in adv_bal.items():
            im = inv_info.get((code, cur))
            cm = col_info.get((code, cur), {})
            invoiced = im["invoiced"] if im else 0.0
            collected = cm.get("amount", 0.0)
            items_120.append({
                "customer_name": (im["name"] if im else None) or cm.get("name") or code,
                "currency": cur, "source": "120",
                "is_munferit": im["ism"] if im else code.startswith("120.03"),
                "received": round(collected, 2), "consumed": round(min(collected, invoiced), 2),
                "remaining": net,
            })

    # 340 'Alınan Avanslar' (asıl avans defteri; import edilmiş tablodan — offline)
    items_340 = []
    for a in db.query(SalesAdvance).all():
        rem = round(_f(a.received) - _f(a.consumed), 2)
        if rem > 1:
            items_340.append({
                "customer_name": a.name or a.code, "currency": a.currency or "TL", "source": "340",
                "is_munferit": False,
                "received": round(_f(a.received), 2), "consumed": round(_f(a.consumed), 2), "remaining": rem,
            })

    # birleştir — 340 öncelikli; 120'den adı 340'ta geçeni at (mükerrer)
    tok_340 = [_norm_tokens(x["customer_name"]) for x in items_340]
    merged = list(items_340)
    for it in items_120:
        t = _norm_tokens(it["customer_name"])
        if t and any(len(t & n) >= 1 for n in tok_340):
            continue
        merged.append(it)
    # Döviz-bazlı sırala: önce yabancı para grupları (EUR vb.), sonra TL — her grup içinde kalan azalan.
    # Ham `remaining` ile sıralamak farklı para birimlerini (4M € vs 3M ₺) yanlış kıyaslardı.
    merged.sort(key=lambda x: (x["currency"] == "TL", x["currency"], -x["remaining"]))

    total_by_cur: dict = {}
    for x in merged:
        total_by_cur[x["currency"]] = round(total_by_cur.get(x["currency"], 0.0) + x["remaining"], 2)
    return merged, total_by_cur
