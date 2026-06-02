"""Kredi kartı ekstre PDF parser — Çoklu banka desteği.

Desteklenen formatlar:
- Garanti BBVA (Bonus Business Card)
- VakıfBank (BusinessCard)
- QNB Finansbank (Corporate)
- Yapı Kredi (World)
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

import pymupdf


@dataclass
class ParsedCCTransaction:
    islem_tarihi: Optional[date]
    aciklama: str
    kategori: Optional[str]
    taksit_bilgi: Optional[str]
    tutar: float
    is_credit: bool
    bonus: Optional[float] = None


@dataclass
class ParsedCCStatement:
    bank_name: str = ""
    kart_no: str = ""
    kart_limiti: float = 0
    kesim_tarihi: Optional[date] = None
    son_odeme_tarihi: Optional[date] = None
    toplam_borc: float = 0
    asgari_odeme: float = 0
    onceki_bakiye: float = 0
    donem_harcama: float = 0
    faiz_ucret: float = 0
    donem_odeme: float = 0
    ekstre_no: str = ""
    transactions: List[ParsedCCTransaction] = field(default_factory=list)


# ─── Ortak yardımcılar ────────────────────────────────────────────────


_TR_MONTHS = {
    'ocak': 1, 'şubat': 2, 'mart': 3, 'nisan': 4,
    'mayıs': 5, 'haziran': 6, 'temmuz': 7, 'ağustos': 8,
    'eylül': 9, 'ekim': 10, 'kasım': 11, 'aralık': 12,
}


def _parse_amount(text: str) -> Tuple[float, bool]:
    """Türk veya İngiliz formatlı tutarı parse et. (tutar, is_credit) döndürür.

    Türk: 1.234.567,89 (nokta=binlik, virgül=ondalık)
    İngiliz: 1,234,567.89 (virgül=binlik, nokta=ondalık)
    """
    text = text.strip()
    is_credit = text.startswith('+') or text.endswith('+')
    text = text.strip('+-').strip()

    # Format algıla: son ayırıcı virgül mü nokta mı?
    last_comma = text.rfind(',')
    last_dot = text.rfind('.')

    if last_comma > last_dot:
        # Türk formatı: 1.234.567,89
        text = text.replace('.', '').replace(',', '.')
    else:
        # İngiliz formatı: 1,234,567.89
        text = text.replace(',', '')

    try:
        return abs(float(text)), is_credit
    except ValueError:
        return 0.0, False


def _parse_date_slash(text: str) -> Optional[date]:
    """DD/MM/YYYY veya DD.MM.YYYY formatını parse et."""
    m = re.match(r'(\d{1,2})[./](\d{2})[./](\d{4})', text.strip())
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _parse_date_tr(text: str) -> Optional[date]:
    """'24 Şubat 2026' formatını parse et."""
    m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})', text.strip())
    if m:
        month = _TR_MONTHS.get(m.group(2).lower())
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    return None


def _parse_date(text: str) -> Optional[date]:
    """Tüm tarih formatlarını dene."""
    return _parse_date_slash(text) or _parse_date_tr(text)


def _extract_amount_from_text(text: str) -> Optional[float]:
    """Metin içindeki ilk TL tutarını bul."""
    m = re.search(r'([\d.,]+)\s*TL', text)
    if m:
        amt, _ = _parse_amount(m.group(1))
        return amt
    return None


def _extract_text(file_path: str) -> str:
    """PDF'den tüm metni çıkar. Kontrol karakterlerini temizle."""
    doc = pymupdf.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    doc.close()
    # Kontrol karakterlerini temizle (QNB PDF'lerinde \x00-\x0F arası var)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text


