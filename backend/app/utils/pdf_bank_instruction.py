"""Banka talimat PDF oluşturucu — EFT/havale/transfer ve döviz bozma talimatları.

Metin kuralları (2026-04-16):
- TL + aynı banka  → "havale"
- TL + farklı banka → "EFT"
- TL dışı (EUR/USD/GBP…) → "transfer"
- Paragraflar `firstLineIndent` ile paragraf başı alır
- Metin `TA_JUSTIFY` ile iki yana dayalı (sağa-sola yaslı) hizalanır
- Kaynak hesabın IBAN'ı gövde metninde belirtilir
"""

import io
import os
from datetime import date
from typing import Optional

import reportlab
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

# ─── Font kaydı (Türkçe karakter desteği) ─────────────────────────────

_FONT_DIR = os.path.join(os.path.dirname(reportlab.__file__), "fonts")

if "Vera" not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont("Vera", os.path.join(_FONT_DIR, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("VeraBd", os.path.join(_FONT_DIR, "VeraBd.ttf")))

FONT = "Vera"
FONT_BOLD = "VeraBd"

# ─── Logo ─────────────────────────────────────────────────────────────

_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_LOGO_PATH = os.path.join(_BACKEND_DIR, "uploads", "logos", "1_17e1b8ab.jpg")

# ─── Ortak sabitler ───────────────────────────────────────────────────

MARGIN_LEFT = 30 * mm
MARGIN_RIGHT = 30 * mm
FIRST_LINE_INDENT = 12 * mm  # Paragraf başı
BODY_FONT_SIZE = 11
BODY_LEADING = 18  # Satır yüksekliği (pt)


def _format_iban(iban: str) -> str:
    """IBAN'ı 4'lü gruplar halinde formatla."""
    iban = iban.replace(" ", "").upper()
    return " ".join(iban[i:i+4] for i in range(0, len(iban), 4))


def _currency_label(currency: str) -> str:
    """Para birimi kodunu görünen etikete çevir."""
    return {"TRY": "TL", "EUR": "EUR", "USD": "USD", "GBP": "GBP"}.get(currency, currency)


def _currency_name(currency: str) -> str:
    """Para biriminin tam adı (gövde metninde kullanılır)."""
    return {
        "TRY": "TL",
        "EUR": "Euro",
        "USD": "Amerikan Doları",
        "GBP": "İngiliz Sterlini",
    }.get(currency, currency)


def _format_amount(amount: float, currency: str = "TRY") -> str:
    """Tutarı Türk formatında göster — her zaman 2 ondalık basamak."""
    formatted = "{:,.2f}".format(amount).replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} {_currency_label(currency)}"


def _format_date(d: date) -> str:
    """Tarihi dd.mm.yyyy formatında döndür."""
    return d.strftime("%d.%m.%Y")


def _transfer_term(source_currency: str, source_bank: str, dest_bank: str) -> str:
    """İşlem adını döndürür.

    - TL + aynı banka  → 'havale'
    - TL + farklı banka → 'EFT'
    - TL dışı          → 'transfer'
    """
    cur = (source_currency or "TRY").upper()
    if cur != "TRY":
        return "transfer"
    # TL: aynı banka mı kontrol et (büyük/küçük harf + boşluk toleranslı)
    a = (source_bank or "").strip().lower()
    b = (dest_bank or "").strip().lower()
    if a and b and a == b:
        return "havale"
    return "EFT"


def _body_style() -> ParagraphStyle:
    """Gövde metni stili — paragraf başı + justify."""
    return ParagraphStyle(
        name="BankInstructionBody",
        fontName=FONT,
        fontSize=BODY_FONT_SIZE,
        leading=BODY_LEADING,
        alignment=TA_JUSTIFY,
        firstLineIndent=FIRST_LINE_INDENT,
        spaceAfter=6,
    )


def _draw_paragraph(c: canvas.Canvas, text: str, x: float, y: float,
                    width: float, style: ParagraphStyle) -> float:
    """Paragrafı (x, y) üst-sol köşesinden başlayarak çiz.
    Paragrafın bıraktığı yeni y (alt pozisyonu) döndürür.
    """
    p = Paragraph(text, style)
    _w, h = p.wrap(width, 200 * mm)
    p.drawOn(c, x, y - h)
    return y - h


