"""Kalite formu PDF rapor oluşturucu."""

import io
import os
from datetime import datetime
from typing import Optional

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ─── Font kaydı (Türkçe karakter desteği) ─────────────────────────────

_FONT_DIR = os.path.join(os.path.dirname(reportlab.__file__), "fonts")

pdfmetrics.registerFont(TTFont("Vera", os.path.join(_FONT_DIR, "Vera.ttf")))
pdfmetrics.registerFont(TTFont("VeraBd", os.path.join(_FONT_DIR, "VeraBd.ttf")))
pdfmetrics.registerFont(TTFont("VeraIt", os.path.join(_FONT_DIR, "VeraIt.ttf")))
pdfmetrics.registerFont(TTFont("VeraBI", os.path.join(_FONT_DIR, "VeraBI.ttf")))

pdfmetrics.registerFontFamily(
    "Vera", normal="Vera", bold="VeraBd", italic="VeraIt", boldItalic="VeraBI",
)

FONT = "Vera"
FONT_BOLD = "VeraBd"

# ─── Logo dizini ──────────────────────────────────────────────────────

# backend/ dizini (pdf_quality.py → utils/ → app/ → backend/)
_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_PROJECT_DIR = os.path.dirname(_BACKEND_DIR)  # otel/
_LOGOS_DIR = os.path.join(_BACKEND_DIR, "uploads", "logos")
_DEFAULT_LOGO = os.path.join(_PROJECT_DIR, "frontend", "static", "icon-192.png")

# ─── Renkler ──────────────────────────────────────────────────────────

TEAL = colors.HexColor("#0d9488")
TEAL_LIGHT = colors.HexColor("#f0fdfa")
GRAY_50 = colors.HexColor("#f9fafb")
GRAY_100 = colors.HexColor("#f3f4f6")
GRAY_200 = colors.HexColor("#e5e7eb")
GRAY_500 = colors.HexColor("#6b7280")
GRAY_700 = colors.HexColor("#374151")
GRAY_900 = colors.HexColor("#111827")
GREEN = colors.HexColor("#16a34a")
GREEN_LIGHT = colors.HexColor("#f0fdf4")
RED = colors.HexColor("#dc2626")
RED_LIGHT = colors.HexColor("#fef2f2")
AMBER = colors.HexColor("#d97706")
AMBER_LIGHT = colors.HexColor("#fffbeb")

# ─── Stiller ─────────────────────────────────────────────────────────

STYLE_TITLE = ParagraphStyle(
    "Title", fontName=FONT_BOLD, fontSize=14, leading=18,
    textColor=GRAY_900, spaceAfter=2 * mm, alignment=1,  # center
)

STYLE_DATE = ParagraphStyle(
    "Date", fontName=FONT, fontSize=9, leading=12,
    textColor=GRAY_500, alignment=2,  # right
)

STYLE_SECTION = ParagraphStyle(
    "Section", fontName=FONT_BOLD, fontSize=10, leading=14,
    textColor=TEAL, spaceBefore=4 * mm, spaceAfter=2 * mm,
)

STYLE_LABEL = ParagraphStyle(
    "Label", fontName=FONT, fontSize=8.5, leading=11, textColor=GRAY_700,
)

STYLE_VALUE = ParagraphStyle(
    "Value", fontName=FONT_BOLD, fontSize=8.5, leading=11, textColor=GRAY_900,
)

STYLE_UNIT = ParagraphStyle(
    "Unit", fontName=FONT, fontSize=7.5, leading=10, textColor=GRAY_500,
)

STYLE_META = ParagraphStyle(
    "Meta", fontName=FONT, fontSize=8, leading=11, textColor=GRAY_500,
)

STYLE_CORRECTIVE = ParagraphStyle(
    "Corrective", fontName=FONT, fontSize=7.5, leading=10,
    textColor=RED, leftIndent=4 * mm,
)

STYLE_NOTES = ParagraphStyle(
    "Notes", fontName=FONT, fontSize=8.5, leading=12, textColor=GRAY_700,
)