def _detect_bank(text: str) -> str:
    """PDF metninden bankayı algıla."""
    upper = text[:3000].upper()
    if 'BONUS' in upper and 'GARANTİ' in upper.replace('GARANTI', 'GARANTİ'):
        return 'garanti'
    if 'VAKIFBANK' in upper or 'VAKIF' in upper and 'BUSINESSCARD' in upper:
        return 'vakifbank'
    if 'QNB' in upper and ('CORPORATE' in upper or 'FİNANSBANK' in upper or 'FINANSBANK' in upper):
        return 'qnb'
    if 'YAPI' in upper and 'KREDİ' in upper or 'YAPI KREDİ' in upper.replace('KREDI', 'KREDİ'):
        return 'yapikredi'
    # Fallback — anahtar kelimelerle
    if 'BONUS' in upper:
        return 'garanti'
    if 'WORLDPUAN' in upper or 'WORLD' in upper:
        return 'yapikredi'
    if 'QNB' in upper:
        return 'qnb'
    if 'VAKIF' in upper:
        return 'vakifbank'
    return 'unknown'


# ─── Garanti BBVA Parser ──────────────────────────────────────────────


def _parse_garanti(text: str) -> ParsedCCStatement:
    """Garanti BBVA Bonus Business Card ekstresi."""
    result = ParsedCCStatement(bank_name="Garanti BBVA")
    lines = text.split('\n')

    i = 0
    current_category = None
    in_transactions = False

    while i < len(lines):
        line = lines[i].strip()

        if line == 'İşlem Tarihi' or line == 'Dönem İçi İşlemler':
            in_transactions = True
        if 'EKSTRE ÖZETİ' in line or 'EKSTRENİZ İLE İLGİLİ' in line:
            in_transactions = False

        # Header
        if 'Kart Numarası' in line and i + 1 < len(lines) and not result.kart_no:
            result.kart_no = lines[i + 1].strip()
            i += 1; continue

        if 'Kart Limiti' in line and i + 1 < len(lines) and result.kart_limiti == 0:
            amt = _extract_amount_from_text(lines[i + 1])
            if amt: result.kart_limiti = amt

        if 'Hesap Kesim Tarihi' in line and i + 1 < len(lines) and not result.kesim_tarihi:
            d = _parse_date(lines[i + 1].strip())
            if d: result.kesim_tarihi = d; i += 1; continue

        if 'Son Ödeme Tarihi' in line and not result.son_odeme_tarihi:
            # Aynı satırda veya sonraki satırda olabilir
            d = _parse_date(line.split(':', 1)[-1].strip()) if ':' in line else None
            if not d and i + 1 < len(lines):
                d = _parse_date(lines[i + 1].strip())
            if d: result.son_odeme_tarihi = d

        if 'Toplam Borcunuz' in line and result.toplam_borc == 0:
            amt = _extract_amount_from_text(line) or (
                _extract_amount_from_text(lines[i + 1]) if i + 1 < len(lines) else None
            )
            if amt: result.toplam_borc = amt

        if 'Minimum Ödeme Tutarı' in line and result.asgari_odeme == 0:
            amt = _extract_amount_from_text(line) or (
                _extract_amount_from_text(lines[i + 1]) if i + 1 < len(lines) else None
            )
            if amt: result.asgari_odeme = amt

        if 'Ekstre No' in line:
            m = re.search(r'Ekstre No\s*:\s*(.+)', line)
            if m: result.ekstre_no = m.group(1).strip()

        # Özet satırı
        if 'Önceki Bakiye' in line:
            for j in range(i + 1, min(i + 5, len(lines))):
                vals = re.findall(r'([\d.,]+)\s*TL', lines[j])
                if len(vals) >= 4:
                    result.onceki_bakiye, _ = _parse_amount(vals[0])
                    result.donem_harcama, _ = _parse_amount(vals[1])
                    result.faiz_ucret, _ = _parse_amount(vals[2])
                    result.donem_odeme, _ = _parse_amount(vals[3])
                    break

        # Kategori başlıkları
        if 'BONUS PROGRAM ORTAKLARI' in line and 'DIŞI' not in line:
            current_category = "Bonus Program Ortakları"
        elif 'BONUS PROGRAM ORTAKLARI DIŞI' in line:
            current_category = None
        elif line in ('ARAÇ KİRALAMA', 'OTOMOBİL / TAMİR / BAKIM', 'MAIL / TELEFON ORDER',
                      'DİĞER', 'MARKET', 'YEME / İÇME', 'GİYİM', 'ELEKTRONİK',
                      'SEYAHAT', 'SAĞLIK', 'EĞİTİM', 'KONAKLAMA', 'SİGORTA'):
            current_category = line.title()

        # İşlemler
        if line == 'ÖNCEKİ DÖNEMDEN DEVİR EDİLEN TUTAR' and i + 1 < len(lines):
            amt, _ = _parse_amount(lines[i + 1].strip())
            if amt > 0:
                result.transactions.append(ParsedCCTransaction(
                    None, "Önceki Dönemden Devir", "Devir", None, amt, False))

        elif line == 'DÖNEM FAİZİ' and i + 1 < len(lines):
            amt, _ = _parse_amount(lines[i + 1].strip())
            if amt > 0:
                result.transactions.append(ParsedCCTransaction(
                    None, "Dönem Faizi", "Faiz", None, amt, False))

        elif in_transactions and _parse_date_tr(line):
            tx_date = _parse_date_tr(line)
            if i + 1 < len(lines):
                desc = lines[i + 1].strip()
                if 'ÖDEMENİZ İÇİN TEŞEKKÜR' in desc:
                    if i + 2 < len(lines):
                        amt, _ = _parse_amount(lines[i + 2].strip())
                        result.transactions.append(ParsedCCTransaction(
                            tx_date, "Ödeme", "Ödeme", None, amt, True))
                        i += 2
                else:
                    taksit = None
                    amt, is_cr = 0.0, False
                    for j in range(i + 2, min(i + 5, len(lines))):
                        nl = lines[j].strip()
                        if not nl or nl == 'bosluk': break
                        if 'Taksit' in nl or re.search(r'\d+x\d+=', nl):
                            taksit = nl
                        elif re.match(r'^[\d.,]+\+?$', nl):
                            amt, is_cr = _parse_amount(nl)
                    if amt > 0:
                        result.transactions.append(ParsedCCTransaction(
                            tx_date, desc, current_category, taksit, amt, is_cr))

        i += 1
    return result


