"""Kâr payı dağıtımı (temettü) domain servis katmanı — HTTP'siz mutasyon mantığı.

D1-2 deseni: dağıtım/ödeme mutasyon mantığı TEK kaynakta. Hem router endpoint'leri
(`accounting/dividend/*`) hem onay executor handler'ı (`_handle_accounting_dividend`)
AYNI fonksiyonları çağırır → router↔executor sapması yapısal olarak engellenir.

Üretim: dağıtım başlığı + pay sahibi listesinden (ad + pay değeri) pay oranı/brüt/stopaj/net
hesaplanır, N taksit ve pay-sahibi × taksit (72) ödeme satırı üretilir. Para hesabı Python
`Decimal` + ROUND_HALF_UP ile yapılır, 2 hane saklanır. Yuvarlama artığı brütte en büyük
pay sahibine, taksit-içi dağıtımda son taksite absorbe edilir (Excel paritesi).

Nakit akım: her taksit için 2 finance_event — net (source 'dividend', taksit günü) + stopaj
(source 'dividend_stopaj', ertesi ay muhtasar 26'sı). Durum pay-sahibi ödemelerinden roll-up.
"""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.dividend import (
    DividendDistribution,
    DividendInstallment,
    DividendPayment,
    DividendShareholder,
)
from app.models.finance_event import SOURCE_DIVIDEND, SOURCE_DIVIDEND_STOPAJ
from app.utils.finance_event_service import finance_event_svc


# ─── Yardımcılar ─────────────────────────────────────────────────────

def _coerce_date(v):
    """Onay yolu payload_json'ı tarihleri string yapar (json.dumps default=str);
    router yolu date objesi geçirir. Her ikisini de date'e normalize et."""
    if isinstance(v, str) and v:
        return date.fromisoformat(v[:10])
    return v


