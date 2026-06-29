"""Stok servis katmanı — Sedna içe aktarma + maliyet/KPI hesap (HTTP'siz, saf domain).

D1-1/D1-5 (2026-06-22): Bu saf fonksiyonlar eskiden `routers/stock.py` içindeydi ve
`routers/yonetim.py` + `routers/finance/sedna_sync.py` onları router'dan import ediyordu
(router→router coupling). Artık burada; hem stock router'ı hem de tüketiciler buradan alır.
"""
import calendar
import json
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.exchange_rate import ExchangeRate
from app.models.stock import (
    COST_GROUP_LABELS,
    StockDepot,
    StockMovement,
    StockProduct,
    depot_cost_group,
    type_direction,
    type_label,
)
from app.models.user import User
from app.utils.audit import log_action
from app.utils.occupancy import guest_nights_by_period, occupancy_metrics
from app.utils.sedna_client import (
    fetch_stock_depots,
    fetch_stock_movements,
    fetch_stock_products,
)

logger = logging.getLogger(__name__)




# ─── İçe aktarma servisi (merkezi Sedna sync + tekil endpoint) ──────────────

def run_stock_import(db: Session, current_user: User, ip: Optional[str] = None) -> dict:
    """Sedna'dan depo/ürün/hareket çekip upsert eder (hareketler sedna_line_id ile dedup).

    Commit eder, audit'ler. HTTP'siz — orchestrator + tekil endpoint çağırır.
    """
    depots = fetch_stock_depots()
    products = fetch_stock_products()
    movements = fetch_stock_movements()

    # DB mutasyonları tek transaction — herhangi bir adım patlarsa rollback + 500
    # (diğer Sedna importları — cariler/checks — ile tutarlı; yarım-state bırakmaz).
    try:
        # Depolar — code ile upsert
        existing_d = {d.code: d for d in db.query(StockDepot).all()}
        d_new = 0
        for r in depots:
            code = (r["code"] or "").strip()
            if not code:
                continue
            d = existing_d.get(code)
            if d:
                d.name = r["name"]
                d.cost_group = depot_cost_group(code)
                d.no_consumption = bool(r["no_consumption"])
                d.is_expense = bool(r["is_expense"])
            else:
                db.add(StockDepot(code=code, name=r["name"], cost_group=depot_cost_group(code),
                                  no_consumption=bool(r["no_consumption"]), is_expense=bool(r["is_expense"])))
                d_new += 1
        db.flush()

        # Ürünler — sedna_id ile upsert + anlık değer
        existing_p = {p.sedna_id: p for p in db.query(StockProduct).all()}
        p_new = 0
        for r in products:
            sid = r["sedna_id"]
            cs = float(r["current_stock"] or 0)
            lc = float(r["last_cost"] or 0)
            cv = round(cs * lc, 2)
            p = existing_p.get(sid)
            if p:
                p.code = r["code"]
                p.name = r["name"]
                p.currency = r["currency"]
                p.stock_type = r["stock_type"]
                p.current_stock = cs
                p.last_cost = lc
                p.current_value = cv
            else:
                db.add(StockProduct(sedna_id=sid, code=r["code"], name=r["name"], currency=r["currency"],
                                    stock_type=r["stock_type"], current_stock=cs, last_cost=lc, current_value=cv))
                p_new += 1
        db.flush()

        # Hareketler — sedna_line_id ile dedup, yalnız yenileri ekle (hareketler değişmez)
        existing_m = {row[0] for row in db.query(StockMovement.sedna_line_id).all()}
        batch = []
        for r in movements:
            lid = r["line_id"]
            if lid in existing_m:
                continue
            existing_m.add(lid)
            dt = r["date"]
            d_only = dt.date() if isinstance(dt, datetime) else dt
            tc = r["type_code"]
            batch.append({
                "sedna_line_id": lid, "sedna_owner_id": r["owner_id"], "date": d_only,
                "period": d_only.strftime("%Y-%m") if d_only else None,
                "type_code": tc, "type_label": type_label(tc), "direction": type_direction(tc),
                "product_sedna_id": r["product_id"], "product_code": r["product_code"], "product_name": r["product_name"],
                "entry_depot": (r["entry_depot"] or "").strip() or None,
                "exit_depot": (r["exit_depot"] or "").strip() or None,
                "cons_depot": (r["cons_depot"] or "").strip() or None,
                "quantity": float(r["quantity"] or 0), "unit_cost": float(r["unit_cost"] or 0),
                "net_amount": float(r["net_amount"] or 0),
                "supplier_code": r["supplier_code"], "supplier_name": r["supplier_name"], "doc_no": r["doc_no"],
            })
        if batch:
            db.bulk_insert_mappings(StockMovement, batch)

        result = {
            "depots": len(depots), "depots_new": d_new,
            "products": len(products), "products_new": p_new,
            "movements_new": len(batch), "movements_total": len(movements),
        }
        log_action(db, current_user.id, "create", "stock", None,
                   json.dumps(result, ensure_ascii=False), ip)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Stok içe aktarma DB hatası: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Stok içe aktarma sırasında veritabanı hatası.")
    return result