# ─── VakıfBank Parser ─────────────────────────────────────────────────


def _vakif_get_value(lines: list, i: int) -> str:
    """VakıfBank formatında değer satırını bul (: atla)."""
    for j in range(i + 1, min(i + 3, len(lines))):
        nl = lines[j].strip()
        if nl and nl != ':':
            return nl
    return ""


def _parse_vakifbank(text: str) -> ParsedCCStatement:
    """VakıfBank BusinessCard ekstresi."""
    result = ParsedCCStatement(bank_name="VakıfBank")
    lines = text.split('\n')

    in_transactions = False

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        # Header — VakıfBank formatında "anahtar", ":", "değer" ayrı satırlarda
        if line == 'Kart No' and not result.kart_no:
            val = _vakif_get_value(lines, i)
            if val and re.match(r'\d{4}', val):
                result.kart_no = val

        if line == 'Dönem Borcunuz' and result.toplam_borc == 0:
            val = _vakif_get_value(lines, i)
            amt = _extract_amount_from_text(val + ' TL' if 'TL' not in val else val)
            if amt: result.toplam_borc = amt

        if line == 'Asgari Ödeme Tutarı' and result.asgari_odeme == 0:
            val = _vakif_get_value(lines, i)
            amt = _extract_amount_from_text(val + ' TL' if 'TL' not in val else val)
            if amt: result.asgari_odeme = amt

        if line == 'Son Ödeme Tarihi' and not result.son_odeme_tarihi:
            val = _vakif_get_value(lines, i)
            d = _parse_date_slash(val)
            if d: result.son_odeme_tarihi = d

        if line == 'Hesap Kesim Tarihi' and not result.kesim_tarihi:
            val = _vakif_get_value(lines, i)
            d = _parse_date_slash(val)
            if d: result.kesim_tarihi = d

        if line == 'Limitiniz' and result.kart_limiti == 0:
            val = _vakif_get_value(lines, i)
            amt = _extract_amount_from_text(val + ' TL' if 'TL' not in val else val)
            if amt: result.kart_limiti = amt

        # İşlem bölümü — VakıfBank: tarih → açıklama → tutar (her satırda)
        if 'İŞLEM TARİHİ' in line:
            in_transactions = True
            continue

        if line == 'HESAP ÖZETİ' or (line.startswith('Önceki Hesap Bakiyesi') and in_transactions):
            in_transactions = False

        if in_transactions and _parse_date_slash(line):
            tx_date = _parse_date_slash(line)
            if i + 1 < len(lines):
                desc = lines[i + 1].strip()
                # Kart sahibi satırını atla
                if re.match(r'\d{4}\*+\d{4}\s', desc):
                    i += 1
                    continue
                # Tutar sonraki satırda
                amt, is_cr = 0.0, False
                for j in range(i + 2, min(i + 4, len(lines))):
                    nl = lines[j].strip()
                    m_amt = re.match(r'^([+-]?[\d.,]+)$', nl)
                    if m_amt:
                        amt, is_cr = _parse_amount(m_amt.group(1))
                        break
                if amt > 0:
                    kategori = None
                    desc_up = desc.upper()
                    if 'FAİZ' in desc_up: kategori = "Faiz"
                    elif 'BSMV' in desc_up: kategori = "Vergi"
                    elif 'ÖDEME' in desc_up or 'TEŞEKKÜR' in desc_up:
                        is_cr = True; kategori = "Ödeme"
                    elif 'ÖNCEKİ DÖNEM' in desc_up or 'BAKİYE' in desc_up: kategori = "Devir"
                    result.transactions.append(ParsedCCTransaction(
                        tx_date, desc, kategori, None, amt, is_cr))

    return result