STYLE_APPROVED = ParagraphStyle(
    "Approved", fontName=FONT_BOLD, fontSize=10, leading=14,
    textColor=GREEN, alignment=1,  # center
)


# ─── Sayfa dekorasyonları için özel Canvas ──────────────────────────────


def _extract_png_from_svg(svg_path):
    """SVG içinde gömülü base64 PNG varsa çıkar, geçici dosya yolu döndür."""
    import base64
    import re
    import tempfile
    try:
        with open(svg_path, "r", encoding="utf-8") as f:
            content = f.read()
        # data:image/png;base64,... kalıbını bul
        match = re.search(r'data:image/png;base64,\s*([A-Za-z0-9+/=\s]+)', content)
        if match:
            b64_data = match.group(1).replace("\n", "").replace("\r", "").replace(" ", "")
            png_bytes = base64.b64decode(b64_data)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(png_bytes)
            tmp.close()
            return tmp.name
    except Exception:
        pass
    return None


def _draw_logo_on_canvas(cvs, logo_path, x, y, max_w, max_h):
    """Logo dosyasını canvas üzerine çiz (PNG/JPG/SVG destekli)."""
    if not logo_path or not os.path.exists(logo_path):
        return

    ext = os.path.splitext(logo_path)[1].lower()

    if ext == ".svg":
        # SVG içinde gömülü PNG varsa çıkar — şeffaflık korunur
        extracted_png = _extract_png_from_svg(logo_path)
        if extracted_png:
            try:
                cvs.drawImage(
                    extracted_png, x, y,
                    width=max_w, height=max_h,
                    preserveAspectRatio=True,
                    mask='auto',
                )
            except Exception:
                pass
            finally:
                try:
                    os.unlink(extracted_png)
                except OSError:
                    pass
            return

        # Gömülü PNG yoksa svglib ile render et
        try:
            from reportlab.graphics import renderPDF
            from reportlab.graphics.shapes import Drawing, Group
            from svglib.svglib import svg2rlg

            drawing = svg2rlg(logo_path)
            if drawing:
                bounds = drawing.getBounds()
                if bounds:
                    bx1, by1, bx2, by2 = bounds
                    content_w = bx2 - bx1
                    content_h = by2 - by1
                else:
                    content_w = drawing.width
                    content_h = drawing.height
                    bx1, by1 = 0, 0

                if content_w <= 0 or content_h <= 0:
                    return

                scale = min(max_w / content_w, max_h / content_h)
                wrapper = Group(drawing)
                wrapper.transform = (
                    scale, 0, 0, scale,
                    -bx1 * scale, -by1 * scale,
                )
                new_drawing = Drawing(content_w * scale, content_h * scale)
                new_drawing.add(wrapper)
                renderPDF.draw(new_drawing, cvs, x, y)
        except Exception:
            pass
    else:
        try:
            cvs.drawImage(
                logo_path, x, y,
                width=max_w, height=max_h,
                preserveAspectRatio=True,
                mask='auto',
            )
        except Exception:
            pass


def _make_numbered_canvas(footer_text, logo_path):
    """Her sayfaya logo, sayfa numarası ve altbilgi ekleyen Canvas sınıfı."""

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            canvas.Canvas.__init__(self, *args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_decorations(num_pages)
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)

        def _draw_decorations(self, total_pages):
            page_w, page_h = A4
            page_num = self._pageNumber

            self.saveState()

            # ─── Logo sol üst ─────────────────────────
            _draw_logo_on_canvas(
                self, logo_path,
                x=15 * mm,
                y=page_h - 6 * mm - 13 * mm,
                max_w=50 * mm,
                max_h=13 * mm,
            )

            # ─── Alt çizgi ────────────────────────────
            self.setStrokeColor(GRAY_200)
            self.setLineWidth(0.5)
            self.line(
                15 * mm, 18 * mm,
                page_w - 15 * mm, 18 * mm,
            )

            # ─── Altbilgi metni (orta) ────────────────
            if footer_text:
                self.setFont(FONT, 7)
                self.setFillColor(GRAY_500)
                self.drawCentredString(page_w / 2, 11 * mm, footer_text)

            # ─── Sayfa numarası (sağ alt) ─────────────
            self.setFont(FONT, 8)
            self.setFillColor(GRAY_500)
            self.drawRightString(
                page_w - 15 * mm,
                11 * mm,
                "%d/%d" % (page_num, total_pages),
            )

            self.restoreState()

    return NumberedCanvas


