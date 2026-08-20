"""Nakit akım grafiği — ardışık dönem serisi: tahsilatlar, ödemeler, banka bakiyesi (EUR).

Finans → Nakit Akım sayfasındaki grafiğin veri kaynağı (2026-08-19, kullanıcı isteği).
Panel T-Hesap cetveli (`t_account.py`) TEK bir dönemi iki kolonda gösterir; bu endpoint
AYNI kuralları kullanarak ARDIŞIK dönem serisi (gün/hafta/ay/yıl) üretir → çubuk grafik.

TEK SAYI KURALI — her kova, aynı (period, offset) için t-account ile birebir tutar:
    income_realized  + income_planned  == t-account `total_in_eur`
    expense_realized + expense_planned == t-account `total_out_eur`
    income_realized                     == t-account `realized_in_eur`
    expense_realized                    == t-account `realized_out_eur`
Bunu garanti etmek için dönem sınırları, EUR çevrimi, grup etiketi ve transfer/bilgi
kategorisi kuralları `t_account`'tan İMPORT edilir (kopyalanmaz — kopyalama FIN-001
sınıfı sessiz drift üretir). Regresyon: `backend/tests/test_cash_flow_chart.py`.

T-HESAP'TAN TEK FARK — VADESİ GEÇENLER: `t_account` gerçekleşmemiş + vadesi bugün/geçmiş
kalemleri listeden düşer (ayrı "Vadesi Geçenler" panelinde izlenir); grafik onları KENDİ
tarihlerinde AYRI seri olarak gösterir (kullanıcı isteği: "vadesi geride kalanlar burada
görünsün"). Bu seri `net_eur`e GİRMEZ ve bakiye eğrisini DÜŞÜRMEZ — "ödenmedi, para hâlâ
bankada" kuralı (`eur_balances` 2026-07-06 notu). Böylece grafik hem T-Hesap hem runway
ile çelişmez: aynı kalem ya akışta ya vadesi-geçende, asla iki yerde sayılmaz.

BEKLEMEYE ALINANLAR (hold): `*_held` ayrı döner, toplam/net dışıdır (T-Hesap ile aynı).
BİLGİ KATEGORİLERİ (POS Bloke Çözme / Döviz Satışı): `*_info` — hesaplar arası virman,
toplam dışı (T-Hesap `in_total=False` ile aynı).

BAKİYE EĞRİSİ burada DÖNMEZ: frontend `cashFlowCache.eurBalances.daily`den (RunwayChart +
PDF raporuyla aynı `compute_eur_balances` çekirdeği) kova sonundaki son bakiyeyi okur.
Sebep: `compute_eur_balances` ağır bir tam-tarama; sayfa onu zaten WS-geçersizlemeli
cache'te tutuyor → dönem sekmesi her değiştiğinde yeniden hesaplatmak israf olurdu.
ANLIK hesap bakiyeleri (`accounts`) ise buradan gelir — `bank_snapshot` tek kaynağı.
"""

import bisect
from datetime import date as date_cls
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import RateLimiter
from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    FinanceEvent,
)
from app.models.user import User
from app.utils.finance_helpers import MIN_DATE

from ._helpers import bank_snapshot
from .t_account import (
    INFO_CATEGORIES,
    TRANSFER_CATEGORIES,
    _eur_rate_for,
    _event_eur,
    _group_label,
    _period_range,
)

# Türkçe ay adları — sunucu locale'ine güvenilmez (report.py / runway.py ile aynı liste)
TR_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
TR_MONTHS_SHORT = [
    "Oca", "Şub", "Mar", "Nis", "May", "Haz",
    "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
]

# Dönem başına varsayılan pencere (geçmiş kova, gelecek kova). Nakit akımda GELECEK en az
# geçmiş kadar önemlidir (planlı ödeme/tahsilat) → pencere bugünün iki yanında simetrik.
DEFAULT_WINDOW = {
    "daily": (14, 14),    # 29 gün
    "weekly": (8, 8),     # 17 hafta
    "monthly": (6, 6),    # 13 ay
    "yearly": (2, 2),     # 5 yıl
}

