"""Sedna Mutabakat (accounting.mutabakat) — Uyuşmayan Veriler.

Banka ↔ Sedna 102 defteri uyuşmazlık takibi. Kural: banka verisi HER ZAMAN otorite;
Sedna sonradan girilince kayıt otomatik kapanır. Mutasyon mantığı
`services/sedna_recon_service`'te (onay executor'ı da AYNI fonksiyonları çağırır).

Onay kapsamı: kullanıcı-tetikli kayıt aksiyonları (PATCH) check_approval'lıdır;
`POST /run` taraması veri mutasyonu değil sınıflandırma olduğundan onaydan MUAF
(dosya-yükleme istisnası sınıfı — docs/modules/sedna-mutabakat.md).
"""
import io
import json
import math
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.constants import BroadcastModule, ReconStatus
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip, heavy_limiter
from app.models import BankAccount, SednaBankRecon, SednaReconRun
from app.models.user import User
from app.schemas.sedna_recon import (
    AccountMappingUpdate,
    AgencyMappingUpdate,
    CreditMappingUpdate,
    PeriodLockUpdate,
    ReconItemAction,
    ReconRunRequest,
)
from app.services import sedna_recon_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.sedna_client import SednaUnavailable

router = APIRouter(tags=["Sedna Mutabakat"])

_SORT_COLUMNS = {
    "event_date": SednaBankRecon.event_date,
    "amount": SednaBankRecon.amount,
    "status": SednaBankRecon.status,
    "detected_at": SednaBankRecon.detected_at,
}

# PDF raporu — frontend STATUS_LABELS/RESOLUTION_LABELS ile birebir aynı etiketler
_STATUS_LABELS_TR = {
    ReconStatus.MATCHED: "Mutabık",
    ReconStatus.SEDNA_PENDING: "Sedna Bekliyor",
    ReconStatus.SEDNA_MISSING: "Sedna'da Eksik",
    ReconStatus.SEDNA_EXTRA: "Sedna'da Fazla",
    ReconStatus.DIRECTION_FLIP: "Yön Ters",
    ReconStatus.DUPLICATE_SUSPECT: "Mükerrer Şüphesi",
    ReconStatus.SEDNA_DIFF: "Sedna Sapması",
    ReconStatus.BALANCE_DIFF: "Bakiye Farkı",
}
_RESOLUTION_LABELS_TR = {"manual": "Elle çözüldü", "ignored": "Yoksayıldı", "auto": "Otomatik kapandı"}
_ENTITY_LABELS_TR = {"bank": "Banka", "check": "Çek", "vendor_tx": "Cari", "vendor_balance": "Cari Bakiye"}
_CURRENCY_SYMBOLS = {"TRY": "₺", "EUR": "€", "USD": "$", "GBP": "£"}
_PDF_MAX_ROWS = 1500  # tek PDF'e basılacak azami satır (aşımı raporda açıkça belirtilir)


def _apply_item_filters(query, status: Optional[str], account_id: Optional[int],
                        entity_type: Optional[str], include_closed: bool, q: Optional[str]):
    """Uyuşmazlık liste filtreleri — /items ve /items/pdf AYNI kümeyi görsün diye ortak."""
    if not include_closed:
        query = query.filter(SednaBankRecon.resolved_at.is_(None))
    if status:
        query = query.filter(SednaBankRecon.status == status)
    if account_id:
        query = query.filter(SednaBankRecon.bank_account_id == account_id)
    if entity_type == "bank":
        # Banka satırları entity_type taşımaz (NULL) — 'bank' takma değeri onları seçer
        query = query.filter(SednaBankRecon.entity_type.is_(None))
    elif entity_type:
        query = query.filter(SednaBankRecon.entity_type == entity_type)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            SednaBankRecon.description.ilike(like),
            SednaBankRecon.sedna_description.ilike(like),
        ))
    return query


def _fmt_pdf_amount(value: float, currency: Optional[str]) -> str:
    """İşaretli, Türkçe binlik/ondalık ayraçlı tutar (ekrandaki fmtAmount ile aynı biçim)."""
    cur = currency or ""
    sym = _CURRENCY_SYMBOLS.get(cur, f"{cur} " if cur else "")
    v = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if value < 0 else '+'}{sym}{v}"