# ─── Operasyonel maliyet KPI (doluluk füzyonu) ──────────────────────────────

def compute_operational_kpi(db: Session) -> dict:
    """Operasyonel KPI: kişi başı F&B maliyeti, CPOR, zayiat %, stok devir hızı.

    Tüketim (Sedna stok, TRY) doluluğa (geceleme/oda-gece, rezervasyon) bölünür. **Yalnız
    tüketimi işlenmiş aylar** (fb>0 & geceleme>0) headline'a girer — tüketim ay-sonu sayımla
    geç post edildiğinden açık aylar dilüsyon yapmaz. Yönetim Paneli de bu fonksiyonu çağırır.
    """
    # Tüketim: (period, cost_group) → tutar
    cons: dict = {}
    group_totals: dict = {}
    for period, group, t in (
        db.query(StockMovement.period, StockDepot.cost_group, func.sum(StockMovement.net_amount))
        .join(StockDepot, StockMovement.cons_depot == StockDepot.code)
        .filter(StockMovement.direction == "consume", StockMovement.period.isnot(None))
        .group_by(StockMovement.period, StockDepot.cost_group).all()
    ):
        g = group or "overhead"
        cons.setdefault(period, {})[g] = float(t or 0)
        group_totals[g] = round(group_totals.get(g, 0.0) + float(t or 0), 2)
    total_consumption = round(sum(group_totals.values()), 2)
    periods = sorted(cons.keys())
    if not periods:
        return {"kpi": {}, "monthly": [], "by_group": [], "occupancy": {}, "consumption": {}}

    # Stok dönem aralığı → doluluk
    y0, m0 = map(int, periods[0].split("-"))
    y1, m1 = map(int, periods[-1].split("-"))
    start = date(y0, m0, 1)
    end = date(y1, m1, calendar.monthrange(y1, m1)[1])
    occ_by = guest_nights_by_period(db, start, end)
    occ_total = occupancy_metrics(db, start, end)
    capacity = occ_total["capacity"] or 0

    stock_value = float(db.query(func.coalesce(func.sum(StockProduct.current_value), 0)).scalar() or 0)
    rate_row = (db.query(ExchangeRate.forex_selling).filter(ExchangeRate.currency_code == "EUR")
                .order_by(ExchangeRate.date.desc()).first())
    eur_rate = float(rate_row[0]) if rate_row and rate_row[0] else None

    # Aylık + eşleşen aylar
    monthly = []
    m_fb = m_gn = m_rooms = m_rn = 0.0
    for p in periods:
        fb = cons.get(p, {}).get("fb", 0.0)
        rooms = cons.get(p, {}).get("rooms", 0.0)
        gn = occ_by.get(p, {}).get("guest_nights", 0)
        rn = occ_by.get(p, {}).get("room_nights", 0)
        yy, mm = map(int, p.split("-"))
        cap_nights = capacity * calendar.monthrange(yy, mm)[1]
        occ_pct = round(rn / cap_nights * 100, 1) if cap_nights else 0.0
        matched = fb > 0 and gn > 0
        if matched:
            m_fb += fb; m_gn += gn; m_rooms += rooms; m_rn += rn
        monthly.append({
            "period": p, "fb_consumption": round(fb, 2), "guest_nights": gn, "room_nights": rn,
            "occupancy_pct": occ_pct,
            "cost_per_guest_night": round(fb / gn, 1) if gn else 0.0, "matched": matched,
        })

    cpgn_try = round(m_fb / m_gn, 2) if m_gn else 0.0
    cpor_try = round(m_rooms / m_rn, 2) if m_rn else 0.0
    waste = group_totals.get("waste", 0.0)

    return {
        "range": {"start": occ_total["start"], "end": occ_total["end"]},
        "occupancy": {
            "occupancy_pct": occ_total["occupancy_pct"], "room_nights": occ_total["room_nights"],
            "guest_nights": occ_total["guest_nights"], "capacity": capacity,
            "adr_eur": occ_total["adr_eur"], "revpar_eur": occ_total["revpar_eur"],
        },
        "consumption": {"total": total_consumption, "fb": group_totals.get("fb", 0.0),
                        "rooms": group_totals.get("rooms", 0.0), "staff": group_totals.get("staff", 0.0),
                        "technical": group_totals.get("technical", 0.0), "waste": waste},
        "kpi": {
            "cost_per_guest_night_try": cpgn_try,
            "cost_per_guest_night_eur": round(cpgn_try / eur_rate, 2) if eur_rate else None,
            "cpor_try": cpor_try,
            "staff_meal_total": group_totals.get("staff", 0.0),
            "waste_pct": round(waste / total_consumption * 100, 2) if total_consumption else 0.0,
            "inventory_turnover": round(total_consumption / stock_value, 2) if stock_value else 0.0,
            "matched_periods": [m["period"] for m in monthly if m["matched"]],
            "eur_rate": eur_rate,
        },
        "by_group": [{"group": g, "label": COST_GROUP_LABELS.get(g, g), "total": v}
                     for g, v in sorted(group_totals.items(), key=lambda x: -x[1])],
        "monthly": monthly,
    }


