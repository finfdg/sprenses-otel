"""Kredi ürünleri CRUD endpoint'leri."""

import json
import math
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.credit_product import (
    CREDIT_PRODUCT_TYPES,
    CREDIT_TYPE_LABELS,
    CreditPayment,
    CreditProduct,
)
from app.models.user import User
from app.schemas.credit import (
    CreditCloseRequest,
    CreditPaymentResponse,
    CreditProductCreate,
    CreditProductResponse,
    CreditProductUpdate,
)
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.sql_search import like_pattern

from ._helpers import (
    _batch_payment_stats,
    _build_product_response,
    _regenerate_bch_payments,
    _regenerate_kmh_payments,
)

router = APIRouter()


@router.get("/")
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    type_filter: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Kredi ürünlerini listele."""
    query = db.query(CreditProduct)

    if type_filter and type_filter in CREDIT_PRODUCT_TYPES:
        query = query.filter(CreditProduct.type == type_filter)
    if status_filter:
        query = query.filter(CreditProduct.status == status_filter)
    if search:
        s = like_pattern(search, max_len=100)
        query = query.filter(
            (CreditProduct.name.ilike(s, escape="\\")) |
            (CreditProduct.bank_name.ilike(s, escape="\\"))
        )

    total = query.count()
    products = (
        query
        .options(joinedload(CreditProduct.creator))   # N+1 engeli
        .order_by(CreditProduct.type, CreditProduct.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Ödeme istatistiklerini toplu hesapla (N+1 engeli)
    product_ids = [p.id for p in products]
    stats = _batch_payment_stats(db, product_ids)

    return {
        "items": [_build_product_response(p, stats) for p in products],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


def _fmt_money_tr(v, currency: Optional[str]) -> str:
    """Tutarı TR formatında + para birimi sembolüyle döndür (₺1.234.567,89)."""
    sym = {"TRY": "₺", "EUR": "€", "USD": "$", "GBP": "£"}.get(currency or "TRY", "")
    try:
        s = f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{sym}{s}"
    except (TypeError, ValueError):
        return "—"


@router.get("/export/pdf")
def export_credits_pdf(
    type_filter: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Kredi ürünlerini PDF rapor olarak indir (açılış + vade tarihleri dahil).

    Liste ekranındaki filtreleri (tip/durum/arama) destekler — rapor, ekranda
    görülen krediyle eşleşir. Sayfalama yoktur; tüm eşleşen krediler raporlanır.
    """
    import io
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.utils.pdf_fonts import register_turkish_fonts

    # Liste ile aynı filtreler (sayfalama yok)
    query = db.query(CreditProduct)
    if type_filter and type_filter in CREDIT_PRODUCT_TYPES:
        query = query.filter(CreditProduct.type == type_filter)
    if status_filter:
        query = query.filter(CreditProduct.status == status_filter)
    if search:
        s = like_pattern(search, max_len=100)
        query = query.filter(
            (CreditProduct.name.ilike(s, escape="\\")) |
            (CreditProduct.bank_name.ilike(s, escape="\\"))
        )
    products = query.order_by(
        CreditProduct.type, CreditProduct.bank_name, CreditProduct.name
    ).all()

    # Türkçe + para birimi sembolü (₺ € £ $) destekli font — DejaVuSans
    base_font, bold_font = register_turkish_fonts()

    status_labels = {"active": "Aktif", "closed": "Kapalı"}

    def fmt_date(d):
        return d.strftime("%d.%m.%Y") if d else "—"

    def fmt_pct(v):
        return ("%" + (f"{float(v):g}")) if v is not None else "—"

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=landscape(A4),
        topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=12 * mm, rightMargin=12 * mm,
    )
    title_style = ParagraphStyle("t", fontName=bold_font, fontSize=14, spaceAfter=4)
    sub_style = ParagraphStyle("s", fontName=base_font, fontSize=9, textColor=colors.grey, spaceAfter=4)
    legend_style = ParagraphStyle("lg", fontName=base_font, fontSize=8, textColor=colors.grey, spaceAfter=10)
    # Metin hücreleri Paragraph ile sarılır → uzun adlar kolon içinde alt satıra
    # kayar (düz string hücreler kaymaz, taşıp komşu kolonun üstüne biner)
    cell_style = ParagraphStyle("cell", fontName=base_font, fontSize=7.5, leading=9)

    def _wrap(text):
        return Paragraph(escape(str(text)), cell_style)

    today = date_cls.today()
    elems = [
        Paragraph("Kredi Raporu", title_style),
        Paragraph(f"{len(products)} kredi &nbsp;·&nbsp; Rapor tarihi: {today.strftime('%d.%m.%Y')}", sub_style),
    ]

    data = [["Banka", "Kredi Adı", "Tip", "Tutar", "Faiz", "Kom.", "Açılış", "Vade", "Kalan", "Durum"]]
    eur_rows = []  # EUR kredilerinin tablo satır indeksleri (renklendirme için)
    for i, p in enumerate(products):
        if (p.currency or "TRY") == "EUR":
            eur_rows.append(i + 1)  # +1: başlık satırı
        data.append([
            _wrap(p.bank_name or "—"),
            _wrap(p.name),
            _wrap(CREDIT_TYPE_LABELS.get(p.type, p.type)),
            _fmt_money_tr(p.total_amount, p.currency),
            fmt_pct(p.interest_rate),
            fmt_pct(p.commission_rate),
            fmt_date(p.start_date),
            fmt_date(p.end_date),
            _fmt_money_tr(p.remaining_amount, p.currency),
            status_labels.get(p.status, p.status or "—"),
        ])

    # EUR kredileri varsa açıklama (legend) ekle
    if eur_rows:
        elems.append(Paragraph(
            '<font color="#2563EB">■</font>&nbsp; Mavi ile işaretli satırlar EUR kredileridir',
            legend_style,
        ))
    elems.append(Spacer(1, 4))

    # Landscape A4 kullanılabilir genişlik ≈ 273mm; toplam 260mm (güvenli)
    col_widths = [26 * mm, 54 * mm, 26 * mm, 31 * mm, 15 * mm, 15 * mm, 23 * mm, 23 * mm, 31 * mm, 16 * mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), bold_font),
        ("FONTNAME", (0, 1), (-1, -1), base_font),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D9488")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (3, 0), (5, -1), "RIGHT"),
        ("ALIGN", (6, 0), (7, -1), "CENTER"),
        ("ALIGN", (8, 0), (8, -1), "RIGHT"),
        ("ALIGN", (9, 0), (9, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#0D9488")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    # EUR satırlarını mavi ile vurgula (zebra'nın üzerine yazılır) + sol kenar aksanı
    eur_bg = colors.HexColor("#DBEAFE")
    eur_accent = colors.HexColor("#2563EB")
    for r in eur_rows:
        style_cmds.append(("BACKGROUND", (0, r), (-1, r), eur_bg))
        style_cmds.append(("LINEBEFORE", (0, r), (0, r), 2, eur_accent))
    table.setStyle(TableStyle(style_cmds))
    elems.append(table)

    # Para birimi bazında toplam (karışık para birimlerini toplamaz)
    totals: dict = {}
    for p in products:
        c = p.currency or "TRY"
        t = totals.setdefault(c, {"total": 0.0, "remaining": 0.0})
        t["total"] += float(p.total_amount or 0)
        t["remaining"] += float(p.remaining_amount or 0)
    if totals:
        elems.append(Spacer(1, 8))

        def _tot_line(c, v):
            txt = (
                f"{c}: Toplam {_fmt_money_tr(v['total'], c)} "
                f"&nbsp;·&nbsp; Kalan {_fmt_money_tr(v['remaining'], c)}"
            )
            # EUR toplamını mavi ile vurgula (tabloyla tutarlı)
            return f'<font color="#1D4ED8">{txt}</font>' if c == "EUR" else txt

        lines = "<br/>".join(_tot_line(c, v) for c, v in totals.items())
        elems.append(Paragraph(lines, ParagraphStyle("tot", fontName=bold_font, fontSize=9, leading=14)))

    doc.build(elems)
    output.seek(0)
    return Response(
        content=output.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=kredi-raporu-{today.isoformat()}.pdf"},
    )


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_product(
    data: CreditProductCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Yeni kredi ürünü oluştur."""
    approval_resp = check_approval(db, "finance.krediler", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    if data.type not in CREDIT_PRODUCT_TYPES:
        raise HTTPException(status_code=400, detail=f"Geçersiz ürün tipi: {data.type}")

    product = CreditProduct(
        type=data.type,
        name=data.name.strip(),
        bank_name=data.bank_name.strip() if data.bank_name else None,
        company=data.company.strip() if data.company else None,
        currency=data.currency or "TRY",
        total_amount=data.total_amount,
        remaining_amount=data.remaining_amount,
        interest_rate=data.interest_rate,
        bsmv_rate=data.bsmv_rate,
        commission_rate=data.commission_rate,
        start_date=data.start_date,
        end_date=data.end_date,
        details=json.dumps(data.details, ensure_ascii=False) if data.details else None,
        notes=data.notes,
        created_by=current_user.id,
    )
    db.add(product)
    db.flush()

    # BCH/KMH: gerekli alanlar doluysa ödeme planını üret
    payment_count = 0
    if product.type in ("bch", "kmh") and product.start_date and product.end_date and product.interest_rate:
        if product.type == "kmh":
            payment_count = _regenerate_kmh_payments(db, product)
        else:
            payment_count = _regenerate_bch_payments(db, product)

    details_msg = f"Kredi ürünü oluşturuldu: {CREDIT_TYPE_LABELS.get(data.type, data.type)} — {data.name}"
    if payment_count:
        details_msg += f" (+{payment_count} taksit)"

    log_action(
        db, current_user.id, "create", "credit_product",
        entity_id=product.id,
        details=details_msg,
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(product)

    return _build_product_response(product, _batch_payment_stats(db, [product.id]))


@router.get("/{product_id}")
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """Kredi ürünü detayı + ödeme planı."""
    product = db.query(CreditProduct).filter(CreditProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi ürünü bulunamadı")

    result = _build_product_response(product, _batch_payment_stats(db, [product.id]))

    # Ödemeler
    payments = db.query(CreditPayment).filter(
        CreditPayment.credit_product_id == product_id,
    ).order_by(CreditPayment.due_date).all()

    result["payments"] = [
        CreditPaymentResponse(
            id=p.id,
            credit_product_id=p.credit_product_id,
            installment_no=p.installment_no,
            due_date=p.due_date,
            amount=float(p.amount),
            principal=float(p.principal) if p.principal is not None else None,
            interest=float(p.interest) if p.interest is not None else None,
            bsmv=float(p.bsmv) if p.bsmv is not None else None,
            commission=float(p.commission) if p.commission is not None else None,
            is_paid=p.is_paid,
            paid_date=p.paid_date,
            bank_transaction_id=p.bank_transaction_id,
            match_number=p.match_number,
            notes=p.notes,
            created_at=p.created_at,
        ).model_dump()
        for p in payments
    ]

    return result


@router.patch("/{product_id}")
def update_product(
    product_id: int,
    data: CreditProductUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Kredi ürününü güncelle. BCH hesaplarında vade/faiz değişirse ödeme planı otomatik yenilenir."""
    product = db.query(CreditProduct).filter(CreditProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi ürünü bulunamadı")

    approval_resp = check_approval(db, "finance.krediler", product_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp

    update_data = data.model_dump(exclude_unset=True)

    # BCH/KMH için yeniden hesaplama gerekip gerekmediğini kontrol et
    needs_recalc = False
    if product.type in ("bch", "kmh"):
        recalc_fields = {"start_date", "end_date", "interest_rate", "total_amount", "remaining_amount", "bsmv_rate", "commission_rate"}
        if recalc_fields & set(update_data.keys()):
            needs_recalc = True

    if "details" in update_data:
        update_data["details"] = json.dumps(update_data["details"], ensure_ascii=False) if update_data["details"] else None

    for key, value in update_data.items():
        if key == "name" and value:
            value = value.strip()
        setattr(product, key, value)

    # BCH/KMH ödeme planını yeniden oluştur
    if needs_recalc:
        if product.type == "kmh":
            count = _regenerate_kmh_payments(db, product)
        else:
            count = _regenerate_bch_payments(db, product)
        details = f"Kredi ürünü güncellendi + ödeme planı yeniden oluşturuldu ({count} taksit): {product.name}"
    else:
        details = f"Kredi ürünü güncellendi: {product.name}"

    log_action(
        db, current_user.id, "update", "credit_product",
        entity_id=product_id,
        details=details,
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(product)

    return _build_product_response(product, _batch_payment_stats(db, [product.id]))


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Kredi ürününü sil (ödemeleri ile birlikte)."""
    product = db.query(CreditProduct).filter(CreditProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi ürünü bulunamadı")

    approval_resp = check_approval(db, "finance.krediler", product_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    product_name = product.name
    db.delete(product)

    log_action(
        db, current_user.id, "delete", "credit_product",
        entity_id=product_id,
        details=f"Kredi ürünü silindi: {product_name}",
        ip_address=get_client_ip(request),
    )
    db.commit()


# ─── Kapatma / Yeniden Açma ──────────────────────────────


@router.post("/{product_id}/close")
def close_product(
    product_id: int,
    data: CreditCloseRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Krediyi kapat — erken tahsil/kapanış.

    status='closed' + closed_date set edilir. Ödenmemiş (is_paid=False) ileri vadeli
    taksitlerin finance_events kayıtları geçersiz kılınır (invalidate) — nakit akımdan
    düşer. Ödenmiş taksitlere ve taksit kayıtlarının kendisine dokunulmaz (iz korunur).
    """
    product = db.query(CreditProduct).filter(CreditProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi ürünü bulunamadı")

    if product.status == "closed":
        raise HTTPException(status_code=400, detail="Kredi zaten kapalı")

    closed_date = data.closed_date or date_cls.today()

    approval_resp = check_approval(
        db, "finance.krediler", product_id, current_user.id, "update",
        {"action": "close", "closed_date": closed_date.isoformat()},
    )
    if approval_resp:
        return approval_resp

    try:
        product.status = "closed"
        product.closed_date = closed_date

        # Ödenmemiş ileri vadeli taksitlerin finance_event'lerini nakit akımdan çıkar
        unpaid = (
            db.query(CreditPayment)
            .filter(
                CreditPayment.credit_product_id == product_id,
                CreditPayment.is_paid.is_(False),
            )
            .all()
        )
        for pay in unpaid:
            finance_event_svc.invalidate(db, "credit", pay.id)

        log_action(
            db, current_user.id, "update", "credit_product",
            entity_id=product_id,
            details=(
                f"Kredi kapatıldı: {product.name} (kapanış {closed_date.isoformat()}). "
                f"{len(unpaid)} ödenmemiş taksit nakit akımdan çıkarıldı."
            ),
            ip_address=get_client_ip(request),
        )
        db.commit()
        db.refresh(product)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Kredi kapatılırken hata oluştu: {str(e)[:120]}")

    broadcast_finance_update(background_tasks, "credits", "update")
    return _build_product_response(product, _batch_payment_stats(db, [product.id]))


@router.post("/{product_id}/reopen")
def reopen_product(
    product_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.krediler", "use")),
):
    """Kapalı krediyi yeniden aç — kapatma işlemini geri alır.

    status='active' + closed_date=None. Ödenmemiş taksitlerin finance_events kayıtları
    yeniden oluşturulur (re-upsert) — nakit akıma geri döner.
    """
    product = db.query(CreditProduct).filter(CreditProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi ürünü bulunamadı")

    if product.status != "closed":
        raise HTTPException(status_code=400, detail="Kredi zaten açık")

    approval_resp = check_approval(
        db, "finance.krediler", product_id, current_user.id, "update",
        {"action": "reopen"},
    )
    if approval_resp:
        return approval_resp

    try:
        product.status = "active"
        product.closed_date = None

        # Ödenmemiş taksitleri nakit akıma geri getir
        unpaid = (
            db.query(CreditPayment)
            .filter(
                CreditPayment.credit_product_id == product_id,
                CreditPayment.is_paid.is_(False),
            )
            .all()
        )
        for pay in unpaid:
            finance_event_svc.upsert_credit_payment(db, pay, product)

        log_action(
            db, current_user.id, "update", "credit_product",
            entity_id=product_id,
            details=(
                f"Kredi yeniden açıldı: {product.name}. "
                f"{len(unpaid)} ödenmemiş taksit nakit akıma geri eklendi."
            ),
            ip_address=get_client_ip(request),
        )
        db.commit()
        db.refresh(product)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Kredi yeniden açılırken hata oluştu: {str(e)[:120]}")

    broadcast_finance_update(background_tasks, "credits", "update")
    return _build_product_response(product, _batch_payment_stats(db, [product.id]))