# ─── Yardımcı fonksiyonlar ───────────────────────────────────────────


def _fmt_date(d) -> str:
    """Tarihi dd.MM.yyyy formatına çevir."""
    if not d:
        return "—"
    if isinstance(d, str):
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            return d
    return d.strftime("%d.%m.%Y")


def _fmt_datetime(d) -> str:
    """Tarihi dd.MM.yyyy HH:mm formatına çevir."""
    if not d:
        return "—"
    if isinstance(d, str):
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            return d
    return d.strftime("%d.%m.%Y %H:%M")


def _safe(text: Optional[str]) -> str:
    """None → '—', XML özel karakterlerini escape et."""
    if not text:
        return "—"
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ─── Karşılaştırma badge yardımcısı ────────────────────────────────


_COMPARISON_LABELS = {
    "previous": "Ö.Form",
    "previous_day": "Ö.Gün",
    "previous_week": "Ö.Hafta",
    "previous_month": "Ö.Ay",
}


def _build_comparison_badges(
    field_id,
    current_per_capita,
    guest_field_id,
    comparisons,
    increase_threshold,
    decrease_threshold,
):
    # type: (int, float, Optional[int], Optional[dict], float, float) -> List[dict]
    """Karşılaştırma badge listesi oluştur. Her badge: {label, pct, direction, color}."""
    if not comparisons or current_per_capita is None:
        return []

    badges = []
    for period_key, label in _COMPARISON_LABELS.items():
        period_values = comparisons.get(period_key)
        if not period_values:
            continue

        # Önceki kişi sayısını bul
        prev_guest_count = 0
        prev_value = None
        for pv in period_values:
            if pv.get("field_id") == guest_field_id:
                try:
                    prev_guest_count = float(pv.get("value", "0") or "0")
                except (ValueError, TypeError):
                    prev_guest_count = 0
            if pv.get("field_id") == field_id:
                prev_value = pv.get("value")

        if prev_value is None or prev_guest_count <= 0:
            continue

        try:
            prev_per_capita = float(prev_value) / prev_guest_count
        except (ValueError, TypeError, ZeroDivisionError):
            continue

        if prev_per_capita == 0:
            continue

        change_pct = ((current_per_capita - prev_per_capita) / prev_per_capita) * 100

        if change_pct > increase_threshold:
            badges.append({
                "label": label,
                "pct": abs(change_pct),
                "direction": "up",
                "color": "#dc2626",
            })
        elif change_pct < -decrease_threshold:
            badges.append({
                "label": label,
                "pct": abs(change_pct),
                "direction": "down",
                "color": "#16a34a",
            })

    return badges