# Son alış MEDYANIN bu kat ÜstÜnde/altında ise → "gerçek fiyat hareketi" değil, olası
# birim/miktar tutarsızlığı (Sedna'da Birim hep "Kg" ama miktar bazen çuval/koli adedi →
# net÷miktar uçar). Net tutar daima doğru; sapan yalnız payda (miktar).
_PRICE_ANOMALY_RATIO = 3.0


def _price_variance_rows(db: Session) -> list:
    """Ürün başına satın alma birim-maliyet sapması — MEDYAN bazlı (aykırı girişe dayanıklı).

    **Birim fiyat = net_amount ÷ quantity** (gerçek ödenen). Sedna'nın `Cost` (unit_cost) alanı
    bazen hatalı/0 (ör. NAR'da tek satır 359,48 ama net/miktar=135) → onu KULLANMAYIZ; net tutar
    daima doğru olduğundan net÷miktar gerçek birim fiyatı verir. Bu, `Cost` hatasından doğan sahte
    "fiyat sıçramalarını" eler.

    Ortalama yerine medyan: tek bir hatalı giriş baz çizgisini kaydırmaz. Son alış medyanın
    `_PRICE_ANOMALY_RATIO` katından sapıyorsa `category="entry"` (olası birim/miktar hatası — burada
    net÷miktar da sapar çünkü payda/miktar yanlış girilmiştir), aksi halde `category="price"`.
    """
    rows = db.execute(text("""
        WITH mv AS (
            SELECT product_sedna_id AS pid, product_name AS name, date, id,
                   net_amount / quantity AS eff
            FROM stock_movements
            WHERE direction='in' AND quantity > 0 AND net_amount > 0
              AND product_sedna_id IS NOT NULL
        ),
        agg AS (
            SELECT pid, MAX(name) AS name,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY eff) AS median,
                   COUNT(*) AS n
            FROM mv
            GROUP BY pid
            HAVING COUNT(*) >= 2
        ),
        last AS (
            SELECT DISTINCT ON (pid) pid, eff AS last_cost
            FROM mv
            ORDER BY pid, date DESC NULLS LAST, id DESC
        )
        SELECT a.pid, a.name, a.median, a.n, l.last_cost
        FROM agg a JOIN last l ON l.pid = a.pid
        WHERE a.median > 0
    """)).fetchall()
    out = []
    for r in rows:
        median = float(r.median or 0)
        last = float(r.last_cost or 0)
        if median <= 0 or last <= 0:
            continue
        ratio = last / median
        is_entry = ratio > _PRICE_ANOMALY_RATIO or ratio < (1.0 / _PRICE_ANOMALY_RATIO)
        out.append({
            "product_id": r.pid, "name": r.name,
            "avg_cost": round(median, 2),     # geri uyum (artık medyan değeri)
            "median_cost": round(median, 2),
            "last_cost": round(last, 2),
            "variance_pct": round((last - median) / median * 100, 1),
            "purchase_count": int(r.n or 0),
            "category": "entry" if is_entry else "price",
        })
    return out


