"""Nakit akım PDF raporu — ay/gün bazlı EUR gelir-gider-bakiye tablosu.

Ekrandaki ay akordiyonunun (MonthAccordion) yazdırılabilir karşılığı: her ay
için günlük Gider/Gelir/Bakiye satırları + ay toplamı. Sayılar `eur-balances`
endpoint'iyle AYNI çekirdekten (`compute_eur_balances`) gelir — rapor ile
ekran birebir tutar.
"""

import io
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import heavy_limiter
from app.models.user import User
from app.utils.pdf_fonts import register_turkish_fonts

from .eur_balances import compute_eur_balances

# Türkçe ay/gün adları — sunucu locale'ine güvenilmez, sabit liste kullanılır
TR_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
TR_DAYS_SHORT = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

router = APIRouter()


def _fmt_eur(value: float) -> str:
    """EUR tutarını Türkçe binlik ayraçla, ondalıksız biçimlendir (1.515.047)."""
    if round(value) == 0:
        value = 0.0  # "-0" görünmesin
    return f"{value:,.0f}".replace(",", ".")


def _parse_date(value: Optional[str]) -> Optional[date_cls]:
    """Geçersiz tarih parametresini sessizce yok say (listing.py ile aynı tolerans)."""
    if not value:
        return None
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _day_label(d: date_cls) -> str:
    """Ekrandaki gün etiketiyle aynı biçim: '1 Temmuz Çar'."""
    return f"{d.day} {TR_MONTHS[d.month - 1]} {TR_DAYS_SHORT[d.weekday()]}"