# Yanıttaki en fazla kova — eksende okunabilirlik + tek sorgunun tarama sınırı
MAX_BUCKETS = 60

# Gezinme okları art arda istek üretir (t_account ile aynı gerekçe: heavy_limiter gezinmeyi
# boğuyordu). Grafik ayrıca dönem sekmesi başına bir istek atar → aynı geniş pencere.
chart_limiter = RateLimiter(max_requests=30, window_seconds=60)

router = APIRouter()


def _bucket_label(period: str, start: date_cls, end: date_cls) -> Tuple[str, str]:
    """(kısa eksen etiketi, uzun ipucu etiketi) — Türkçe, sunucu locale'inden bağımsız."""
    if period == "daily":
        short = "{} {}".format(start.day, TR_MONTHS_SHORT[start.month - 1])
        return short, "{} {} {}".format(start.day, TR_MONTHS[start.month - 1], start.year)
    if period == "weekly":
        if start.month == end.month:
            short = "{}–{} {}".format(start.day, end.day, TR_MONTHS_SHORT[start.month - 1])
        else:
            short = "{} {} – {} {}".format(
                start.day, TR_MONTHS_SHORT[start.month - 1],
                end.day, TR_MONTHS_SHORT[end.month - 1],
            )
        long = "{} {} – {} {} {}".format(
            start.day, TR_MONTHS[start.month - 1],
            end.day, TR_MONTHS[end.month - 1], end.year,
        )
        return short, long
    if period == "monthly":
        return (
            "{} {}".format(TR_MONTHS_SHORT[start.month - 1], str(start.year)[2:]),
            "{} {}".format(TR_MONTHS[start.month - 1], start.year),
        )
    return str(start.year), str(start.year)


def _new_bucket(period: str, offset: int, start: date_cls, end: date_cls, today: date_cls) -> dict:
    short, long = _bucket_label(period, start, end)
    return {
        "offset": offset,
        "key": start.isoformat(),
        "label": short,
        "label_long": long,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        # Kova bugünü içeriyor mu / tamamen geçmişte mi (frontend "bugün" işareti + soluklaştırma)
        "is_current": start <= today <= end,
        "is_past": end < today,
        # TAHSİLATLAR (giriş)
        "income_realized": 0.0,
        "income_planned": 0.0,
        "income_overdue": 0.0,
        "income_held": 0.0,
        "income_info": 0.0,
        # ÖDEMELER (çıkış)
        "expense_realized": 0.0,
        "expense_planned": 0.0,
        "expense_overdue": 0.0,
        "expense_held": 0.0,
        "expense_info": 0.0,
        # Kalem sayıları — ipucunda "12 kalem" gösterimi
        "income_count": 0,
        "expense_count": 0,
        "overdue_count": 0,
    }


