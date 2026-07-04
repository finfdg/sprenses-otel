"""Kâr payı dağıtımı router yardımcıları — yanıt oluşturucular + N+1'siz özet istatistik."""

from typing import List, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.dividend import (
    DividendDistribution,
    DividendInstallment,
    DividendPayment,
    DividendShareholder,
)
from app.schemas.dividend import (
    DividendDistributionResponse,
    DividendInstallmentResponse,
    DividendPaymentResponse,
    DividendShareholderResponse,
)
from app.services.dividend_service import _derive_stopaj_date


def _empty_stats() -> dict:
    return {
        "total_stopaj": 0.0, "total_net": 0.0, "shareholder_count": 0,
        "net_paid_count": 0, "net_total_count": 0, "stopaj_paid_count": 0,
    }


def batch_rollup_stats(db: Session, distribution_ids: List[int]) -> dict:
    """Dağıtım başına özet — 3 gruplu sorgu (N+1 yok)."""
    stats = {did: _empty_stats() for did in distribution_ids}
    if not distribution_ids:
        return stats

    # Toplam stopaj/net = pay sahibi (Özet) görünümü → Excel Özet TOPLAM ile birebir
    # (taksit görünümü kuruş yuvarlamasıyla ~3 kuruş sapar; Excel'de de öyle).
    for did, cnt, s_stopaj, s_net in (
        db.query(
            DividendShareholder.distribution_id,
            func.count(DividendShareholder.id),
            func.coalesce(func.sum(DividendShareholder.stopaj_amount), 0),
            func.coalesce(func.sum(DividendShareholder.net_dividend), 0),
        )
        .filter(DividendShareholder.distribution_id.in_(distribution_ids))
        .group_by(DividendShareholder.distribution_id)
    ):
        stats[did]["shareholder_count"] = int(cnt)
        stats[did]["total_stopaj"] = float(s_stopaj)
        stats[did]["total_net"] = float(s_net)

    for did, total, net_paid, stopaj_paid in (
        db.query(
            DividendPayment.distribution_id,
            func.count(DividendPayment.id),
            func.coalesce(func.sum(case((DividendPayment.is_paid, 1), else_=0)), 0),
            func.coalesce(func.sum(case((DividendPayment.stopaj_paid, 1), else_=0)), 0),
        )
        .filter(DividendPayment.distribution_id.in_(distribution_ids))
        .group_by(DividendPayment.distribution_id)
    ):
        stats[did]["net_total_count"] = int(total)
        stats[did]["net_paid_count"] = int(net_paid)
        stats[did]["stopaj_paid_count"] = int(stopaj_paid)

    return stats


def build_distribution_response(
    dist: DividendDistribution, stats: dict, creator_name: Optional[str] = None,
) -> dict:
    """Üst düzey dağıtım yanıtı (çocuksuz — liste için)."""
    return DividendDistributionResponse(
        id=dist.id,
        name=dist.name,
        decision_date=dist.decision_date,
        total_gross=float(dist.total_gross),
        capital=float(dist.capital) if dist.capital is not None else None,
        withholding_rate=float(dist.withholding_rate),
        installment_count=dist.installment_count,
        year=dist.year,
        status=dist.status,
        notes=dist.notes,
        created_by=dist.created_by,
        creator_name=creator_name,
        created_at=dist.created_at,
        updated_at=dist.updated_at,
        total_stopaj=stats["total_stopaj"],
        total_net=stats["total_net"],
        shareholder_count=stats["shareholder_count"],
        net_paid_count=stats["net_paid_count"],
        net_total_count=stats["net_total_count"],
        stopaj_paid_count=stats["stopaj_paid_count"],
    ).model_dump()


def _shareholder_resp(s: DividendShareholder) -> dict:
    return DividendShareholderResponse(
        id=s.id, sort_order=s.sort_order, name=s.name,
        share_value=float(s.share_value), share_ratio=float(s.share_ratio),
        gross_dividend=float(s.gross_dividend), stopaj_amount=float(s.stopaj_amount),
        net_dividend=float(s.net_dividend),
    ).model_dump()


def build_detail_response(
    dist: DividendDistribution, stats: dict, creator_name: Optional[str],
    shareholders: List[DividendShareholder], installments: List[DividendInstallment],
    payments: List[DividendPayment],
) -> dict:
    """Detay yanıtı — sahipler + taksitler (roll-up) + 72 ödeme (shareholder_name)."""
    resp = build_distribution_response(dist, stats, creator_name)

    sh_by_id = {s.id: s for s in shareholders}
    inst_by_id = {i.id: i for i in installments}

    # Taksit başına ödeme grupları
    by_inst: dict = {i.id: [] for i in installments}
    for p in payments:
        by_inst.setdefault(p.installment_id, []).append(p)

    inst_resps = []
    for inst in installments:
        rows = by_inst.get(inst.id, [])
        total = len(rows)
        net_paid = sum(1 for r in rows if r.is_paid)
        stopaj_paid = sum(1 for r in rows if r.stopaj_paid)
        inst_resps.append(DividendInstallmentResponse(
            id=inst.id, installment_no=inst.installment_no, due_date=inst.due_date,
            label=inst.label, gross_amount=float(inst.gross_amount),
            stopaj_amount=float(inst.stopaj_amount), net_amount=float(inst.net_amount),
            stopaj_due_date=_derive_stopaj_date(inst.due_date),
            paid_count=net_paid, total_count=total,
            net_paid=total > 0 and net_paid == total,
            stopaj_paid=total > 0 and stopaj_paid == total,
        ).model_dump())

    pay_resps = []
    for p in payments:
        sh = sh_by_id.get(p.shareholder_id)
        inst = inst_by_id.get(p.installment_id)
        pay_resps.append(DividendPaymentResponse(
            id=p.id, distribution_id=p.distribution_id, installment_id=p.installment_id,
            shareholder_id=p.shareholder_id,
            shareholder_name=sh.name if sh else None,
            installment_no=inst.installment_no if inst else None,
            gross_amount=float(p.gross_amount), stopaj_amount=float(p.stopaj_amount),
            net_amount=float(p.net_amount), is_paid=p.is_paid, paid_date=p.paid_date,
            stopaj_paid=p.stopaj_paid, stopaj_paid_date=p.stopaj_paid_date, notes=p.notes,
        ).model_dump())

    resp["shareholders"] = [_shareholder_resp(s) for s in shareholders]
    resp["installments"] = inst_resps
    resp["payments"] = pay_resps
    return resp


def payment_response(p: DividendPayment, shareholder_name: Optional[str] = None,
                     installment_no: Optional[int] = None) -> dict:
    return DividendPaymentResponse(
        id=p.id, distribution_id=p.distribution_id, installment_id=p.installment_id,
        shareholder_id=p.shareholder_id, shareholder_name=shareholder_name,
        installment_no=installment_no,
        gross_amount=float(p.gross_amount), stopaj_amount=float(p.stopaj_amount),
        net_amount=float(p.net_amount), is_paid=p.is_paid, paid_date=p.paid_date,
        stopaj_paid=p.stopaj_paid, stopaj_paid_date=p.stopaj_paid_date, notes=p.notes,
    ).model_dump()
