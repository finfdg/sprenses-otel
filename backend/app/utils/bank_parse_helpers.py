"""Banka ekstresi sayı/tarih ayrıştırma yardımcıları (saf fonksiyonlar).

`bank_parser.py`'den ayrıştırıldı (dosya boyutu + tek-sorumluluk). Bu modül yalnız
standart kütüphaneye bağlıdır (re/datetime/unicodedata) — dataclass/PDF/Excel mantığı yok.
`bank_parser.py` bu fonksiyonları import eder.
"""
import re
import unicodedata
from datetime import date, datetime
from typing import List, Optional, Tuple


def _strip_currency_suffix(text: str) -> str:
    """Tutar metninden döviz son ekini kaldır: '2.785,37 TL' → '2.785,37'"""
    return re.sub(r"\s*(TL|TRY|EUR|EURO|USD)\s*$", "", text.strip(), flags=re.IGNORECASE)


def parse_turkish_number(text: str) -> Optional[float]:
    """Türk sayı formatını float'a çevir: 3.765.000,00 → 3765000.00"""
    if not text:
        return None
    text = _strip_currency_suffix(text.strip()).replace(" ", "")

    # Pozitif/negatif göstergesi
    negative = False
    if text.startswith("-"):
        negative = True
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    elif text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    # Binlik noktaları kaldır, ondalık virgülü noktaya çevir
    text = text.replace(".", "").replace(",", ".")

    try:
        val = float(text)
        return -val if negative else val
    except ValueError:
        return None


def parse_english_number(text: str) -> Optional[float]:
    """İngilizce sayı formatını float'a çevir: 600,000.00 → 600000.0 (QNB Finansbank)."""
    if not text:
        return None
    text = _strip_currency_suffix(text.strip()).replace(" ", "")

    negative = False
    if text.startswith("-"):
        negative = True
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    elif text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    # Binlik virgülleri kaldır
    text = text.replace(",", "")

    try:
        val = float(text)
        return -val if negative else val
    except ValueError:
        return None


def _detect_number_format(data_rows_cells: list, amount_idx: Optional[int],
                          balance_idx: Optional[int]) -> str:
    """Tablo hücrelerinden sayı formatını tespit et: 'english' veya 'turkish'.

    English: 1,000.00 (virgül binlik, nokta ondalık) — QNB Finansbank
    Turkish: 1.000,00 (nokta binlik, virgül ondalık) — Ziraat, TEB, Garanti vb.
    """
    english_score = 0
    turkish_score = 0

    for cells in data_rows_cells:
        for idx in (amount_idx, balance_idx):
            if idx is None or idx >= len(cells):
                continue
            val = cells[idx].strip().lstrip("+-")
            if not val:
                continue
            # English: 600,000.00 — virgül binlik, nokta ondalık
            if re.match(r"\d{1,3}(,\d{3})*\.\d{2}$", val):
                english_score += 1
            # Turkish: 600.000,00 — nokta binlik, virgül ondalık
            elif re.match(r"\d{1,3}(\.\d{3})*,\d{2}$", val):
                turkish_score += 1

    return "english" if english_score > turkish_score else "turkish"


def parse_date_tr(text: str) -> Optional[date]:
    """DD.MM.YYYY veya DD/MM/YYYY formatını date'e çevir."""
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_tr(text: str) -> str:
    """Türkçe İ/I karakterlerini normalize et (İ → i, I → ı sorununu çöz).

    Python'da 'İ'.lower() → 'i\\u0307' (combining dot) olur,
    bu da 'tarih' aramasının 'tari̇h' ile eşleşmemesine neden olur.
    NFKD normalization + combining mark temizliği ile düzeltilir.
    Ayrıca 'ı' (dotless i, U+0131) → 'i' dönüşümü yapılır (QNB: Açıklaması → aciklamasi).
    """
    normalized = unicodedata.normalize("NFKD", text.lower())
    result = re.sub(r"[̀-ͯ]", "", normalized)
    return result.replace("ı", "i")


def _extract_trailing_numbers(text: str) -> Tuple[List[str], str]:
    """Satır sonundan sayısal değerleri (tutar/bakiye) ayır."""
    # Döviz son ekini kaldır
    text = re.sub(r"\s+(TL|TRY|EUR|USD)\s*$", "", text.strip(), flags=re.IGNORECASE)
    # İç döviz etiketlerini kaldır (Yapı Kredi: "2.785,37 TL 1.273.709,37 TL")
    text = re.sub(r"\s+(TL|TRY|EUR|USD)\s+", " ", text, flags=re.IGNORECASE)

    num_token = re.compile(r"[+-]?[\d]+(?:[.,][\d]+)*")
    tokens = list(num_token.finditer(text))
    if not tokens:
        return [], text

    result_nums = []
    cut_pos = len(text)

    for token in reversed(tokens[-2:]):
        between = text[token.end():cut_pos].strip()
        if between and not all(c in " \t" for c in between):
            break
        result_nums.insert(0, token.group())
        cut_pos = token.start()

    remaining = text[:cut_pos].strip()
    return result_nums, remaining


def _smart_parse_number(text: str) -> Optional[float]:
    """Türk formatı sayıyı akıllıca ayrıştır (OCR desteği)."""
    if not text:
        return None
    text = _strip_currency_suffix(text.strip())

    negative = text.startswith("-")
    positive = text.startswith("+")
    if negative or positive:
        text = text[1:]

    if not re.match(r"^[\d.,]+$", text):
        return None

    parts_comma = text.split(",")
    parts_dot = text.split(".")

    # Standart Türk formatı: 1.234,56
    if "," in text and len(parts_comma) == 2 and len(parts_comma[1]) <= 2:
        integer_part = parts_comma[0].replace(".", "")
        try:
            val = float(f"{integer_part}.{parts_comma[1]}")
            return -val if negative else val
        except ValueError:
            pass

    # OCR hatalı: virgülsüz, noktalar var
    if "," not in text and "." in text:
        last_dot_part = parts_dot[-1]
        if len(last_dot_part) <= 2:
            integer_parts = ".".join(parts_dot[:-1])
            integer_clean = integer_parts.replace(".", "")
            try:
                val = float(f"{integer_clean}.{last_dot_part}")
                return -val if negative else val
            except ValueError:
                pass
        elif len(last_dot_part) == 3:
            clean = text.replace(".", "")
            try:
                val = float(clean)
                return -val if negative else val
            except ValueError:
                pass

    clean = text.replace(".", "").replace(",", "")
    try:
        val = float(clean)
        return -val if negative else val
    except ValueError:
        return None
