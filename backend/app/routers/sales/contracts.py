"""Kontratlar modülü (sales.kontratlar) — acente kontrat arşivi + metadata CRUD.

16 tur operatörünün sözleşme/dönem/ödeme planı/aksiyon/kontenjan/kesinti kayıtları.
Mutasyon mantığı `services/contract_service.py`'de ORTAK (D1-2) — onay executor'ı
(`_handle_sales_kontratlar`) aynı fonksiyonları çağırır. Alt varlık mutasyonları tek
`kind` parametresiyle yönetilir; onay payload'ı `_kind` alanı taşır.

Belge yükleme/indirme onay akışı DIŞI (dosya endpoint istisnası, CLAUDE.md) ama
audit'li ve broadcast'li.
"""
import math
import os
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query,
    Request, UploadFile, status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.agency_group import AgencyGroup
from app.models.contract import (
    ALL_DOC_TYPES, INSTALLMENT_PENDING, PLAN_TYPE_GUARANTEE_CHECK, AgencyContract,
    ContractAction, ContractDocument, ContractInstallment, ContractPaymentPlan,
)
from app.models.user import User
from app.schemas.contract import (
    ActionCreate, ActionTierCreate, AllotmentCreate, ChildPolicyCreate,
    ContractCreate, ContractUpdate, DeductionCreate, DocumentMetaUpdate,
    InstallmentCreate, PaymentPlanCreate, PeriodCreate, RateCreate,
    RoomTypeMapCreate,
)
from app.services import contract_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.file_validation import validate_upload_file
from app.utils.sales_broadcast import broadcast_sales_update

MODULE_CODE = "sales.kontratlar"

# kind → create şeması (PATCH'te de aynı şema partial kullanılır — exclude_unset)
_KIND_SCHEMAS = {
    "periods": PeriodCreate,
    "room-types": RoomTypeMapCreate,
    "plans": PaymentPlanCreate,
    "installments": InstallmentCreate,
    "actions": ActionCreate,
    "tiers": ActionTierCreate,
    "allotments": AllotmentCreate,
    "deductions": DeductionCreate,
    "rates": RateCreate,
    "child-policies": ChildPolicyCreate,
}

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "uploads", "contract_files")

router = APIRouter(prefix="/kontratlar", tags=["Kontratlar"])


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─── Yanıt kurucular ────────────────────────────────────

def _row(c: AgencyContract, group_names: dict) -> dict:
    """Liste satırı — hafif alanlar + taksit özetleri.

    guarantee_check planları (otelin VERDİĞİ teminat — gelir değil) ve kontrat para
    biriminden farklı taksitler bekleyen-toplam dışında tutulur (karışık PB toplanamaz)."""
    pending = [i for p in c.payment_plans for i in p.installments
               if p.plan_type != PLAN_TYPE_GUARANTEE_CHECK
               and i.status == INSTALLMENT_PENDING and i.amount
               and i.currency == c.currency]
    return {
        "id": c.id,
        "agency_group_id": c.agency_group_id,
        "agency_group_name": group_names.get(c.agency_group_id),
        "code": c.code,
        "title": c.title,
        "season_code": c.season_code,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_to": c.valid_to.isoformat() if c.valid_to else None,
        "currency": c.currency,
        "status": c.status,
        "data_confidence": c.data_confidence,
        "pricing_model": c.pricing_model,
        "invoice_due_basis": c.invoice_due_basis,
        "invoice_due_days": c.invoice_due_days,
        "release_days_default": c.release_days_default,
        "markets": c.markets or [],
        "exclusive_markets": c.exclusive_markets or [],
        "plan_count": len(c.payment_plans),
        "action_count": len(c.actions),
        "document_count": len(c.documents),
        "pending_installment_total": round(sum(float(i.amount) for i in pending), 2),
        "pending_installment_count": len(pending),
    }


def _child_dict(obj) -> dict:
    """Alt varlık satırı — kolonları otomatik serileştir (date → ISO)."""
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if isinstance(v, date):
            v = v.isoformat()
        elif v is not None and col.type.__class__.__name__ == "Numeric":
            v = float(v)
        out[col.name] = v
    return out