def compute_price_variance(db: Session, limit: Optional[int] = 20, include_zero: bool = False) -> list:
    """Gerçek satın alma fiyat hareketleri (medyan bazlı; birim/miktar anomalileri HARİÇ).

    Sıralama: **işaretli azalan** → fiyatı artanlar üstte (en çok artan en üstte), azalanlar
    altta. `include_zero=False` (varsayılan) → değişmeyen (variance_pct=0) ürünler "hareket"
    sayılmaz, listeye alınmaz; `include_zero=True` → %0'lar da dönülür (frontend toggle ile
    göster/gizle). `limit=None` → cap yok (tüm hareketler).
    """
    rows = [
        r for r in _price_variance_rows(db)
        if r["category"] == "price" and (include_zero or r["variance_pct"] != 0)
    ]
    rows.sort(key=lambda x: -x["variance_pct"])
    return rows[:limit]


def compute_price_anomalies(db: Session, limit: Optional[int] = 20) -> list:
    """Olası birim/miktar tutarsızlıkları (medyandan >3× sapan son alış) — Sedna giriş kalitesi."""
    rows = [r for r in _price_variance_rows(db) if r["category"] == "entry"]
    rows.sort(key=lambda x: -abs(x["variance_pct"]))
    return rows[:limit]


def get_product_purchases(db: Session, product_sedna_id: int, limit: int = 200) -> dict:
    """Bir ürünün alış (`direction='in'`) hareketleri — tarih/fiyat/miktar/tedarikçi kırılımı.

    Maliyet panelindeki fiyat-hareketi/anomali satırına tıklanınca açılan detay için. Net
    tutar daima doğru; birim fiyat = net/miktar (Sedna'da miktar paydası bazen tutarsız).
    """
    q = (
        db.query(StockMovement)
        .filter(
            StockMovement.direction == "in",
            StockMovement.product_sedna_id == product_sedna_id,
        )
        .order_by(StockMovement.date.desc().nullslast(), StockMovement.id.desc())
    )
    rows = q.limit(limit).all()
    name = next((r.product_name for r in rows if r.product_name), None)
    # Birim fiyat = net ÷ miktar (gerçek ödenen) — panel ile aynı baz
    costs = sorted(
        float(r.net_amount) / float(r.quantity)
        for r in rows
        if r.quantity and float(r.quantity) > 0 and r.net_amount and float(r.net_amount) > 0
    )
    median = 0.0
    if costs:
        mid = len(costs) // 2
        median = costs[mid] if len(costs) % 2 else (costs[mid - 1] + costs[mid]) / 2
    items = [
        {
            "id": r.id,
            "date": r.date.isoformat() if r.date else None,
            "quantity": float(r.quantity or 0),
            "unit_cost": round(float(r.unit_cost or 0), 4),
            "net_amount": round(float(r.net_amount or 0), 2),
            "supplier_name": r.supplier_name,
            "doc_no": r.doc_no,
            "entry_depot": r.entry_depot,
        }
        for r in rows
    ]
    return {
        "product_id": product_sedna_id,
        "name": name,
        "median_cost": round(median, 2),
        "count": len(items),
        "items": items,
    }