# ─── QNB Finansbank Parser ────────────────────────────────────────────


def _parse_qnb(text: str) -> ParsedCCStatement:
    """QNB Finansbank Corporate Card ekstresi."""
    result = ParsedCCStatement(bank_name="QNB")
    lines = text.split('\n')

    in_transactions = False

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        # Header — QNB formatında ":" ayrı satırda veya aynı satırda olabilir
        def _qnb_val(idx: int) -> str:
            """QNB satır değerini bul — ':' ayrı satırsa atla."""
            m = re.search(r':\s*(.+)', lines[idx].strip())
            if m and m.group(1).strip():
                return m.group(1).strip()
            for k in range(idx + 1, min(idx + 3, len(lines))):
                nl = lines[k].strip()
                if nl and nl != ':':
                    return nl
            return ""

        if ('Kredi Kart' in line and 'Numaras' in line) and not result.kart_no:
            val = _qnb_val(i)
            if val and val != ':': result.kart_no = val

        if 'Hesap Kesim Tarihi' in line and not result.kesim_tarihi:
            val = _qnb_val(i)
            d = _parse_date(val)
            if d: result.kesim_tarihi = d

        if ('Dnem Borcu' in line or 'Dönem Borcu' in line) and 'nceki' not in line and result.toplam_borc == 0:
            val = _qnb_val(i)
            # QNB İngiliz formatı: "1,051,612.47 TL"
            if 'TL' not in val: val = val + ' TL'
            amt = _extract_amount_from_text(val)
            if amt: result.toplam_borc = amt

        if 'Asgari' in line and ('deme' in line or 'Ödeme' in line) and result.asgari_odeme == 0:
            val = _qnb_val(i)
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.asgari_odeme = amt

        if 'Son' in line and ('deme Tarihi' in line or 'Ödeme Tarihi' in line) and not result.son_odeme_tarihi:
            # "Son Ödeme Tarihi: 16 Mart 2026, Pazartesi" formatı
            full_line = line
            for k in range(i + 1, min(i + 3, len(lines))):
                full_line += ' ' + lines[k].strip()
            m = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', full_line)
            if m:
                d = _parse_date_tr(m.group(1))
                if d: result.son_odeme_tarihi = d

        if 'Kredi Kart' in line and 'Limiti' in line and result.kart_limiti == 0:
            val = _qnb_val(i)
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.kart_limiti = amt

        # Özet
        if 'nceki Dnem' in line or 'Önceki Dönem' in line:
            # QNB'nin özet tablosu — sonraki satırlarda tutarlar
            if 'Bakiye' in line or i + 2 < len(lines):
                pass  # Satır satır parse zor, text akışı bozuk

        # İşlem bölümü
        if ('lem Tarihi' in line or 'İşlem Tarihi' in line) and ('lem A' in line or 'İşlem Açıklaması' in line):
            in_transactions = True
            continue

        if 'Hesap' in line and 'zetiniz' in line:
            in_transactions = False

        # İşlem header — QNB'de Türkçe karakterler bozuk olabilir
        if ('lem Tarihi' in line or 'İşlem Tarihi' in line) and ('lem A' in line or 'Tutar' in line or i + 1 < len(lines) and 'Tutar' in lines[i + 1]):
            in_transactions = True
            continue

        # "nceki Dnem Bakiyeniz" satırı
        if ('nceki Dnem Bakiyeniz' in line or 'Önceki Dönem Bakiyeniz' in line):
            in_transactions = True
            if i + 1 < len(lines):
                amt, _ = _parse_amount(lines[i + 1].strip())
                if amt > 0:
                    result.onceki_bakiye = amt
                    result.transactions.append(ParsedCCTransaction(
                        None, "Önceki Dönem Bakiyeniz", "Devir", None, amt, False))

        # Kart sahibi satırı — atla ama in_transactions devam etsin
        if re.match(r'(ASIL|EK) KART:', line):
            continue

        if 'Genel Toplam' in line or ('Hesap' in line and 'zetiniz' in line and 'nceki' not in line):
            in_transactions = False

        # QNB işlem satırları: tarih → açıklama → tutar → (taksit)
        if in_transactions and _parse_date_slash(line):
            tx_date = _parse_date_slash(line)
            if i + 1 < len(lines):
                desc = lines[i + 1].strip()
                amt, is_cr = 0.0, False
                taksit = None

                for j in range(i + 2, min(i + 5, len(lines))):
                    nl = lines[j].strip()
                    # Taksit: "3/3"
                    if re.match(r'^\d+/\d+$', nl):
                        taksit = nl
                        continue
                    # Tutar
                    m_amt = re.match(r'^(-?[\d.,]+)$', nl)
                    if m_amt:
                        amt, is_cr = _parse_amount(m_amt.group(1))
                        if nl.startswith('-'): is_cr = True
                        break

                if amt > 0:
                    kategori = None
                    if 'deme' in desc or 'Tesekk' in desc:
                        is_cr = True; kategori = "Ödeme"
                    elif 'Ekstre' in desc: kategori = "Ücret"
                    result.transactions.append(ParsedCCTransaction(
                        tx_date, desc, kategori, taksit, amt, is_cr))

    return result