def _draw_header(c: canvas.Canvas, width: float, height: float, instruction_date: date):
    """Logo ve tarih çiz."""
    # Logo (sol üst)
    if os.path.exists(_LOGO_PATH):
        logo_w = 50 * mm
        logo_h = 25 * mm
        c.drawImage(
            _LOGO_PATH, MARGIN_LEFT, height - 45 * mm,
            width=logo_w, height=logo_h,
            preserveAspectRatio=True, mask="auto",
        )

    # Tarih (sağ üst)
    c.setFont(FONT, 11)
    date_str = _format_date(instruction_date)
    c.drawRightString(width - MARGIN_RIGHT, height - 45 * mm, date_str)


# Sol imza seçenekleri
LEFT_SIGNERS = {
    "ugur": {"name": "Uğur CARUS", "title": "Yön.Kur.Üyesi"},
    "erol": {"name": "Erol YILDIZ", "title": "Yön.Kur.Bşk.Yrd."},
}
# Sağ imza (sabit)
RIGHT_SIGNER = {"name": "İsmail ÖZDEN", "title": "Yön.Kur.Baş."}


def _draw_signatures(c: canvas.Canvas, width: float, y: float,
                     text_width: float, left_signer: str = "ugur"):
    """İmza alanları çiz.

    - "Saygılarımızla" ayrı paragraf olarak paragraf başı + justify stiliyle
    - Sol: Uğur CARUS veya Erol YILDIZ (default Uğur)
    - Sağ: İsmail ÖZDEN (sabit)
    """
    # "Saygılarımızla," — gövde ile aynı stilde (paragraf başı + justify)
    style = _body_style()
    y -= 4 * mm
    y = _draw_paragraph(c, "Saygılarımızla,", MARGIN_LEFT, y, text_width, style)

    # İmzalar için alt boşluk
    y -= 20 * mm

    # Sol imza (Uğur/Erol)
    left = LEFT_SIGNERS.get(left_signer, LEFT_SIGNERS["ugur"])
    c.setFont(FONT_BOLD, 11)
    c.drawString(MARGIN_LEFT + 10 * mm, y, left["name"])
    c.setFont(FONT, 10)
    c.drawString(MARGIN_LEFT + 10 * mm, y - 5 * mm, left["title"])

    # Sağ imza (İsmail ÖZDEN — sabit)
    right_x = width - MARGIN_RIGHT - 50 * mm
    c.setFont(FONT_BOLD, 11)
    c.drawString(right_x, y, RIGHT_SIGNER["name"])
    c.setFont(FONT, 10)
    c.drawString(right_x, y - 5 * mm, RIGHT_SIGNER["title"])

    return y - 15 * mm


# ─── Public API: EFT / Havale / Transfer ──────────────────────────────

def generate_transfer_instruction(
    source_bank_name: str,
    source_branch_name: Optional[str],
    source_account_no: Optional[str],
    source_iban: str,
    source_currency: str,
    dest_bank_name: str,
    dest_branch_name: Optional[str],
    dest_iban: str,
    amount: float,
    instruction_date: Optional[date] = None,
    description: Optional[str] = None,
    left_signer: str = "ugur",
) -> bytes:
    """EFT / Havale / Transfer talimat PDF'i oluştur.

    İşlem adı otomatik seçilir:
    - TL + aynı banka → 'havale yapılmasını'
    - TL + farklı banka → 'EFT yapılmasını'
    - TL dışı → 'transfer edilmesini'
    """
    if instruction_date is None:
        instruction_date = date.today()

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)

    # Başlık (logo + tarih)
    _draw_header(c, width, height, instruction_date)

    # Banka başlığı — ortalanmış
    y = height - 65 * mm
    c.setFont(FONT_BOLD, 12)
    bank_title = source_bank_name.upper()
    if source_branch_name:
        bank_title += f" {source_branch_name.upper()}"
    bank_title += " MÜDÜRLÜĞÜNE"
    c.drawCentredString(width / 2, y, bank_title)

    # Gövde metni — paragraf başı + justify
    y -= 25 * mm
    text_width = width - MARGIN_LEFT - MARGIN_RIGHT

    cur_label = _currency_label(source_currency)
    amount_str = _format_amount(amount, source_currency)
    source_iban_fmt = _format_iban(source_iban)
    dest_iban_fmt = _format_iban(dest_iban)

    # İşlem adı seçimi
    term = _transfer_term(source_currency, source_bank_name, dest_bank_name)

    # Fiil yapısı
    # - havale / EFT → "yapılmasını"
    # - transfer (döviz) → "gerçekleştirilmesini"
    verb = "gerçekleştirilmesini" if term == "transfer" else "yapılmasını"

    # Kaynak hesap — "Şubeniz nezdindeki [... numaralı, ] <IBAN> IBAN'lı vadesiz <cur> hesabımızdan"
    acc_prefix = f"{source_account_no} numaralı, " if source_account_no else ""

    # Hedef banka/şube
    dest_branch = f" {dest_branch_name}" if dest_branch_name else ""

    # Tek paragraf, akıcı yazışma dili — "bulunan" tekrarı olmadan
    body_text = (
        f"Şubeniz nezdindeki {acc_prefix}{source_iban_fmt} IBAN'lı "
        f"vadesiz {cur_label} hesabımızdan, "
        f"{dest_bank_name}{dest_branch} Şubesindeki {dest_iban_fmt} IBAN'lı "
        f"hesabımıza {amount_str} tutarında {term} {verb} rica ederiz."
    )

    style = _body_style()
    y = _draw_paragraph(c, body_text, MARGIN_LEFT, y, text_width, style)

    # Paragraf 2 — açıklama (varsa)
    if description:
        desc_text = f"Açıklama: {description}"
        y -= 4 * mm
        y = _draw_paragraph(c, desc_text, MARGIN_LEFT, y, text_width, style)

    # İmzalar ("Saygılarımızla" dahil)
    y -= 8 * mm
    _draw_signatures(c, width, y, text_width, left_signer=left_signer)

    c.save()
    buf.seek(0)
    return buf.read()