@router.get("/cash-flow/chart")
def cash_flow_chart(
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|yearly)$"),
    back: Optional[int] = Query(None, ge=0, le=MAX_BUCKETS - 1, description="Geçmiş kova sayısı (boş=dönem varsayılanı)"),
    forward: Optional[int] = Query(None, ge=0, le=MAX_BUCKETS - 1, description="Gelecek kova sayısı (boş=dönem varsayılanı)"),
    offset: int = Query(0, ge=-120, le=24, description="Pencereyi kaydır: 0=bugünün dönemi ortada"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Dönem serisi nakit akım grafiği — tahsilat/ödeme kırılımı + anlık banka bakiyeleri."""
    chart_limiter.check("cashflow-chart-{}".format(current_user.id))

    today = date_cls.today()
    def_back, def_fwd = DEFAULT_WINDOW[period]
    n_back = def_back if back is None else back
    n_fwd = def_fwd if forward is None else forward
    # Toplam kova tavanı: önce gelecek, sonra geçmiş kırpılır (geçmiş "gerçekleşen" veriyi
    # taşır; kullanıcı pencereyi büyütürken geçmişi kaybetmemeli)
    if n_back + 1 + n_fwd > MAX_BUCKETS:
        n_fwd = max(0, MAX_BUCKETS - 1 - n_back)
        if n_back + 1 + n_fwd > MAX_BUCKETS:
            n_back = MAX_BUCKETS - 1
            n_fwd = 0

    buckets: List[dict] = []
    for off in range(offset - n_back, offset + n_fwd + 1):
        start, end = _period_range(period, off, today)
        buckets.append(_new_bucket(period, off, start, end, today))

    window_start = date_cls.fromisoformat(buckets[0]["start_date"])
    window_end = date_cls.fromisoformat(buckets[-1]["end_date"])
    # Kovalar ardışık ve bitişiktir (_period_range ardışık offset'lerde boşluk bırakmaz) →
    # bitiş tarihleri artan sıradadır, ikili arama ile kova bulunur.
    bucket_ends = [date_cls.fromisoformat(b["end_date"]) for b in buckets]

    def _bucket_index(dt: date_cls) -> Optional[int]:
        idx = bisect.bisect_left(bucket_ends, dt)
        if idx >= len(buckets):
            return None
        if dt < date_cls.fromisoformat(buckets[idx]["start_date"]):
            return None
        return idx

    # Tek sorgu — tüm pencere. Filtreler t_account ile birebir (is_matched=False, MIN_DATE
    # tabanı, transfer kategorileri hariç; NULL kategori or_ ile açıkça korunur).
    query_start = window_start if window_start > MIN_DATE else MIN_DATE
    events = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.is_matched == False,  # noqa: E712
            FinanceEvent.event_date >= MIN_DATE,
            FinanceEvent.event_date >= query_start,
            FinanceEvent.event_date <= window_end,
            or_(
                FinanceEvent.category_name.is_(None),
                ~FinanceEvent.category_name.in_(TRANSFER_CATEGORIES),
            ),
        )
        .order_by(FinanceEvent.event_date.asc(), FinanceEvent.id.asc())
        .all()
    )

    from app.services.hold_service import get_hold_set
    hold_set = get_hold_set(db)

    skipped_no_rate = 0
    rate_cache: Dict[Tuple[str, date_cls], Optional[float]] = {}

    for fe in events:
        if fe.direction not in (DIRECTION_INCOME, DIRECTION_EXPENSE):
            continue
        idx = _bucket_index(fe.event_date)
        if idx is None:
            continue
        eur = _event_eur(db, fe, rate_cache)
        if eur is None:
            skipped_no_rate += 1
            continue

        side = "income" if fe.direction == DIRECTION_INCOME else "expense"
        bucket = buckets[idx]

        # Bilgi kategorisi (hesaplar arası virman) → toplam dışı, ayrı sayaç
        if _group_label(fe) in INFO_CATEGORIES:
            bucket[side + "_info"] += eur
            continue

        # SIRA ÖNEMLİ (runway.py ile aynı): önce vadesi-geçen, sonra beklemeye-alınan.
        # Bekletme yalnız GELECEK vadeli kalem için anlamlıdır; vadesi geçmiş bekletilmiş
        # kalem yine "vadesi geçen"dir (aksi halde sessizce grafikten kaybolurdu).
        if not fe.is_realized and fe.event_date <= today:
            bucket[side + "_overdue"] += eur
            bucket["overdue_count"] += 1
            continue
        if not fe.is_realized and (fe.source_type, fe.source_id) in hold_set:
            bucket[side + "_held"] += eur
            continue

        bucket[side + ("_realized" if fe.is_realized else "_planned")] += eur
        bucket[side + "_count"] += 1

    # Tahmini kredi kartı ekstresi rezervi (yüklenmemiş cari ay = kart limiti) — T-Hesap,
    # EUR bakiye ve runway ile TEK kaynak (`due_reserve_projections`). Projeksiyon her zaman
    # BEKLEYEN rezervdir (gerçekleşmiş sayılmaz); kart bazında beklemeye alınmışsa held.
    from app.services.cc_projection_service import due_reserve_projections
    for proj in due_reserve_projections(db, today=today):
        due = date_cls.fromisoformat(proj["date"])
        idx = _bucket_index(due)
        if idx is None:
            continue
        rate = _eur_rate_for(db, due, rate_cache)
        if not rate:
            skipped_no_rate += 1
            continue
        eur = float(proj["amount"]) / rate
        card_id = proj.get("card_id")
        bucket = buckets[idx]
        if card_id is not None and ("cc_projection", card_id) in hold_set:
            bucket["expense_held"] += eur
        else:
            bucket["expense_planned"] += eur
            bucket["expense_count"] += 1

    # Kontrat taksitleri + beklenen ciro tahsilatı (#26-iii, okuma-anında servis; FE yazılmaz).
    # Vadesi GELECEK olanlar planlı tahsilat; vadesi GEÇMİŞ taksitler `runway.overdue_income`
    # ile aynı mantıkla "vadesi geçen tahsilat" serisine düşer (T-Hesap onları hiç göstermez —
    # grafikte görünmeleri kullanıcı isteğinin ta kendisi). Ciro kalemleri geçmişte
    # gösterilmez (gerçekleşen ciro banka tarafında zaten sayılır → çift sayım olurdu).
    from app.services.contract_projection_service import contract_inflow_projections
    contract_proj = contract_inflow_projections(db, today=today)
    contract_feed = (
        [(True, i) for i in contract_proj["installments"]]      # taksit → vadesi geçebilir
        + [(False, i) for i in contract_proj["ciro_items"]]     # ciro → yalnız gelecek
    )
    for can_be_overdue, item in contract_feed:
        item_date = date_cls.fromisoformat(item["date"])
        idx = _bucket_index(item_date)
        if idx is None:
            continue
        amount_eur = float(item["amount_eur"])
        bucket = buckets[idx]
        if item_date > today:
            bucket["income_planned"] += amount_eur
            bucket["income_count"] += 1
        elif can_be_overdue:
            bucket["income_overdue"] += amount_eur
            bucket["overdue_count"] += 1

    money_keys = (
        "income_realized", "income_planned", "income_overdue", "income_held", "income_info",
        "expense_realized", "expense_planned", "expense_overdue", "expense_held", "expense_info",
    )
    for bucket in buckets:
        for key in money_keys:
            bucket[key] = round(bucket[key], 2)
        bucket["income_total"] = round(bucket["income_realized"] + bucket["income_planned"], 2)
        bucket["expense_total"] = round(bucket["expense_realized"] + bucket["expense_planned"], 2)
        # Net: T-Hesap `net_eur` ile aynı tanım — vadesi geçen ve beklemedeki kalemler HARİÇ
        bucket["net_eur"] = round(bucket["income_total"] - bucket["expense_total"], 2)

    snapshot = bank_snapshot(db)

    return {
        "period": period,
        "offset": offset,
        "back": n_back,
        "forward": n_fwd,
        "today": today.isoformat(),
        "start_date": window_start.isoformat(),
        "end_date": window_end.isoformat(),
        "buckets": buckets,
        # ANLIK banka hesap tutarları — "Bankadaki Nakit" başlığı ve runway `start_eur` ile
        # aynı sayı (`bank_snapshot` tek kaynak)
        "accounts": snapshot["accounts"],
        "total_balance_eur": snapshot["total_eur"],
        "eur_rate": snapshot["eur_rate"],
        # Pencere geneli vadesi geçen toplamları (grafik üstü uyarı şeridi)
        "overdue_expense_eur": round(sum(b["expense_overdue"] for b in buckets), 2),
        "overdue_income_eur": round(sum(b["income_overdue"] for b in buckets), 2),
        "skipped_no_rate": skipped_no_rate,
    }