@router.get("/cash-flow/report/pdf")
def cash_flow_report_pdf(
    start_date: Optional[str] = Query(None, description="Başlangıç tarihi (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Bitiş tarihi (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Ay/gün bazlı nakit akım PDF raporu (EUR karşılıklarıyla).

    Tarih aralığı ekrandaki filtreyle eşleşir — rapor, kullanıcının o an
    gördüğü ayları kapsar. Aralık verilmezse tüm kayıtlar raporlanır.
    """
    heavy_limiter.check(f"cashflow-pdf-{current_user.id}")

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    sd = _parse_date(start_date)
    ed = _parse_date(end_date)

    daily = compute_eur_balances(db)["daily"]

    # Aralık içindeki günleri ay bazında grupla (kronolojik — daily anahtarları ISO tarih)
    months: dict = {}
    for day_key in sorted(daily.keys()):
        d = date_cls.fromisoformat(day_key)
        if (sd and d < sd) or (ed and d > ed):
            continue
        months.setdefault(day_key[:7], []).append((d, daily[day_key]))

    base_font, bold_font = register_turkish_fonts()
    today = date_cls.today()

    if sd and ed:
        range_txt = f"{sd.strftime('%d.%m.%Y')} – {ed.strftime('%d.%m.%Y')}"
    elif sd:
        range_txt = f"{sd.strftime('%d.%m.%Y')} ve sonrası"
    elif ed:
        range_txt = f"{ed.strftime('%d.%m.%Y')} ve öncesi"
    else:
        range_txt = "Tüm kayıtlar"

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4,
        topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=14 * mm, rightMargin=14 * mm,
    )
    title_style = ParagraphStyle("t", fontName=bold_font, fontSize=14, spaceAfter=4)
    sub_style = ParagraphStyle("s", fontName=base_font, fontSize=9, textColor=colors.grey, spaceAfter=2)
    note_style = ParagraphStyle("n", fontName=base_font, fontSize=8, textColor=colors.grey, spaceAfter=8)
    month_title_style = ParagraphStyle(
        "mt", fontName=bold_font, fontSize=11,
        textColor=colors.HexColor("#0F766E"), spaceBefore=10, spaceAfter=2,
    )
    month_sub_style = ParagraphStyle(
        "ms", fontName=base_font, fontSize=8.5,
        textColor=colors.HexColor("#4B5563"), spaceAfter=4,
    )

    elems = [
        Paragraph("Nakit Akım Raporu", title_style),
        Paragraph(f"Dönem: {range_txt} &nbsp;·&nbsp; Rapor tarihi: {today.strftime('%d.%m.%Y')}", sub_style),
        Paragraph(
            "Tutarlar EUR karşılığıdır (TCMB kuru); Virman / Döviz Satım / İade / Pos Bloke Çözme hariçtir. "
            "Bakiye, gün sonu toplam banka bakiyesi projeksiyonudur.",
            note_style,
        ),
    ]

    RED = colors.HexColor("#DC2626")
    GREEN = colors.HexColor("#16A34A")
    TEAL = colors.HexColor("#0D9488")

    if not months:
        elems.append(Paragraph("Seçilen tarih aralığında kayıt bulunamadı.", sub_style))

    grand_income = 0.0
    grand_expense = 0.0
    final_balance = 0.0

    for month_key, day_rows in months.items():
        year, month_no = month_key.split("-")
        month_label = f"{TR_MONTHS[int(month_no) - 1]} {year}"
        m_income = sum(v["income_eur"] for _, v in day_rows)
        m_expense = sum(v["expense_eur"] for _, v in day_rows)
        m_balance = day_rows[-1][1]["balance_eur"]  # ayın son gününün bakiyesi
        grand_income += m_income
        grand_expense += m_expense
        final_balance = m_balance

        data = [["Tarih", "Gider (€)", "Gelir (€)", "Bakiye (€)"]]
        for d, vals in day_rows:
            data.append([
                _day_label(d),
                _fmt_eur(vals["expense_eur"]) if vals["expense_eur"] else "—",
                _fmt_eur(vals["income_eur"]) if vals["income_eur"] else "—",
                _fmt_eur(vals["balance_eur"]),
            ])
        data.append(["Ay Toplamı", _fmt_eur(m_expense), _fmt_eur(m_income), _fmt_eur(m_balance)])

        # A4 dikey kullanılabilir genişlik ≈ 182mm
        table = Table(data, colWidths=[62 * mm, 40 * mm, 40 * mm, 40 * mm], repeatRows=1)
        style_cmds = [
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
            ("FONTNAME", (0, 1), (-1, -2), base_font),
            ("FONTNAME", (0, -1), (-1, -1), bold_font),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), TEAL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F9FAFB")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3F4F6")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, TEAL),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor("#9CA3AF")),
            ("TEXTCOLOR", (1, 1), (1, -1), RED),
            ("TEXTCOLOR", (2, 1), (2, -1), GREEN),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]
        # Negatif bakiyeler kırmızı (ekrandaki renk koduyla tutarlı)
        for i, (_, vals) in enumerate(day_rows, start=1):
            if vals["balance_eur"] < 0:
                style_cmds.append(("TEXTCOLOR", (3, i), (3, i), RED))
        if m_balance < 0:
            style_cmds.append(("TEXTCOLOR", (3, -1), (3, -1), RED))
        table.setStyle(TableStyle(style_cmds))

        elems.append(Paragraph(month_label, month_title_style))
        elems.append(Paragraph(
            f"Gider €{_fmt_eur(m_expense)} &nbsp;·&nbsp; Gelir €{_fmt_eur(m_income)} "
            f"&nbsp;·&nbsp; Ay Sonu Bakiye €{_fmt_eur(m_balance)}",
            month_sub_style,
        ))
        elems.append(table)

    if months:
        elems.append(Spacer(1, 10))
        elems.append(Paragraph(
            f"Genel Toplam — Gider: €{_fmt_eur(grand_expense)} &nbsp;·&nbsp; "
            f"Gelir: €{_fmt_eur(grand_income)} &nbsp;·&nbsp; "
            f"Dönem Sonu Bakiye: €{_fmt_eur(final_balance)}",
            ParagraphStyle("tot", fontName=bold_font, fontSize=10, leading=14),
        ))

    doc.build(elems)
    output.seek(0)
    return Response(
        content=output.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=nakit-akim-raporu-{today.isoformat()}.pdf"},
    )