# ─── Public API: Döviz Bozma ──────────────────────────────────────────

def generate_currency_exchange_instruction(
    bank_name: str,
    branch_name: Optional[str],
    account_no: Optional[str],
    source_iban: str,
    source_currency: str,
    target_currency: str,
    amount: float,
    target_iban: Optional[str] = None,
    instruction_date: Optional[date] = None,
    description: Optional[str] = None,
    left_signer: str = "ugur",
) -> bytes:
    """Döviz bozma/alma talimat PDF'i oluştur."""
    if instruction_date is None:
        instruction_date = date.today()

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)

    # Başlık
    _draw_header(c, width, height, instruction_date)

    # Banka başlığı
    y = height - 65 * mm
    c.setFont(FONT_BOLD, 12)
    bank_title = bank_name.upper()
    if branch_name:
        bank_title += f" {branch_name.upper()}"
    bank_title += " MÜDÜRLÜĞÜNE"
    c.drawCentredString(width / 2, y, bank_title)

    # Gövde — paragraf başı + justify
    y -= 25 * mm
    text_width = width - MARGIN_LEFT - MARGIN_RIGHT

    amount_str = _format_amount(amount, source_currency)
    source_name = _currency_name(source_currency)
    target_name = _currency_name(target_currency)
    source_iban_fmt = _format_iban(source_iban)

    # Kaynak hesap — "Şubeniz nezdindeki [... numaralı, ] <IBAN> IBAN'lı <cur> hesabımızdan"
    acc_prefix = f"{account_no} numaralı, " if account_no else ""

    # Hedef hesap varsa aktarım ekle — "bulunan" tekrarı olmadan, tek paragraf
    if target_iban:
        target_iban_fmt = _format_iban(target_iban)
        body_text = (
            f"Şubeniz nezdindeki {acc_prefix}{source_iban_fmt} IBAN'lı "
            f"{source_name} hesabımızdan {amount_str} tutarın "
            f"{target_name} cinsine çevrilerek "
            f"{target_iban_fmt} IBAN'lı hesabımıza aktarılmasını rica ederiz."
        )
    else:
        body_text = (
            f"Şubeniz nezdindeki {acc_prefix}{source_iban_fmt} IBAN'lı "
            f"{source_name} hesabımızdan {amount_str} tutarın "
            f"{target_name} cinsine çevrilmesini rica ederiz."
        )

    style = _body_style()
    y = _draw_paragraph(c, body_text, MARGIN_LEFT, y, text_width, style)

    # Açıklama
    if description:
        desc_text = f"Açıklama: {description}"
        y -= 4 * mm
        y = _draw_paragraph(c, desc_text, MARGIN_LEFT, y, text_width, style)

    # İmzalar ("Saygılarımızla" dahil)
    y -= 8 * mm
    _draw_signatures(c, width, y, text_width, left_signer=left_signer)

    c.save()
    buf.seek(0)
    return buf.read()