def _detail(c: AgencyContract, group_names: dict) -> dict:
    d = _row(c, group_names)
    d.update({
        "legal_counterparty": c.legal_counterparty,
        "signed_date": c.signed_date.isoformat() if c.signed_date else None,
        "fx_rule": c.fx_rule,
        "fx_fixed_rate": float(c.fx_fixed_rate) if c.fx_fixed_rate is not None else None,
        "board_default": c.board_default,
        "min_stay_default": c.min_stay_default,
        "closed_markets": c.closed_markets or [],
        "supersedes_contract_id": c.supersedes_contract_id,
        "sedna_contrack_ids": c.sedna_contrack_ids or [],
        "notes": c.notes,
        "periods": [_child_dict(p) for p in c.periods],
        "room_types": [_child_dict(r) for r in c.room_types],
        "payment_plans": [
            {**_child_dict(p), "installments": [_child_dict(i) for i in p.installments]}
            for p in c.payment_plans
        ],
        "actions": [
            {**_child_dict(a), "tiers": [_child_dict(t) for t in a.tiers]}
            for a in c.actions
        ],
        "allotments": [_child_dict(a) for a in c.allotments],
        "deductions": [_child_dict(x) for x in c.deductions],
        "documents": [_child_dict(x) for x in c.documents],
    })
    return d


def _group_names(db: Session) -> dict:
    return {g.id: g.name for g in db.query(AgencyGroup).all()}


# ─── Liste + özet ───────────────────────────────────────

@router.get("/")
def list_contracts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    group_id: Optional[int] = Query(None),
    season: Optional[str] = Query(None, max_length=20),
    status_f: Optional[str] = Query(None, alias="status", max_length=20),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Kontrat listesi — grup/sezon/durum filtreli, sayfalı."""
    q = db.query(AgencyContract).options(
        selectinload(AgencyContract.payment_plans)
        .selectinload(ContractPaymentPlan.installments),
        selectinload(AgencyContract.actions),
        selectinload(AgencyContract.documents),
    )
    if group_id:
        q = q.filter(AgencyContract.agency_group_id == group_id)
    if season:
        q = q.filter(AgencyContract.season_code == season)
    if status_f:
        q = q.filter(AgencyContract.status == status_f)
    total = q.count()
    items = (q.order_by(AgencyContract.season_code.desc(), AgencyContract.code)
             .offset((page - 1) * page_size).limit(page_size).all())
    names = _group_names(db)
    return {
        "items": [_row(c, names) for c in items],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }


@router.get("/actions-calendar")
def actions_calendar(
    start: date = Query(..., description="Pencere başlangıcı (ISO)"),
    end: date = Query(..., description="Pencere bitişi (ISO)"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Aksiyon/SPO takvimi — pencereyle kesişen confirmed aksiyon bantları.

    Grafik overlay'leri ve takvim görünümü için: satış penceresi (booking) VEYA
    konaklama bantları (stay/tiers) verilen aralıkla kesişen aksiyonlar döner.
    """
    if end < start:
        raise HTTPException(status_code=400, detail="Bitiş, başlangıçtan önce olamaz")
    acts = (
        db.query(ContractAction)
        .join(AgencyContract, ContractAction.contract_id == AgencyContract.id)
        .filter(ContractAction.status == "confirmed",
                AgencyContract.status == "active")
        .options(selectinload(ContractAction.tiers))
        .all()
    )
    names = _group_names(db)
    contracts = {c.id: c for c in db.query(AgencyContract).all()}
    out = []
    for a in acts:
        c = contracts.get(a.contract_id)
        # Kesişim: satış penceresi ya da herhangi bir konaklama bandı aralığa değmeli
        windows = []
        if a.sales_start or a.sales_end:
            windows.append((a.sales_start or start, a.sales_end or end))
        for t in a.tiers:
            if t.stay_start or t.stay_end:
                windows.append((t.stay_start or start, t.stay_end or end))
        if windows and not any(ws <= end and (we is None or we >= start)
                               for ws, we in windows):
            continue
        out.append({
            "action_id": a.id,
            "contract_code": c.code if c else None,
            "group_name": names.get(c.agency_group_id) if c else None,
            "action_type": a.action_type,
            "title": a.title,
            "sales_start": a.sales_start.isoformat() if a.sales_start else None,
            "sales_end": a.sales_end.isoformat() if a.sales_end else None,
            "open_ended": a.open_ended,
            "basis": a.basis,
            "combinable": a.combinable,
            "data_confidence": a.data_confidence,
            "tiers": [{
                "stay_start": t.stay_start.isoformat() if t.stay_start else None,
                "stay_end": t.stay_end.isoformat() if t.stay_end else None,
                "discount_percent": float(t.discount_percent) if t.discount_percent is not None else None,
                "fixed_net_price": float(t.fixed_net_price) if t.fixed_net_price is not None else None,
            } for t in a.tiers],
        })
    out.sort(key=lambda x: (x["group_name"] or "", x["sales_start"] or ""))
    return {"items": out, "start": start.isoformat(), "end": end.isoformat()}