def _build_meter_comparison_badges(
    field_id,
    current_per_capita,
    guest_field_id,
    comparisons,
    meter_consumptions,
    increase_threshold,
    decrease_threshold,
):
    # type: (int, float, Optional[int], Optional[dict], dict, float, float) -> List[dict]
    """Sayaç alanları için tüketim bazlı karşılaştırma badge listesi."""
    if not comparisons or current_per_capita is None:
        return []

    badges = []
    for period_key, label in _COMPARISON_LABELS.items():
        if period_key == "previous":
            continue  # Sayaç karşılaştırmada sadece gün/hafta/ay kullanılır

        period_values = comparisons.get(period_key)
        if not period_values:
            continue

        # Önceki kişi sayısını bul
        prev_guest_count = 0
        for pv in period_values:
            if pv.get("field_id") == guest_field_id:
                try:
                    prev_guest_count = float(pv.get("value", "0") or "0")
                except (ValueError, TypeError):
                    prev_guest_count = 0

        if prev_guest_count <= 0:
            continue

        # Tüketim değerini al
        comp_consumptions = meter_consumptions.get(period_key)
        if not comp_consumptions:
            continue

        consumption = comp_consumptions.get(str(field_id))
        if consumption is None:
            continue

        try:
            prev_per_capita = consumption / prev_guest_count
        except (ValueError, TypeError, ZeroDivisionError):
            continue

        if prev_per_capita == 0:
            continue

        change_pct = ((current_per_capita - prev_per_capita) / prev_per_capita) * 100

        if change_pct > increase_threshold:
            badges.append({
                "label": label,
                "pct": abs(change_pct),
                "direction": "up",
                "color": "#dc2626",
            })
        elif change_pct < -decrease_threshold:
            badges.append({
                "label": label,
                "pct": abs(change_pct),
                "direction": "down",
                "color": "#16a34a",
            })

    return badges


# ─── Ana fonksiyon ───────────────────────────────────────────────────