# ─── Yapı Kredi Parser ────────────────────────────────────────────────


def _parse_yapikredi(text: str) -> ParsedCCStatement:
    """Yapı Kredi World Card ekstresi."""
    result = ParsedCCStatement(bank_name="Yapı Kredi")
    lines = text.split('\n')

    in_transactions = False

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        # Header — Yapı Kredi ": değer TL" formatında, aynı satırda veya sonraki
        def _yk_val(idx: int) -> str:
            m = re.search(r':\s*(.+)', lines[idx].strip())
            if m and m.group(1).strip():
                return m.group(1).strip()
            for k in range(idx + 1, min(idx + 3, len(lines))):
                nl = lines[k].strip()
                if nl and nl != ':':
                    return nl
            return ""

        if 'Kart Numarası' in line and not result.kart_no:
            val = _yk_val(i)
            # ":6508 37**" gibi ":"den başlayan değeri de yakala
            val = val.lstrip(':').strip()
            if re.match(r'\d{4}', val):
                result.kart_no = val

        if 'Hesap Kesim Tarihi' in line and not result.kesim_tarihi:
            val = _yk_val(i).lstrip(':').strip()
            d = _parse_date(val)
            if d: result.kesim_tarihi = d

        if 'Son Ödeme Tarihi' in line and not result.son_odeme_tarihi:
            val = _yk_val(i).lstrip(':').strip()
            d = _parse_date(val)
            if not d:
                # "Son Ödeme Tarihi: 2 Mart 2026" aynı satırda
                m = re.search(r':\s*(.+)', line)
                if m: d = _parse_date_tr(m.group(1).strip())
            if d: result.son_odeme_tarihi = d

        if 'Dönem Borcu' in line and result.toplam_borc == 0:
            val = _yk_val(i)
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.toplam_borc = amt

        if 'Asgari' in line and ('Tutar' in line or 'Ödeme' in line) and result.asgari_odeme == 0:
            val = _yk_val(i)
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.asgari_odeme = amt

        if ('Müşteri Limiti' in line or 'Kart Limiti' in line) and result.kart_limiti == 0:
            val = _yk_val(i)
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.kart_limiti = amt

        if 'Önceki Dönem Hesap Özeti Borcu' in line:
            val = _yk_val(i)
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.onceki_bakiye = amt

        if 'Dönem İçi Harcamalar' in line:
            val = _yk_val(i)
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.donem_harcama = amt

        if 'Dönem İçi Ödemeler' in line:
            val = _yk_val(i).lstrip('+')
            amt = _extract_amount_from_text(val if 'TL' in val else val + ' TL')
            if amt: result.donem_odeme = amt

        # İşlem bölümü
        if 'İşlem Tarihi' in line:
            in_transactions = True
            continue

        if 'PUAN ÖZETİ' in line or 'MESAJINIZ VAR' in line or line == 'TOPLAM':
            in_transactions = False

        # Önceki dönem borcu
        if in_transactions and 'ÖNCEKİ DÖNEM HESAP ÖZETİ BORCU' in line and i + 1 < len(lines):
            amt, _ = _parse_amount(lines[i + 1].strip())
            if amt > 0:
                result.onceki_bakiye = amt
                result.transactions.append(ParsedCCTransaction(
                    None, "Önceki Dönem Hesap Özeti Borcu", "Devir", None, amt, False))

        # Yapı Kredi işlem: "DD Ay YYYY" tarih → açıklama → tutar
        elif in_transactions and _parse_date_tr(line):
            tx_date = _parse_date_tr(line)
            if i + 1 < len(lines):
                desc = lines[i + 1].strip()
                amt, is_cr = 0.0, False
                taksit = None

                if 'ÖDEME' in desc.upper(): is_cr = True

                for j in range(i + 2, min(i + 6, len(lines))):
                    nl = lines[j].strip()
                    if 'taksid' in nl.lower():
                        taksit = nl
                        continue
                    m_amt = re.match(r'^([+-]?[\d.,]+)$', nl)
                    if m_amt:
                        amt, cr = _parse_amount(m_amt.group(1))
                        if nl.startswith('+') or is_cr: is_cr = True
                        break

                if amt > 0:
                    kategori = "Ödeme" if is_cr else None
                    if 'FAİZ' in desc.upper(): kategori = "Faiz"
                    result.transactions.append(ParsedCCTransaction(
                        tx_date, desc, kategori, taksit, amt, is_cr))

    return result


# ─── Ana parse fonksiyonu ─────────────────────────────────────────────


def parse_cc_statement(file_path: str) -> ParsedCCStatement:
    """Kredi kartı ekstresi parse et — bankayı otomatik algıla."""
    text = _extract_text(file_path)
    bank = _detect_bank(text)

    if bank == 'garanti':
        return _parse_garanti(text)
    elif bank == 'vakifbank':
        return _parse_vakifbank(text)
    elif bank == 'qnb':
        return _parse_qnb(text)
    elif bank == 'yapikredi':
        return _parse_yapikredi(text)
    else:
        # Bilinmeyen format — genel parse dene
        result = _parse_garanti(text)
        if not result.transactions:
            result = _parse_vakifbank(text)
        if not result.transactions:
            result = _parse_qnb(text)
        if not result.transactions:
            result = _parse_yapikredi(text)
        return result


# Geriye uyumluluk
parse_garanti_cc_statement = parse_cc_statement
