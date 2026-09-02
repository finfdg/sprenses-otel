"""Acente bazında kişi başı fiyat ortalamaları — Rezervasyonlar sekmesi kartı (2026-09-02).

Kullanıcı isteği: "ay ay acenta bazında kişi başı fiyat ortalamalarını göstersin, liste şeklinde
en pahalıdan en ucuza". Metrik **kişi-gece başına ortalama EUR** (ADR'nin kişi bazlı hali):

    pp_night = Σ (aya düşen ciro) / Σ (aya düşen ödeyen kişi-gece)

- Ay dağıtımı STAY-NIGHT bazlıdır (`generate_series`, `eur_total / nights` gece başına) —
  "Aylık Doluluk Dağılımı" kartı ve `occupancy-overview` ile birebir aynı yöntem; iki kart
  aynı ayın cirosunu farklı göstermez.
- Ödeyen kişi = `adult + child_paid` (ücretsiz çocuk + bebek fiyatı düşürmesin). Ödeyen kişisi
  olmayan (0) veya `nights=0` satırlar ortalamaya GİRMEZ (pay + payda birlikte atlanır; aksi
  halde ciro paydasız kalıp diğerlerini şişirirdi). Sedna'nın `per_adult` alanı (eur_total /
  adult, konaklama başına, çocuğu saymaz) bu yüzden kullanılmaz.
- Acente satırı = **acente grubu** (`agency_groups`, Acenteler sekmesiyle aynı gruplama);
  gruba bağlı olmayan PMS acenteleri kendi adıyla ayrı satırdır (gizlenmez).
- Önceki yılın aynı ayı da döner (`prev_pp_night`) — kart "Karşılaştır" modunda gösterir.
Salt-okunur GET → onay akışı kapsam dışı; `sales.acente_mahsup` view.
"""

from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional, Tuple

import pytz
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.services.agency_settlement_service import _OTHER_ID, _agency_group_maps, _norm

router = APIRouter()

_TZ_ISTANBUL = pytz.timezone("Europe/Istanbul")
_UNGROUPED_COLOR = "#a09a88"  # gray-400 — gruba bağlı olmayan acente (tema token'ı)

_MONTH_AGENCY_SQL = text("""
    SELECT
        EXTRACT(MONTH FROM gs)::int                                   AS m,
        COALESCE(r.agency, '')                                         AS agency,
        COALESCE(SUM(r.eur_total / r.nights), 0)::float                AS eur,
        COALESCE(SUM(r.adult + r.child_paid), 0)::int                  AS pax_nights,
        COUNT(DISTINCT r.id)::int                                      AS rez
    FROM reservations r
    JOIN LATERAL generate_series(
        r.checkin_date::timestamp,
        (r.checkout_date - INTERVAL '1 day')::timestamp,
        INTERVAL '1 day'
    ) AS gs ON TRUE
    WHERE EXTRACT(YEAR FROM gs) = :year
      AND r.nights > 0
      AND (r.adult + r.child_paid) > 0
    GROUP BY m, agency
""")


def _rows_by_key(db: Session, year: int, member_to_gid: dict) -> Dict[Tuple[int, str], dict]:
    """(ay, satır anahtarı) → {eur, pax_nights, rez, members:set}. Anahtar: 'g:<gid>' grup,
    'a:<PMS adı>' gruba bağlı olmayan acente."""
    out: Dict[Tuple[int, str], dict] = {}
    for m, agency, eur, pax_nights, rez in db.execute(_MONTH_AGENCY_SQL, {"year": year}):
        gid = member_to_gid.get(_norm(agency), _OTHER_ID)
        key = f"g:{gid}" if gid != _OTHER_ID else f"a:{_norm(agency) or '?'}"
        slot = out.setdefault((int(m), key), {"eur": 0.0, "pax_nights": 0, "rez": 0, "members": set()})
        slot["eur"] += float(eur or 0)
        slot["pax_nights"] += int(pax_nights or 0)
        slot["rez"] += int(rez or 0)
        slot["members"].add(_norm(agency) or "?")
    return out


def _row_meta(key: str, gmeta: dict) -> dict:
    if key.startswith("g:"):
        g = gmeta.get(int(key[2:])) or {}
        return {"name": g.get("name") or "?", "color": g.get("color") or _UNGROUPED_COLOR, "is_group": True}
    return {"name": key[2:], "color": _UNGROUPED_COLOR, "is_group": False}


def _build_rows(slots: Dict[str, dict], prev: Dict[str, dict], gmeta: dict) -> list:
    rows = []
    for key, s in slots.items():
        if s["pax_nights"] <= 0:
            continue
        p = prev.get(key)
        rows.append({
            "key": key,
            **_row_meta(key, gmeta),
            "member_count": len(s["members"]),
            "pp_night": round(s["eur"] / s["pax_nights"], 2),
            "pax_nights": s["pax_nights"],
            "revenue": round(s["eur"], 2),
            "rez": s["rez"],
            "prev_pp_night": (round(p["eur"] / p["pax_nights"], 2)
                              if p and p["pax_nights"] > 0 else None),
        })
    # En pahalıdan en ucuza; eşitlikte ciro büyük olan önce, sonra ad
    rows.sort(key=lambda r: (-r["pp_night"], -r["revenue"], r["name"]))
    return rows


def _summary(slots: Dict[str, dict]) -> dict:
    eur = sum(s["eur"] for s in slots.values())
    pax = sum(s["pax_nights"] for s in slots.values())
    return {
        "pp_night": round(eur / pax, 2) if pax > 0 else None,
        "pax_nights": pax,
        "revenue": round(eur, 2),
        "rez": sum(s["rez"] for s in slots.values()),
        "agency_count": sum(1 for s in slots.values() if s["pax_nights"] > 0),
    }


@router.get("/agency-pp-prices")
def agency_pp_prices(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("sales.acente_mahsup", "view")),
):
    """Ay × acente kişi-gece fiyat ortalamaları (EUR), her ayda pahalıdan ucuza sıralı;
    ayrıca yıl toplamı ve önceki yılın aynı ay değeri (`prev_pp_night`)."""
    today = datetime.now(_TZ_ISTANBUL).date()
    y = year or today.year
    gmeta, member_to_gid = _agency_group_maps(db)

    cur = _rows_by_key(db, y, member_to_gid)
    prv = _rows_by_key(db, y - 1, member_to_gid)

    def _month_slots(data, m):
        return {key: s for (mm, key), s in data.items() if mm == m}

    def _year_slots(data):
        agg: Dict[str, dict] = defaultdict(lambda: {"eur": 0.0, "pax_nights": 0, "rez": 0, "members": set()})
        for (_m, key), s in data.items():
            a = agg[key]
            a["eur"] += s["eur"]
            a["pax_nights"] += s["pax_nights"]
            a["rez"] += s["rez"]
            a["members"] |= s["members"]
        return agg

    months = []
    for m in range(1, 13):
        cs = _month_slots(cur, m)
        ps = _month_slots(prv, m)
        months.append({
            "month": m,
            "agencies": _build_rows(cs, ps, gmeta),
            **_summary(cs),
            "prev_pp_night": _summary(ps)["pp_night"],
        })

    ys, yps = _year_slots(cur), _year_slots(prv)
    return {
        "year": y,
        "prev_year": y - 1,
        "today": today.isoformat(),
        "months": months,
        "year_totals": {
            "agencies": _build_rows(ys, yps, gmeta),
            **_summary(ys),
            "prev_pp_night": _summary(yps)["pp_night"],
        },
    }