def generate_quality_form_pdf(
    detail: dict,
    footer_text: Optional[str] = None,
    logo_filename: Optional[str] = None,
) -> bytes:
    """
    Form detay dict'inden PDF byte dizisi oluşturur.

    detail: _build_form_detail() çıktısı (dict).
    footer_text: Şablon altbilgi metni (her sayfada gösterilir).
    logo_filename: Şablon logo dosya adı (uploads/logos/ içinde).
    """
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=28 * mm,
        bottomMargin=22 * mm,
    )

    elements = []
    page_width = A4[0] - 30 * mm  # kullanılabilir genişlik

    # ─── Başlık (ortalı) + Tarih (sağ üst) ─────────────────────
    elements.append(Paragraph(_safe(detail.get("template_name", "")), STYLE_TITLE))
    elements.append(
        Paragraph(
            "Tarih: %s" % _fmt_date(detail.get("period_date")),
            STYLE_DATE,
        )
    )
    elements.append(Spacer(1, 1 * mm))

    # ─── Meta bilgiler (dolduran | onaylayan yan yana) ────────
    filled_by = detail.get("filled_by_name")
    submitted_at = detail.get("submitted_at")
    reviewed_by = detail.get("reviewed_by_name")
    reviewed_at = detail.get("reviewed_at")

    half_w = page_width / 2

    meta_left = []  # Dolduran
    if filled_by:
        meta_left.append(Paragraph(
            'Dolduran: <b>%s</b>' % _safe(filled_by), STYLE_META
        ))
    if submitted_at:
        meta_left.append(Paragraph(
            'Gönderilme: <b>%s</b>' % _fmt_datetime(submitted_at), STYLE_META
        ))

    meta_right = []  # Onaylayan
    if reviewed_by:
        meta_right.append(Paragraph(
            'Onaylayan: <b>%s</b>' % _safe(reviewed_by), STYLE_META
        ))
    if reviewed_at:
        meta_right.append(Paragraph(
            'Onay Tarihi: <b>%s</b>' % _fmt_datetime(reviewed_at), STYLE_META
        ))

    if meta_left or meta_right:
        # Her sütunu tek Paragraph listesine dönüştür
        left_cell = meta_left if meta_left else [Paragraph("", STYLE_META)]
        right_cell = meta_right if meta_right else [Paragraph("", STYLE_META)]

        meta_table = Table(
            [[left_cell, right_cell]],
            colWidths=[half_w, half_w],
        )
        meta_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(meta_table)

    elements.append(Spacer(1, 2 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_200))
    elements.append(Spacer(1, 1 * mm))

    # ─── Kişi başı hesaplama hazırlığı ───────────────────────────
    # Değerleri field_id → value map'e çevir
    val_map = {}
    for v in detail.get("values", []):
        val_map[v["field_id"]] = {
            "value": v.get("value", ""),
            "corrective_action": v.get("corrective_action", ""),
            "correction_note": v.get("correction_note", ""),
        }

    # Kişi sayısı alanını bul
    guest_count = 0
    guest_field_id = None
    sections = detail.get("sections", [])
    for sec in sections:
        for fld in sec.get("fields", []):
            if fld.get("is_guest_count"):
                guest_field_id = fld["id"]
                try:
                    guest_count = float(val_map.get(fld["id"], {}).get("value", "0") or "0")
                except (ValueError, TypeError):
                    guest_count = 0
                break

    # Karşılaştırma ve eşik bilgileri
    comparisons = detail.get("comparisons")
    meter_consumptions = detail.get("meter_consumptions")
    inc_threshold = detail.get("increase_threshold", 10.0) or 10.0
    dec_threshold = detail.get("decrease_threshold", 10.0) or 10.0
    is_month_end = detail.get("is_month_end", False)

    # ─── Bölüm + Alanlar ────────────────────────────────────────
    for sec in sections:
        elements.append(Paragraph(_safe(sec.get("name", "")), STYLE_SECTION))

        fields = sec.get("fields", [])
        if not fields:
            continue

        table_data = []
        row_colors = []

        for fld in fields:
            fid = fld["id"]
            label = fld.get("label", "")
            field_type = fld.get("field_type", "text")
            unit = fld.get("unit", "")
            is_resource = fld.get("is_resource", False)
            is_meter = fld.get("is_meter", False)
            is_month_end_only = fld.get("is_month_end_only", False)

            # Ay sonu alanlarını atla (ay sonu değilse)
            if is_month_end_only and not is_month_end:
                continue

            raw_val = val_map.get(fid, {}).get("value", "") or ""
            corrective = val_map.get(fid, {}).get("corrective_action", "")
            correction_note = val_map.get(fid, {}).get("correction_note", "")

            # Değer gösterimi
            if field_type == "yes_no":
                if raw_val in ("Evet", "Uygun"):
                    display_val = '<font color="#16a34a"><b>Uygun</b></font>'
                    row_colors.append(GREEN_LIGHT)
                elif raw_val in ("Hayır", "Uygun Değil"):
                    display_val = '<font color="#dc2626"><b>Uygun Değil</b></font>'
                    row_colors.append(RED_LIGHT)
                else:
                    display_val = "—"
                    row_colors.append(None)
            else:
                display_val = _safe(raw_val) if raw_val else "—"
                row_colors.append(None)

            # Birim ve kişi başı
            extra_parts = []
            if unit:
                extra_parts.append(unit)

            current_per_capita = None
            if is_resource and guest_count > 0 and raw_val:
                try:
                    if is_meter and meter_consumptions:
                        # Sayaç: tüketim üzerinden kişi başı hesapla
                        consumption = meter_consumptions.get("current", {}).get(str(fid))
                        if consumption is not None:
                            extra_parts.append("tüketim: %.1f" % consumption)
                            current_per_capita = consumption / guest_count
                            extra_parts.append("kişi başı: %.2f" % current_per_capita)
                    else:
                        current_per_capita = float(raw_val) / guest_count
                        extra_parts.append("kişi başı: %.2f" % current_per_capita)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

            extra_text = " · ".join(extra_parts) if extra_parts else ""

            # Karşılaştırma badge'leri
            comparison_badges = []
            if is_resource and current_per_capita is not None and comparisons:
                if is_meter and meter_consumptions:
                    # Sayaç: tüketim bazlı karşılaştırma
                    comparison_badges = _build_meter_comparison_badges(
                        fid, current_per_capita, guest_field_id,
                        comparisons, meter_consumptions,
                        inc_threshold, dec_threshold,
                    )
                else:
                    comparison_badges = _build_comparison_badges(
                        fid, current_per_capita, guest_field_id,
                        comparisons, inc_threshold, dec_threshold,
                    )

            # Etiket — ay sonu alanı ise işaretle
            label_text = _safe(label)
            if is_month_end_only:
                label_text += ' <font color="#6b7280" size="7">(Ay Sonu)</font>'

            # Tablo satırı
            row = [
                Paragraph(label_text, STYLE_LABEL),
                Paragraph(display_val, STYLE_VALUE),
                Paragraph(extra_text, STYLE_UNIT),
            ]
            table_data.append(row)

            # Karşılaştırma badge satırları (her badge ayrı satırda)
            for badge in comparison_badges:
                arrow = "+" if badge["direction"] == "up" else "-"
                clr = badge["color"]
                bg_color = RED_LIGHT if badge["direction"] == "up" else GREEN_LIGHT
                badge_text = (
                    '<font color="%s"><b>%s</b>  %s%.1f%%</font>'
                    % (clr, badge["label"], arrow, badge["pct"])
                )
                comp_row = [
                    Paragraph("", STYLE_LABEL),
                    Paragraph(badge_text, STYLE_UNIT),
                    Paragraph("", STYLE_UNIT),
                ]
                table_data.append(comp_row)
                row_colors.append(bg_color)

            # Uygunsuzluk açıklaması satırı
            if field_type == "yes_no" and raw_val in ("Hayır", "Uygun Değil") and corrective:
                corr_row = [
                    Paragraph("", STYLE_LABEL),
                    Paragraph(
                        '<font color="#dc2626"><b>Uygunsuzluk:</b> %s</font>' % _safe(corrective),
                        STYLE_CORRECTIVE,
                    ),
                    Paragraph("", STYLE_UNIT),
                ]
                table_data.append(corr_row)
                row_colors.append(RED_LIGHT)

            # Yapılan düzeltme satırı
            if field_type == "yes_no" and raw_val in ("Hayır", "Uygun Değil") and correction_note:
                note_row = [
                    Paragraph("", STYLE_LABEL),
                    Paragraph(
                        '<font color="#b45309"><b>Düzeltme:</b> %s</font>' % _safe(correction_note),
                        STYLE_CORRECTIVE,
                    ),
                    Paragraph("", STYLE_UNIT),
                ]
                table_data.append(note_row)
                row_colors.append(AMBER_LIGHT)

        if table_data:
            col_widths = [page_width * 0.45, page_width * 0.30, page_width * 0.25]
            tbl = Table(table_data, colWidths=col_widths, repeatRows=0)

            style_cmds = [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.3, GRAY_200),
            ]

            # Satır arkaplan renkleri
            for i, bg in enumerate(row_colors):
                if bg:
                    style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
                elif i % 2 == 0:
                    style_cmds.append(("BACKGROUND", (0, i), (-1, i), GRAY_50))

            tbl.setStyle(TableStyle(style_cmds))
            elements.append(tbl)

    # ─── Açıklama / Notlar ───────────────────────────────────────
    notes = detail.get("notes")
    if notes:
        elements.append(Spacer(1, 4 * mm))
        elements.append(Paragraph("Açıklama", STYLE_SECTION))
        elements.append(Paragraph(_safe(notes), STYLE_NOTES))

    # ─── Onay Damgası ────────────────────────────────────────────
    elements.append(Spacer(1, 6 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_200))
    elements.append(Spacer(1, 3 * mm))

    stamp_text = "ONAYLANDI — %s" % _fmt_datetime(reviewed_at)
    if reviewed_by:
        stamp_text += " — %s" % _safe(reviewed_by)
    elements.append(Paragraph(stamp_text, STYLE_APPROVED))

    # ─── Logo dosya yolunu belirle ───────────────────────────
    logo_path = None
    if logo_filename:
        candidate = os.path.join(_LOGOS_DIR, logo_filename)
        if os.path.exists(candidate):
            logo_path = candidate
    if not logo_path and os.path.exists(_DEFAULT_LOGO):
        logo_path = _DEFAULT_LOGO

    # ─── PDF oluştur (logo + sayfa no + altbilgi ile) ──────────
    canvas_class = _make_numbered_canvas(footer_text, logo_path)
    doc.build(elements, canvasmaker=canvas_class)
    return buf.getvalue()