def _item_dict(r: SednaBankRecon, account_name: Optional[str]) -> dict:
    return {
        "id": r.id,
        "bank_account_id": r.bank_account_id,
        "account_name": account_name,
        "entity_type": r.entity_type,
        "entity_id": r.entity_id,
        "bank_transaction_id": r.bank_transaction_id,
        "sedna_trans_rec_id": r.sedna_trans_rec_id,
        "sedna_voucher": r.sedna_voucher,
        "status": r.status,
        "amount": float(r.amount) if r.amount is not None else 0,
        "currency": r.currency,
        "event_date": r.event_date.isoformat() if r.event_date else None,
        "description": r.description,
        "sedna_description": r.sedna_description,
        "sedna_record_user": r.sedna_record_user,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "resolution": r.resolution,
        "resolution_note": r.resolution_note,
    }


@router.get("/summary")
def recon_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Özet: açık durum sayıları + son koşu + hesap eşleme kapsamı."""
    status_rows = (
        db.query(SednaBankRecon.status, func.count(SednaBankRecon.id))
        .filter(SednaBankRecon.resolved_at.is_(None))
        .group_by(SednaBankRecon.status)
        .all()
    )
    by_status = {s: c for s, c in status_rows}
    oldest = (
        db.query(func.min(SednaBankRecon.event_date))
        .filter(SednaBankRecon.resolved_at.is_(None))
        .scalar()
    )
    last_run = db.query(SednaReconRun).order_by(SednaReconRun.id.desc()).first()
    total_accounts = db.query(BankAccount).filter(BankAccount.is_active == True).count()  # noqa: E712
    mapped_accounts = (
        db.query(BankAccount)
        .filter(BankAccount.is_active == True,  # noqa: E712
                BankAccount.sedna_account_code.isnot(None),
                BankAccount.sedna_code_confirmed == True)  # noqa: E712
        .count()
    )
    from app.services.period_lock_service import get_lock_date
    lock = get_lock_date(db)
    return {
        "lock_date": lock.isoformat() if lock else None,
        "open_by_status": by_status,
        "open_total": sum(by_status.values()),
        "oldest_open_date": oldest.isoformat() if oldest else None,
        "mapped_accounts": mapped_accounts,
        "total_accounts": total_accounts,
        "last_run": {
            "run_at": last_run.run_at.isoformat() if last_run.run_at else None,
            "window_start": last_run.window_start.isoformat(),
            "window_end": last_run.window_end.isoformat(),
            "accounts_scanned": last_run.accounts_scanned,
            "matched_count": last_run.matched_count,
            "open_count": last_run.open_count,
            "new_count": last_run.new_count,
            "auto_closed_count": last_run.auto_closed_count,
            "note": last_run.note,
        } if last_run else None,
    }


@router.get("/items")
def list_items(
    status: Optional[str] = Query(default=None, pattern="^[a-z_]+$"),
    account_id: Optional[int] = None,
    entity_type: Optional[str] = Query(default=None, pattern="^(bank|check|vendor_tx|vendor_balance)$"),
    include_closed: bool = False,
    q: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="event_date", pattern="^(event_date|amount|status|detected_at)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Uyuşmazlık listesi (varsayılan: yalnız açık kayıtlar)."""
    query = _apply_item_filters(db.query(SednaBankRecon), status, account_id,
                                entity_type, include_closed, q)

    total = query.count()
    col = _SORT_COLUMNS[sort_by]
    query = query.order_by(col.desc() if sort_dir == "desc" else col.asc(), SednaBankRecon.id.desc())
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    acc_names = {a.id: a.bank_name for a in db.query(BankAccount).all()}
    return {
        "items": [_item_dict(r, acc_names.get(r.bank_account_id)) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }


@router.get("/items/pdf")
def items_pdf(
    status: Optional[str] = Query(default=None, pattern="^[a-z_]+$"),
    account_id: Optional[int] = None,
    entity_type: Optional[str] = Query(default=None, pattern="^(bank|check|vendor_tx|vendor_balance)$"),
    include_closed: bool = False,
    q: Optional[str] = None,
    sort_by: str = Query(default="event_date", pattern="^(event_date|amount|status|detected_at)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Uyuşmazlık listesi PDF raporu — ekrandaki filtrelerle AYNI kayıt kümesi.

    Salt-okuma GET → onaydan muaf. Sayfalama yok: filtreye uyan tüm kayıtlar
    (_PDF_MAX_ROWS tavanıyla; aşım raporda açıkça yazılır) tek belgeye basılır.
    """
    heavy_limiter.check(f"mutabakat-pdf-{current_user.id}")

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    from app.utils.pdf_fonts import register_turkish_fonts

    query = _apply_item_filters(db.query(SednaBankRecon), status, account_id,
                                entity_type, include_closed, q)
    total = query.count()
    col = _SORT_COLUMNS[sort_by]
    rows = (
        query.order_by(col.desc() if sort_dir == "desc" else col.asc(), SednaBankRecon.id.desc())
        .limit(_PDF_MAX_ROWS)
        .all()
    )
    acc_names = {a.id: a.bank_name for a in db.query(BankAccount).all()}

    base_font, bold_font = register_turkish_fonts()
    today = date_cls.today()

    # Uygulanan filtrelerin insan-okur özeti (rapor başlığı altına)
    filter_parts = []
    if status:
        filter_parts.append(f"Durum: {_STATUS_LABELS_TR.get(status, status)}")
    if account_id:
        filter_parts.append(f"Hesap: {acc_names.get(account_id, f'#{account_id}')}")
    if entity_type:
        filter_parts.append(f"Tür: {_ENTITY_LABELS_TR.get(entity_type, entity_type)}")
    if q and q.strip():
        filter_parts.append(f"Arama: “{q.strip()}”")
    filter_parts.append("Kapalılar dahil" if include_closed else "Yalnız açık kayıtlar")
    filter_txt = " · ".join(filter_parts)

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=landscape(A4),
        topMargin=12 * mm, bottomMargin=12 * mm, leftMargin=12 * mm, rightMargin=12 * mm,
    )
    title_style = ParagraphStyle("t", fontName=bold_font, fontSize=14, spaceAfter=4)
    sub_style = ParagraphStyle("s", fontName=base_font, fontSize=9, textColor=colors.grey, spaceAfter=2)
    note_style = ParagraphStyle("n", fontName=base_font, fontSize=8, textColor=colors.grey, spaceAfter=8)
    cell_style = ParagraphStyle("c", fontName=base_font, fontSize=7.5, leading=9.5)
    cell_dim_style = ParagraphStyle("cd", fontName=base_font, fontSize=7, leading=9,
                                    textColor=colors.HexColor("#6B7280"))

    elems = [
        Paragraph("Sedna Mutabakat — Uyuşmazlık Listesi", title_style),
        Paragraph(
            f"{filter_txt} &nbsp;·&nbsp; {total} kayıt &nbsp;·&nbsp; "
            f"Rapor tarihi: {today.strftime('%d.%m.%Y')}",
            sub_style,
        ),
        Paragraph("Banka ekstresi ↔ Sedna muhasebe defteri uyuşmazlık takibi — banka verisi esastır.", note_style),
    ]
    if total > _PDF_MAX_ROWS:
        elems.append(Paragraph(
            f"Uyarı: yalnız ilk {_PDF_MAX_ROWS} kayıt basıldı ({total - _PDF_MAX_ROWS} kayıt "
            "rapor dışı). Filtreleri daraltarak tam kapsam alabilirsiniz.",
            ParagraphStyle("w", fontName=bold_font, fontSize=8.5,
                           textColor=colors.HexColor("#B45309"), spaceAfter=6),
        ))

    RED = colors.HexColor("#DC2626")
    GREEN = colors.HexColor("#047857")
    NAVY = colors.HexColor("#1B2B45")

    if not rows:
        elems.append(Paragraph("Filtrelere uygun kayıt bulunamadı.", sub_style))
    else:
        data = [["Tarih", "Hesap", "Banka Açıklaması", "Tutar", "Sedna", "Sedna Kullanıcı", "Durum"]]
        amount_colors = []
        for i, r in enumerate(rows, start=1):
            sedna_bits = []
            if r.sedna_voucher:
                sedna_bits.append(str(r.sedna_voucher))
            if r.sedna_description:
                sedna_bits.append(r.sedna_description)
            status_txt = _STATUS_LABELS_TR.get(r.status, r.status)
            if r.resolved_at:
                status_txt += f"<br/>{_RESOLUTION_LABELS_TR.get(r.resolution, r.resolution or '')}"
            data.append([
                r.event_date.strftime("%d.%m.%Y") if r.event_date else "—",
                Paragraph(acc_names.get(r.bank_account_id) or "—", cell_style),
                Paragraph(r.description or "—", cell_style),
                _fmt_pdf_amount(float(r.amount or 0), r.currency),
                Paragraph(" — ".join(sedna_bits) if sedna_bits else "—", cell_style),
                Paragraph(r.sedna_record_user or "—", cell_dim_style),
                Paragraph(status_txt, cell_style),
            ])
            amount_colors.append((i, RED if float(r.amount or 0) < 0 else GREEN))

        # A4 yatay kullanılabilir genişlik ≈ 273mm
        table = Table(
            data,
            colWidths=[20 * mm, 32 * mm, 78 * mm, 30 * mm, 60 * mm, 25 * mm, 28 * mm],
            repeatRows=1,
        )
        style_cmds = [
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -1), base_font),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for row_idx, clr in amount_colors:
            style_cmds.append(("TEXTCOLOR", (3, row_idx), (3, row_idx), clr))
        table.setStyle(TableStyle(style_cmds))
        elems.append(table)

    doc.build(elems)
    output.seek(0)
    return Response(
        content=output.read(),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f"inline; filename=sedna-mutabakat-uyusmazliklar-{today.isoformat()}.pdf"},
    )


@router.post("/run")
def run_reconciliation(
    request: Request,
    background_tasks: BackgroundTasks,
    data: Optional[ReconRunRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("accounting.mutabakat", "use")),
):
    """Mutabakat taramasını elle tetikle (Sedna canlı sorgulanır).

    Onaydan MUAF: veri mutasyonu değil sınıflandırma — banka/Sedna verisi değişmez.
    """
    window_days = data.window_days if data else 45
    try:
        summary = sedna_recon_service.run_reconciliation(
            db, window_days=window_days, triggered_by=current_user.id)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Faz C: cari bakiye mutabakatı (best-effort — banka taraması başarılıysa kısmi hata koşuyu düşürmez)
    try:
        summary.update(sedna_recon_service.run_vendor_reconciliation(db))
    except Exception as e:
        db.rollback()
        summary["vendor_error"] = "Cari bakiye taraması başarısız (Sedna bağlantısını kontrol edin)"
        import logging
        logging.getLogger(__name__).error("Cari bakiye mutabakatı hatası: %s", e)

    log_action(
        db, current_user.id, "run", "sedna_recon", None,
        json.dumps({"window_days": window_days, **summary}, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.RECON, "run")
    return summary


@router.patch("/items/{item_id}")
def update_item(
    item_id: int,
    data: ReconItemAction,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("accounting.mutabakat", "use")),
):
    """Uyuşmazlık kaydını çöz / yoksay / yeniden aç."""
    item = db.query(SednaBankRecon).filter(SednaBankRecon.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Mutabakat kaydı bulunamadı")

    approval_resp = check_approval(
        db, "accounting.mutabakat", item_id, current_user.id, "update",
        {"op": "resolve_item", "action": data.action, "note": data.note},
    )
    if approval_resp:
        return approval_resp

    try:
        item = sedna_recon_service.resolve_recon_item(
            db, item_id, data.action, data.note, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        db, current_user.id, "update", "sedna_recon", item_id,
        json.dumps({"action": data.action, "note": data.note}, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    db.refresh(item)
    broadcast_finance_update(background_tasks, BroadcastModule.RECON, "update")
    acc = db.query(BankAccount).filter(BankAccount.id == item.bank_account_id).first()
    return _item_dict(item, acc.bank_name if acc else None)


@router.get("/fx-revaluation")
def fx_revaluation(
    year: int = Query(ge=2020, le=2100),
    month: int = Query(ge=1, le=12),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Aylık kur değerlemesi raporu — bizim hesap ↔ Sedna Type=4 fişi yan yana.

    Salt rapor (deftere/finance_events'e yazmaz — kullanıcı kararı 2026-07-11).
    Sedna canlı sorgulanır; tünel kapalıysa 503.
    """
    from app.services import fx_service

    try:
        return fx_service.compute_monthly_revaluation(db, year, month)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/fx-differences")
def fx_differences(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Kur farkı kayıtları (646/656 eşleniği) — çapraz-para eşleşmelerden birikir."""
    from app.models.event_match import FxDifference

    query = db.query(FxDifference).order_by(FxDifference.period.desc(), FxDifference.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    total_try = float(
        db.query(func.coalesce(func.sum(FxDifference.amount_try), 0)).scalar() or 0
    )
    return {
        "items": [{
            "id": r.id,
            "period": r.period.isoformat() if r.period else None,
            "amount_try": float(r.amount_try or 0),
            "rate_estimate": float(r.rate_estimate) if r.rate_estimate is not None else None,
            "rate_realized": float(r.rate_realized) if r.rate_realized is not None else None,
            "expected_try": float(r.expected_try) if r.expected_try is not None else None,
            "realized_try": float(r.realized_try) if r.realized_try is not None else None,
            "source": r.source,
            "description": r.description,
        } for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
        "total_amount_try": total_try,
    }


@router.get("/credit-mappings")
def credit_mappings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Kredi ürünleri ↔ Sedna 300 hesap eşleme durumu + canlı öneriler (Faz C)."""
    try:
        return sedna_recon_service.suggest_credit_mappings(db)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.patch("/credit-mappings/{product_id}")
def update_credit_mapping(
    product_id: int,
    data: CreditMappingUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("accounting.mutabakat", "use")),
):
    """Kredi ürününe Sedna 300 kodu ata/temizle."""
    approval_resp = check_approval(
        db, "accounting.mutabakat", product_id, current_user.id, "update",
        {"op": "credit_mapping", **data.model_dump()},
    )
    if approval_resp:
        return approval_resp
    try:
        prod = sedna_recon_service.set_credit_mapping(db, product_id, data.sedna_account_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_action(db, current_user.id, "update", "credit_product_sedna_map", product_id,
               json.dumps(data.model_dump(), ensure_ascii=False), get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.RECON, "update")
    return {"id": prod.id, "name": prod.name, "sedna_account_code": prod.sedna_account_code}


@router.get("/agency-mappings")
def agency_mappings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Acente grupları ↔ Sedna 340 avans hesabı eşleme durumu + öneriler (Faz C)."""
    try:
        return sedna_recon_service.suggest_agency_mappings(db)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.patch("/agency-mappings/{group_id}")
def update_agency_mapping(
    group_id: int,
    data: AgencyMappingUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("accounting.mutabakat", "use")),
):
    """Acente grubuna Sedna 340 kod listesi ata/temizle (para birimi başına ayrı hesap)."""
    approval_resp = check_approval(
        db, "accounting.mutabakat", group_id, current_user.id, "update",
        {"op": "agency_mapping", **data.model_dump()},
    )
    if approval_resp:
        return approval_resp
    try:
        g = sedna_recon_service.set_agency_mapping(db, group_id, data.sedna_account_codes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log_action(db, current_user.id, "update", "agency_group_sedna_map", group_id,
               json.dumps(data.model_dump(), ensure_ascii=False), get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.RECON, "update")
    return {"id": g.id, "name": g.name, "sedna_account_codes": list(g.sedna_account_codes or [])}


@router.patch("/period-lock")
def update_period_lock(
    data: PeriodLockUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("accounting.mutabakat", "use")),
):
    """Dönem kilidi tarihini ata/kaldır (uyarı modu — senkronu BLOKLAMAZ).

    Kilit-öncesi döneme ait yeni uyuşmazlık tespit edilirse ayrı vurgulu bildirim gider.
    """
    from datetime import date as date_cls

    from app.services.period_lock_service import set_lock_date

    approval_resp = check_approval(
        db, "accounting.mutabakat", 0, current_user.id, "update",
        {"op": "period_lock", **data.model_dump()},
    )
    if approval_resp:
        return approval_resp
    lock = date_cls.fromisoformat(data.lock_date) if data.lock_date else None
    set_lock_date(db, lock, current_user.id)
    log_action(db, current_user.id, "update", "finance_period_lock", None,
               json.dumps(data.model_dump(), ensure_ascii=False), get_client_ip(request))
    db.commit()
    broadcast_finance_update(background_tasks, BroadcastModule.RECON, "update")
    return {"lock_date": lock.isoformat() if lock else None}


@router.get("/account-mappings")
def account_mappings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("accounting.mutabakat", "view")),
):
    """Hesap eşleme durumu + canlı Sedna önerileri (102 leaf, Remark-numara skorlaması)."""
    try:
        return sedna_recon_service.suggest_account_mappings(db)
    except SednaUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.patch("/account-mappings/{account_id}")
def update_account_mapping(
    account_id: int,
    data: AccountMappingUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("accounting.mutabakat", "use")),
):
    """Banka hesabına Sedna 102 kodu ata/onayla/temizle."""
    acc = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Banka hesabı bulunamadı")

    approval_resp = check_approval(
        db, "accounting.mutabakat", account_id, current_user.id, "update",
        {"op": "account_mapping", **data.model_dump()},
    )
    if approval_resp:
        return approval_resp

    try:
        acc = sedna_recon_service.set_account_mapping(
            db, account_id, data.sedna_account_code, data.confirmed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(
        db, current_user.id, "update", "bank_account_sedna_map", account_id,
        json.dumps(data.model_dump(), ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    db.refresh(acc)
    broadcast_finance_update(background_tasks, BroadcastModule.RECON, "update")
    return {
        "id": acc.id,
        "bank_name": acc.bank_name,
        "sedna_account_code": acc.sedna_account_code,
        "sedna_code_confirmed": bool(acc.sedna_code_confirmed),
    }