def _q2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q6(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _derive_stopaj_date(due_date: date) -> date:
    """Stopaj muhtasar ödeme günü — taksit vadesini izleyen ayın 26'sı."""
    y, m = due_date.year, due_date.month
    if m == 12:
        y, m = y + 1, 1
    else:
        m += 1
    return date(y, m, 26)


def _month_ends(first: date, count: int) -> List[date]:
    """first'in ayından başlayarak ardışık ay-sonu tarihleri (Excel taksit deseni)."""
    dates: List[date] = []
    y, m = first.year, first.month
    for _ in range(count):
        last_day = calendar.monthrange(y, m)[1]
        dates.append(date(y, m, last_day))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return dates


def _resolve_due_dates(data: dict, count: int) -> List[date]:
    raw = data.get("installment_dates")
    if raw:
        dates = [_coerce_date(d) for d in raw]
        if len(dates) != count:
            raise ValueError("Taksit tarihleri sayısı taksit sayısıyla eşleşmeli")
        return dates
    first = _coerce_date(data.get("first_installment_date"))
    if not first:
        raise ValueError("Taksit tarihleri veya ilk taksit tarihi gerekli")
    return _month_ends(first, count)


def _installment_rollup(db: Session, installment_id: int) -> tuple:
    """Taksitin ödeme satırları üzerinden (all_net_paid, all_stopaj_paid, net_paid, stopaj_paid, total)."""
    total, net_paid, stopaj_paid = db.query(
        func.count(DividendPayment.id),
        func.coalesce(func.sum(case((DividendPayment.is_paid, 1), else_=0)), 0),
        func.coalesce(func.sum(case((DividendPayment.stopaj_paid, 1), else_=0)), 0),
    ).filter(DividendPayment.installment_id == installment_id).one()
    total = int(total or 0)
    net_paid = int(net_paid or 0)
    stopaj_paid = int(stopaj_paid or 0)
    all_net = total > 0 and net_paid == total
    all_stopaj = total > 0 and stopaj_paid == total
    return all_net, all_stopaj, net_paid, stopaj_paid, total


def _upsert_installment_events(db: Session, installment: DividendInstallment, distribution: DividendDistribution) -> None:
    """Taksitin net + stopaj finance_event'lerini roll-up durumuyla tazele."""
    all_net, all_stopaj, _, _, _ = _installment_rollup(db, installment.id)
    finance_event_svc.upsert_dividend_net(db, installment, distribution, all_net)
    if float(installment.stopaj_amount or 0) > 0:
        finance_event_svc.upsert_dividend_stopaj(
            db, installment, distribution, _derive_stopaj_date(installment.due_date), all_stopaj,
        )
    else:
        # Stopaj yoksa hayalet olay bırakma
        finance_event_svc.invalidate(db, SOURCE_DIVIDEND_STOPAJ, installment.id)


# ─── Ortak CRUD mutasyonları (router + onay executor ORTAK) ──────────

def create_distribution(db: Session, data: dict, actor_id) -> DividendDistribution:
    """Dağıtım + pay sahipleri + taksitler + 72 ödeme + finance_events üret. Döner: dağıtım.

    Geçersiz girdi → ValueError (router 400'e, executor rollback'e çevirir)."""
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Dağıtım adı gerekli")
    total_gross = Decimal(str(data.get("total_gross") or 0))
    if total_gross <= 0:
        raise ValueError("Dağıtılacak kâr payı 0'dan büyük olmalı")
    rate = Decimal(str(data.get("withholding_rate", 0.15)))
    if rate >= 1:  # yüzde girildiyse (15 → 0.15) orana çevir
        rate = rate / Decimal("100")
    count = int(data.get("installment_count") or 1)
    if count < 1:
        raise ValueError("Taksit sayısı en az 1 olmalı")
    year = int(data.get("year") or date.today().year)
    capital_raw = data.get("capital")
    capital = Decimal(str(capital_raw)) if capital_raw not in (None, "") else None
    shareholders_in = data.get("shareholders") or []
    if not shareholders_in:
        raise ValueError("En az 1 pay sahibi gerekli")

    # Oran denominatörü: capital yalnız pay değerleri toplamına eşitse; değilse toplam
    sum_share = sum((Decimal(str(s.get("share_value") or 0)) for s in shareholders_in), Decimal("0"))
    denom = capital if (capital is not None and capital == sum_share) else sum_share
    if denom <= 0:
        raise ValueError("Pay değerleri toplamı 0 olamaz")

    dist = DividendDistribution(
        name=name,
        decision_date=_coerce_date(data.get("decision_date")),
        total_gross=total_gross,
        capital=capital,
        withholding_rate=rate,
        installment_count=count,
        year=year,
        status="active",
        notes=data.get("notes"),
        created_by=actor_id,
    )
    db.add(dist)
    db.flush()

    # ── Pay sahipleri (brüt/stopaj/net) ──
    # Her pay sahibinin figürü kendi oranının kuruşa yuvarlanmış hâlidir (Excel paritesi;
    # Excel de reconcile ETMEZ — 12 satırın toplamı headerdan ~1 kuruş sapabilir, aynen korunur).
    sh_models: List[DividendShareholder] = []
    for idx, s in enumerate(shareholders_in):
        sv = Decimal(str(s.get("share_value") or 0))
        gross = _q2(total_gross * (sv / denom))
        stopaj = _q2(gross * rate)
        sh = DividendShareholder(
            distribution_id=dist.id,
            sort_order=idx + 1,
            name=(s.get("name") or "").strip(),
            share_value=sv,
            share_ratio=_q6(sv / denom),
            gross_dividend=gross,
            stopaj_amount=stopaj,
            net_dividend=_q2(gross - stopaj),
        )
        sh_models.append(sh)
        db.add(sh)
    db.flush()

    # ── Taksitler (tutarlar ödemelerden türetilecek) ──
    due_dates = _resolve_due_dates(data, count)
    inst_models: List[DividendInstallment] = []
    for i in range(count):
        inst = DividendInstallment(
            distribution_id=dist.id,
            installment_no=i + 1,
            due_date=due_dates[i],
            label=due_dates[i].strftime("%d.%m.%Y"),
            gross_amount=0, stopaj_amount=0, net_amount=0,
        )
        inst_models.append(inst)
        db.add(inst)
    db.flush()

    # ── 72 ödeme (sahip × taksit); son taksit sahip-artığını absorbe eder ──
    inst_totals = [[Decimal("0"), Decimal("0"), Decimal("0")] for _ in range(count)]  # gross, stopaj, net
    for sh in sh_models:
        sh_gross = Decimal(str(sh.gross_dividend))
        per = _q2(sh_gross / count)
        allocated = Decimal("0")
        for i in range(count):
            if i == count - 1:
                g = _q2(sh_gross - allocated)
            else:
                g = per
                allocated += per
            st = _q2(g * rate)
            nt = _q2(g - st)
            db.add(DividendPayment(
                distribution_id=dist.id,
                installment_id=inst_models[i].id,
                shareholder_id=sh.id,
                gross_amount=g, stopaj_amount=st, net_amount=nt,
            ))
            inst_totals[i][0] += g
            inst_totals[i][1] += st
            inst_totals[i][2] += nt

    # Taksit toplamlarını ödemelerden türet → Σ(payment) == installment invaryantı garanti
    for i in range(count):
        inst_models[i].gross_amount = inst_totals[i][0]
        inst_models[i].stopaj_amount = inst_totals[i][1]
        inst_models[i].net_amount = inst_totals[i][2]
    db.flush()

    for inst in inst_models:
        _upsert_installment_events(db, inst, dist)

    return dist


def apply_distribution_update(db: Session, dist: DividendDistribution, update_data: dict) -> None:
    """Yalnız metadata güncelle (name/decision_date/status/notes). status→cancelled tüm
    finance_event'leri kaldırır; cancelled→active geri getirir. Finansal regen YOK."""
    old_status = dist.status
    for key, value in update_data.items():
        if key == "decision_date":
            value = _coerce_date(value)
        if key == "name" and value:
            value = value.strip()
        setattr(dist, key, value)
    db.flush()
    new_status = dist.status
    if old_status != new_status:
        if new_status == "cancelled":
            for inst in dist.installments:
                finance_event_svc.invalidate(db, SOURCE_DIVIDEND, inst.id)
                finance_event_svc.invalidate(db, SOURCE_DIVIDEND_STOPAJ, inst.id)
        elif old_status == "cancelled":
            for inst in dist.installments:
                _upsert_installment_events(db, inst, dist)


def apply_payment_update(db: Session, payment: DividendPayment, update_data: dict) -> None:
    """Ödeme satırının net/stopaj ödendi durumunu uygula + tarih damgala + taksit olaylarını roll-up et."""
    data = dict(update_data)
    for dk in ("paid_date", "stopaj_paid_date"):
        if dk in data:
            data[dk] = _coerce_date(data[dk])
    for key, value in data.items():
        setattr(payment, key, value)
    # Otomatik tarih damgası
    if "is_paid" in data:
        if payment.is_paid and not payment.paid_date:
            payment.paid_date = date.today()
        elif not payment.is_paid and "paid_date" not in data:
            payment.paid_date = None
    if "stopaj_paid" in data:
        if payment.stopaj_paid and not payment.stopaj_paid_date:
            payment.stopaj_paid_date = date.today()
        elif not payment.stopaj_paid and "stopaj_paid_date" not in data:
            payment.stopaj_paid_date = None
    db.flush()

    inst = db.get(DividendInstallment, payment.installment_id)
    dist = db.get(DividendDistribution, payment.distribution_id)
    if inst and dist:
        _upsert_installment_events(db, inst, dist)


def delete_distribution(db: Session, dist: DividendDistribution) -> None:
    """Dağıtımı sil — önce taksit finance_event'lerini invalidate et (CASCADE çocukları siler)."""
    for inst in dist.installments:
        finance_event_svc.invalidate(db, SOURCE_DIVIDEND, inst.id)
        finance_event_svc.invalidate(db, SOURCE_DIVIDEND_STOPAJ, inst.id)
    db.delete(dist)