@router.get("/price-audit")
def price_audit(
    start: date = Query(...),
    end: date = Query(...),
    tolerance: float = Query(3.0, ge=0.5, le=20.0, description="Sapma eşiği (%)"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Fiyat/kural denetimi (Faz 4a) — rate matrisi OLMADAN çalışan kontroller.

    Rezervasyonlar Sedna Contrack eşlemesiyle kontrata bağlanır ve denetlenir:
    (1) para birimi uyumsuzluğu, (2) dönem-boşluğu (checkin kontrat geçerliliğinde ama
    hiçbir fiyat dönemine düşmüyor), (3) min-stay ihlali, (4) Contrack-içi fiyat
    tutarlılığı — aynı (dönem × oda tipi × doluluk) grubunda gecelik ham fiyat
    (net_amount/nights, SÖZLEŞME para biriminde — EUR çevrimi DEĞİL) medyandan
    tolerans üstü sapanlar (SPO etkisi olabilir → bilgi amaçlı). Rate matrisi (Faz 4b)
    girildiğinde kontrat-fiyat karşılaştırması bu motora eklenir (`rate_rows` sayısı
    yanıtın counts'unda — 0 ise karşılaştırma atlanmıştır).
    """
    from statistics import median
    from collections import defaultdict as _dd
    from app.models.reservation import Reservation
    from app.models.contract import ContractRate

    if end < start or (end - start).days > 500:
        raise HTTPException(status_code=400, detail="Geçersiz pencere (en çok 500 gün)")

    contracts = (
        db.query(AgencyContract)
        .filter(AgencyContract.status == "active",
                AgencyContract.sedna_contrack_ids.isnot(None))
        .options(selectinload(AgencyContract.periods))
        .all()
    )
    names = _group_names(db)
    ck_to_contract = {}
    for c in contracts:
        for ck in (c.sedna_contrack_ids or []):
            ck_to_contract[ck] = c

    rez = (
        db.query(Reservation)
        .filter(Reservation.sedna_contrack_id.isnot(None),
                Reservation.checkin_date >= start,
                Reservation.checkin_date <= end)
        .all()
    )

    findings = []
    counts = _dd(int)
    price_groups = _dd(list)

    for r in rez:
        c = ck_to_contract.get(r.sedna_contrack_id)
        if not c:
            counts["unmapped_contrack"] += 1
            continue
        counts["checked"] += 1
        base = {
            "voucher": r.voucher, "agency": r.agency, "checkin": r.checkin_date.isoformat(),
            "contract_code": c.code, "group_name": names.get(c.agency_group_id),
        }
        # (1) Para birimi
        if r.currency and c.currency and r.currency != c.currency:
            counts["currency_mismatch"] += 1
            findings.append({**base, "type": "currency_mismatch",
                             "detail": f"Rezervasyon {r.currency}, kontrat {c.currency}"})
        # (2) Dönem boşluğu + (3) min-stay — KAPSAMA KORUMASI: dönem verisi sezonun
        # %70'inden azını kapsıyorsa (ör. AllTours taranmış kontratta yalnız P1 bantları
        # okunabildi) period_gap YANLIŞ-POZİTİF üretir → o kontratta bu kontrol atlanır.
        period = None
        if c.periods:
            for p in c.periods:
                if p.date_start <= r.checkin_date <= p.date_end:
                    period = p
                    break
            coverage_ok = True
            if c.valid_from and c.valid_to:
                season_days = (c.valid_to - c.valid_from).days + 1
                covered = sum((p.date_end - p.date_start).days + 1 for p in c.periods)
                coverage_ok = season_days > 0 and covered / season_days >= 0.7
            if not coverage_ok:
                counts["period_check_skipped_low_coverage"] += 1
            else:
                in_validity = ((not c.valid_from or r.checkin_date >= c.valid_from)
                               and (not c.valid_to or r.checkin_date <= c.valid_to))
                if period is None and in_validity:
                    counts["period_gap"] += 1
                    findings.append({**base, "type": "period_gap",
                                     "detail": "Checkin kontrat geçerliliğinde ama hiçbir fiyat dönemine düşmüyor"})
        min_stay = (period.min_stay if period and period.min_stay is not None
                    else c.min_stay_default)
        if min_stay and (r.nights or 0) < min_stay and (r.nights or 0) > 0:
            counts["min_stay_violation"] += 1
            findings.append({**base, "type": "min_stay_violation",
                             "detail": f"{r.nights} gece < min {min_stay} gece"})
        # (4) İç tutarlılık grubu (ham fiyat, sözleşme PB — kur oynaklığından bağımsız)
        if r.net_amount and r.nights:
            key = (c.code, period.code if period else "-", r.room_type, r.board,
                   r.adult, r.child_paid, r.child_free)
            price_groups[key].append((float(r.net_amount) / r.nights, r))

    deviation_findings = []
    for key, rows in price_groups.items():
        if len(rows) < 3:
            continue
        med = median(p for p, _ in rows)
        if med <= 0:
            continue
        for p, r in rows:
            dev = abs(p - med) / med * 100.0
            if dev > tolerance:
                counts["price_deviation"] += 1
                c = ck_to_contract[r.sedna_contrack_id]
                deviation_findings.append((dev, {
                    "voucher": r.voucher, "agency": r.agency,
                    "checkin": r.checkin_date.isoformat(),
                    "contract_code": key[0], "group_name": names.get(c.agency_group_id),
                    "type": "price_deviation",
                    "detail": (f"Gecelik {p:,.0f} {r.currency} — grup medyanı {med:,.0f} "
                               f"(%{dev:.1f} sapma; dönem {key[1]}, {key[2]}, "
                               f"{key[4]}+{key[5]}p; EB kademesi/SPO etkisi olabilir — "
                               f"aksiyon motoru Faz 4b'de netleşir)"),
                }))
    # En büyük sapmalar önce; tip başına makul kırpma (rapor okunur kalsın)
    deviation_findings.sort(key=lambda x: -x[0])
    findings = findings[:150] + [f for _, f in deviation_findings[:100]]

    counts["rate_rows"] = db.query(func.count(ContractRate.id)).scalar() or 0
    return {"start": start.isoformat(), "end": end.isoformat(),
            "tolerance_pct": tolerance, "counts": dict(counts), "findings": findings}


@router.get("/deductions-forecast")
def deductions_forecast(
    year: int = Query(..., ge=2024, le=2030),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Sezon sonu kickback/kesinti TAHMİNİ (Faz 3) — mutabakat masasına hazırlık.

    Grup cirosu (çıkış yılı EUR, rezervasyonlardan) üzerine contract_deductions
    uygulanır: fatura-başı % doğrudan, baremli sezon-sonu kalemler ciroyu kapsayan
    baremden, sabit tutarlar aynen. Salt-okuma — operatör bildirimiyle karşılaştırma
    için 'beklenen kesinti' dökümü.
    """
    from sqlalchemy import extract
    from app.models.reservation import Reservation
    from app.models.contract import ContractDeduction

    groups = db.query(AgencyGroup).all()
    members_by_gid = {g.id: [(m or "").strip().upper() for m in (g.members or [])]
                      for g in groups}

    names = _group_names(db)
    contracts = (
        db.query(AgencyContract)
        .filter(AgencyContract.status == "active")
        .options(selectinload(AgencyContract.deductions))
        .all()
    )

    def _contract_ciro(c: AgencyContract) -> float:
        """Kontratın cirosu — önce Sedna Contrack eşlemesiyle (isabetli: aynı grubun
        iki kontratı — ör. ODEON iç pazar vs uluslararası — birbirinin cirosunu
        saymaz); Contrack eşlemesi yoksa grup üyeleri + kontrat geçerlilik aralığı."""
        q = db.query(func.coalesce(func.sum(Reservation.eur_total), 0)).filter(
            extract("year", Reservation.checkout_date) == year)
        if c.sedna_contrack_ids:
            q = q.filter(Reservation.sedna_contrack_id.in_(c.sedna_contrack_ids))
        else:
            members = members_by_gid.get(c.agency_group_id, [])
            if not members:
                return 0.0
            q = q.filter(Reservation.agency.in_(members))
            if c.valid_from:
                q = q.filter(Reservation.checkout_date >= c.valid_from)
            if c.valid_to:
                q = q.filter(Reservation.checkout_date <= c.valid_to)
        return float(q.scalar() or 0)

    out = []
    for c in contracts:
        if not c.deductions:
            continue
        # Kontrat yılı kapsaması: valid aralığı yıl ile kesişmeli
        if c.valid_from and c.valid_from.year > year:
            continue
        if c.valid_to and c.valid_to.year < year:
            continue
        ciro = round(_contract_ciro(c), 2)
        lines = []
        total = 0.0
        for d in c.deductions:
            amt = None
            basis = ""
            if d.percent is not None:
                pct = float(d.percent)
                if d.tier_from is not None or d.tier_to is not None:
                    lo = float(d.tier_from or 0)
                    hi = float(d.tier_to) if d.tier_to is not None else None
                    in_tier = ciro >= lo and (hi is None or ciro <= hi)
                    if not in_tier:
                        continue  # ciro bu bareme düşmüyor
                    basis = f"barem {lo:,.0f}–{'∞' if hi is None else f'{hi:,.0f}'}"
                amt = round(ciro * pct / 100.0, 2)
                basis = (basis + f" · %{pct} × ciro").strip(" ·")
            elif d.fixed_amount is not None:
                amt = round(float(d.fixed_amount), 2)
                basis = f"sabit tutar ({d.currency or 'EUR'})"
            if amt is None:
                continue
            total += amt
            lines.append({
                "deduction_type": d.deduction_type,
                "applies": d.applies,
                "percent": float(d.percent) if d.percent is not None else None,
                "amount_eur": amt if (d.currency or "EUR") == "EUR" else None,
                "amount_native": amt,
                "currency": d.currency or "EUR",
                "basis": basis,
                "settlement_month": d.settlement_month,
                "notes": d.notes,
            })
        if lines:
            out.append({
                "contract_code": c.code,
                "group_name": names.get(c.agency_group_id),
                "season_code": c.season_code,
                "ciro_eur": ciro,
                "data_confidence": c.data_confidence,
                "lines": lines,
                "total_estimate": round(total, 2),
            })
    out.sort(key=lambda x: -x["ciro_eur"])
    return {"year": year, "items": out}


@router.get("/allotment-usage")
def allotment_usage(
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Kontenjan × satılan karşılaştırması (Faz 3) — kritik taahhüt takibi.

    Pencere içindeki her gün için grup rezervasyonlarının dolu oda sayısı hesaplanır;
    kontratın toplam kontenjanıyla kıyaslanır (ortalama/maks kullanım, aşım günleri).
    Taahhüt uyarıları: guaranteed_share_percent (AllTours %80 stop-sale'siz,
    Pegas/Roket %70) — kullanım bu eşiğin altındaysa bilgi, üstündeyse риск yok.
    """
    from app.models.reservation import Reservation
    from app.models.contract import ContractAllotment

    if end < start or (end - start).days > 400:
        raise HTTPException(status_code=400, detail="Geçersiz pencere (en çok 400 gün)")

    groups = db.query(AgencyGroup).all()
    names = _group_names(db)
    contracts = (
        db.query(AgencyContract)
        .filter(AgencyContract.status == "active")
        .options(selectinload(AgencyContract.allotments))
        .all()
    )
    members_by_gid = {g.id: [(m or "").strip().upper() for m in (g.members or [])]
                      for g in groups}

    out = []
    for c in contracts:
        allots = [a for a in c.allotments if a.room_count]
        if not allots:
            continue
        # Pencereyi kontrat geçerliliğiyle kes
        w0 = max(start, c.valid_from) if c.valid_from else start
        w1 = min(end, c.valid_to) if c.valid_to else end
        if w1 < w0:
            continue
        # Rezervasyon seçimi: önce Sedna Contrack eşlemesi (aynı grubun iki kontratı
        # birbirinin odalarını saymasın); yoksa grup üyeleri fallback
        rq = db.query(Reservation.checkin_date, Reservation.checkout_date,
                      Reservation.rooms).filter(
            Reservation.checkin_date <= w1, Reservation.checkout_date > w0)
        if c.sedna_contrack_ids:
            rq = rq.filter(Reservation.sedna_contrack_id.in_(c.sedna_contrack_ids))
        else:
            members = members_by_gid.get(c.agency_group_id, [])
            if not members:
                continue
            rq = rq.filter(Reservation.agency.in_(members))
        rez = rq.all()
        days = (w1 - w0).days + 1
        sold = [0] * days
        for ci, co, rooms in rez:
            a = max(ci, w0)
            b = min(co, w1 + timedelta(days=1))
            for off in range((b - a).days):
                idx = (a - w0).days + off
                if 0 <= idx < days:
                    sold[idx] += int(rooms or 1)
        total_allot = sum(a.room_count for a in allots
                          if a.allotment_type != "free_sale")
        if total_allot <= 0:
            continue
        avg_sold = sum(sold) / days if days else 0
        max_sold = max(sold) if sold else 0
        over_days = sum(1 for s in sold if s > total_allot)
        guaranteed = max((float(a.guaranteed_share_percent)
                          for a in allots if a.guaranteed_share_percent), default=None)
        out.append({
            "contract_code": c.code,
            "group_name": names.get(c.agency_group_id),
            "season_code": c.season_code,
            "window_start": w0.isoformat(),
            "window_end": w1.isoformat(),
            "allotment_rooms": total_allot,
            "avg_sold": round(avg_sold, 1),
            "max_sold": max_sold,
            "utilization_pct": round(100.0 * avg_sold / total_allot, 1),
            "peak_pct": round(100.0 * max_sold / total_allot, 1),
            "days_over_allotment": over_days,
            "guaranteed_share_percent": guaranteed,
            "data_confidence": c.data_confidence,
        })
    out.sort(key=lambda x: -x["utilization_pct"])
    return {"start": start.isoformat(), "end": end.isoformat(), "items": out}


@router.get("/summary")
def contracts_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Stat kartları: aktif kontrat, bekleyen taksit toplamı, 30 gün içi vade, geciken.

    Yalnız EUR taksitler toplanır (karışık para birimi tek sayıya indirgenmez) ve
    guarantee_check planları hariçtir — onlar otelin VERDİĞİ teminat, beklenen gelir değil."""
    today = date.today()
    active = (db.query(func.count(AgencyContract.id))
              .filter(AgencyContract.status == "active").scalar() or 0)
    inst = (
        db.query(ContractInstallment)
        .join(ContractPaymentPlan, ContractInstallment.plan_id == ContractPaymentPlan.id)
        .filter(ContractPaymentPlan.plan_type != PLAN_TYPE_GUARANTEE_CHECK,
                ContractInstallment.status == INSTALLMENT_PENDING,
                ContractInstallment.amount.isnot(None),
                ContractInstallment.currency == "EUR",
                ContractInstallment.due_date.isnot(None))
        .all()
    )
    pending_total = round(sum(float(i.amount) for i in inst), 2)
    due_30 = round(sum(float(i.amount) for i in inst
                       if today <= i.due_date and (i.due_date - today).days <= 30), 2)
    overdue = round(sum(float(i.amount) for i in inst if i.due_date < today), 2)
    overdue_count = sum(1 for i in inst if i.due_date < today)
    conditional_pending = round(sum(float(i.amount) for i in inst if i.is_conditional), 2)
    return {
        "active_contracts": int(active),
        "pending_installment_total": pending_total,
        "due_next_30d": due_30,
        "overdue_total": overdue,
        "overdue_count": overdue_count,
        "conditional_pending": conditional_pending,
    }


@router.get("/{contract_id}")
def get_contract_detail(
    contract_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    c = contract_service.get_contract(db, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")
    return _detail(c, _group_names(db))


# ─── Kontrat CRUD ───────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_contract(
    data: ContractCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Yeni kontrat oluştur."""
    if not db.query(AgencyGroup).filter(AgencyGroup.id == data.agency_group_id).first():
        raise HTTPException(status_code=404, detail="Acente grubu bulunamadı")

    approval_resp = check_approval(
        db, MODULE_CODE, 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    try:
        c = contract_service.create_contract(db, data.model_dump())
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400,
                            detail=f"Bu kontrat kodu zaten kayıtlı: {data.code}")

    log_action(db, current_user.id, "create", "agency_contract", entity_id=c.id,
               details=f"{c.code} — {c.season_code}", ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "create")
    fresh = contract_service.get_contract(db, c.id)
    return _detail(fresh, _group_names(db))


@router.patch("/{contract_id}")
def update_contract(
    contract_id: int,
    data: ContractUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    c = db.query(AgencyContract).filter(AgencyContract.id == contract_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    payload = data.model_dump(exclude_unset=True)
    approval_resp = check_approval(
        db, MODULE_CODE, contract_id, current_user.id, "update", payload)
    if approval_resp:
        return approval_resp

    try:
        contract_service.apply_contract_update(db, c, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Bu kontrat kodu zaten kayıtlı")

    log_action(db, current_user.id, "update", "agency_contract", entity_id=c.id,
               details=f"{c.code} — {c.season_code}", ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "update")
    fresh = contract_service.get_contract(db, contract_id)
    return _detail(fresh, _group_names(db))


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(
    contract_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    c = db.query(AgencyContract).filter(AgencyContract.id == contract_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    approval_resp = check_approval(
        db, MODULE_CODE, contract_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    code = c.code
    try:
        contract_service.delete_contract(db, c)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "delete", "agency_contract", entity_id=contract_id,
               details=code, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "delete")


# ─── Alt varlık CRUD (kind-tabanlı) ─────────────────────

def _validate_kind(kind: str):
    if kind not in _KIND_SCHEMAS:
        raise HTTPException(status_code=404,
                            detail=f"Bilinmeyen alt varlık türü: {kind}")


@router.post("/{contract_id}/children/{kind}", status_code=status.HTTP_201_CREATED)
def create_child(
    contract_id: int,
    kind: str,
    body: dict,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Kontrata alt varlık ekle (dönem/oda-eşleme/plan/taksit/aksiyon/band/kontenjan/kesinti)."""
    _validate_kind(kind)
    if not db.query(AgencyContract).filter(AgencyContract.id == contract_id).first():
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    data = _KIND_SCHEMAS[kind](**body).model_dump()

    approval_resp = check_approval(
        db, MODULE_CODE, 0, current_user.id, "create",
        {"_kind": kind, "_contract_id": contract_id, **data})
    if approval_resp:
        return approval_resp

    try:
        obj = contract_service.create_child(db, kind, contract_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "create", f"contract_{kind}", entity_id=obj.id,
               details=f"kontrat #{contract_id}", ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "create")
    return _child_dict(obj)


@router.patch("/children/{kind}/{child_id}")
def update_child(
    kind: str,
    child_id: int,
    body: dict,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    _validate_kind(kind)
    obj = contract_service.get_child(db, kind, child_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")

    # Partial update: mevcut kayıt + gönderilenler create şemasından geçirilir
    # (tam doğrulama), sonra yalnız gönderilen alanlar uygulanır.
    schema = _KIND_SCHEMAS[kind]
    merged = {**_child_dict(obj), **body}
    merged.pop("id", None)
    try:
        validated = schema(**merged).model_dump()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Geçersiz alan değeri: {e}")
    data = {k: v for k, v in validated.items() if k in body}

    approval_resp = check_approval(
        db, MODULE_CODE, child_id, current_user.id, "update",
        {"_kind": kind, **data})
    if approval_resp:
        return approval_resp

    try:
        contract_service.apply_child_update(db, kind, obj, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_action(db, current_user.id, "update", f"contract_{kind}", entity_id=child_id,
               details=None, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "update")
    return _child_dict(obj)


@router.delete("/children/{kind}/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_child(
    kind: str,
    child_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    _validate_kind(kind)
    obj = contract_service.get_child(db, kind, child_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")

    approval_resp = check_approval(
        db, MODULE_CODE, child_id, current_user.id, "delete", {"_kind": kind})
    if approval_resp:
        return approval_resp

    try:
        contract_service.delete_child(db, kind, obj)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "delete", f"contract_{kind}", entity_id=child_id,
               details=None, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "delete")


# ─── Belge arşivi (onay akışı DIŞI — dosya istisnası; audit + broadcast VAR) ───

@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    agency_group_id: int = Form(...),
    contract_id: Optional[int] = Form(None),
    doc_type: str = Form("other"),
    doc_date: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Kontrat belgesi yükle (PDF/Excel) — arşive kaydeder, istenirse kontrata bağlar."""
    if doc_type not in ALL_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Geçersiz belge türü: {doc_type}")
    if not db.query(AgencyGroup).filter(AgencyGroup.id == agency_group_id).first():
        raise HTTPException(status_code=404, detail="Acente grubu bulunamadı")
    if contract_id:
        c = db.query(AgencyContract).filter(AgencyContract.id == contract_id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Kontrat bulunamadı")
        # Çapraz tutarlılık: belge, kontratın grubundan farklı gruba kaydedilemez
        if c.agency_group_id != agency_group_id:
            raise HTTPException(
                status_code=400,
                detail="Kontrat farklı bir acente grubuna ait — grup ile kontrat uyuşmuyor")

    content = await validate_upload_file(file, allowed_types=["pdf", "excel"])
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()

    _ensure_upload_dir()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as f:
        f.write(content)

    doc = contract_service.create_document(
        db, agency_group_id, file_path, (file.filename or unique_name)[:255],
        doc_type, current_user.id, contract_id, doc_date, notes)

    log_action(db, current_user.id, "create", "contract_document", entity_id=doc.id,
               details=doc.original_name, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "create")
    return _child_dict(doc)


@router.get("/documents/{doc_id}/download")
def download_document(
    doc_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).first()
    if not doc or not os.path.isfile(doc.file_path):
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    return FileResponse(doc.file_path, filename=doc.original_name,
                        headers={"Content-Disposition":
                                 f'attachment; filename="{doc.original_name}"'})


@router.patch("/documents/{doc_id}")
def update_document_meta(
    doc_id: int,
    data: DocumentMetaUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Belge metadata güncelle (kontrata bağlama, tür, tarih) — dosya istisnası kapsamı."""
    doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    payload = data.model_dump(exclude_unset=True)
    if payload.get("contract_id"):
        c = db.query(AgencyContract).filter(
            AgencyContract.id == payload["contract_id"]).first()
        if not c:
            raise HTTPException(status_code=404, detail="Kontrat bulunamadı")
        # Çapraz tutarlılık: belge yalnız kendi grubunun kontratına bağlanabilir
        if c.agency_group_id != doc.agency_group_id:
            raise HTTPException(
                status_code=400,
                detail="Kontrat, belgenin acente grubundan farklı — bağlanamaz")

    contract_service.apply_document_meta(db, doc, payload)
    log_action(db, current_user.id, "update", "contract_document", entity_id=doc.id,
               details=doc.original_name, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "update")
    return _child_dict(doc)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Belgeyi sil — dosya diskten de kaldırılır (audit'li)."""
    doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    name, path = doc.original_name, doc.file_path
    db.delete(doc)
    log_action(db, current_user.id, "delete", "contract_document", entity_id=doc_id,
               details=name, ip_address=get_client_ip(request))
    db.commit()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass  # dosya silinemese de DB kaydı gitti — yetim dosya zararsız
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "delete")
