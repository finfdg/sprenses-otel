"""TCMB (Türkiye Cumhuriyet Merkez Bankası) döviz kuru çekme yardımcıları."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import httpx
from lxml import etree

logger = logging.getLogger(__name__)

CURRENCIES = ["USD", "EUR", "GBP"]

HISTORICAL_URL_TEMPLATE = "https://www.tcmb.gov.tr/kurlar/{yyyymm}/{ddmmyyyy}.xml"
TODAY_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
HOURLY_URL_TEMPLATE = "https://www.tcmb.gov.tr/reeskontkur/{yyyymm}/{ddmmyyyy}-{hhmm}.xml"
HOURLY_SLOTS = ["1500", "1400", "1300", "1200", "1100", "1000"]  # En son saatten geriye


@dataclass
class TCMBRate:
    currency_code: str
    currency_name: Optional[str]
    unit: int
    forex_buying: Optional[float]
    forex_selling: Optional[float]
    banknote_buying: Optional[float]
    banknote_selling: Optional[float]


@dataclass
class TCMBResponse:
    date: date
    rates: List[TCMBRate]


def _parse_float(text: Optional[str]) -> Optional[float]:
    """XML metin içeriğinden güvenli float parse."""
    if not text or not text.strip():
        return None
    try:
        return float(text.strip())
    except (ValueError, TypeError):
        return None


def _build_url(target_date: date) -> str:
    """Belirli tarih için TCMB URL'i oluştur."""
    yyyymm = target_date.strftime("%Y%m")
    ddmmyyyy = target_date.strftime("%d%m%Y")
    return HISTORICAL_URL_TEMPLATE.format(yyyymm=yyyymm, ddmmyyyy=ddmmyyyy)


def parse_tcmb_xml(xml_content: bytes) -> Optional[TCMBResponse]:
    """TCMB XML yanıtını parse edip hedef dövizlerin kurlarını çıkar."""
    try:
        root = etree.fromstring(xml_content)
    except etree.XMLSyntaxError as e:
        logger.error("TCMB XML ayrıştırma hatası: %s", e)
        return None

    # Tarih al
    date_str = root.get("Tarih")  # "09.03.2026"
    if not date_str:
        return None

    parts = date_str.split(".")
    try:
        rate_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        logger.error("TCMB tarih ayrıştırma hatası: %s", date_str)
        return None

    rates: List[TCMBRate] = []
    for currency_el in root.findall("Currency"):
        code = currency_el.get("Kod") or currency_el.get("CurrencyCode")
        if code not in CURRENCIES:
            continue

        unit_text = currency_el.findtext("Unit")
        rate = TCMBRate(
            currency_code=code,
            currency_name=currency_el.findtext("Isim"),
            unit=int(unit_text) if unit_text else 1,
            forex_buying=_parse_float(currency_el.findtext("ForexBuying")),
            forex_selling=_parse_float(currency_el.findtext("ForexSelling")),
            banknote_buying=_parse_float(currency_el.findtext("BanknoteBuying")),
            banknote_selling=_parse_float(currency_el.findtext("BanknoteSelling")),
        )
        rates.append(rate)

    return TCMBResponse(date=rate_date, rates=rates)


def fetch_rates_for_date_sync(target_date: date) -> Optional[TCMBResponse]:
    """Belirli tarih için TCMB'den günlük döviz kurlarını çek (senkron)."""
    url = _build_url(target_date)
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, follow_redirects=True)
            if resp.status_code == 404:
                logger.info("TCMB %s için veri yok (tatil/hafta sonu)", target_date)
                return None
            resp.raise_for_status()
            return parse_tcmb_xml(resp.content)
    except httpx.HTTPError as e:
        logger.error("TCMB istek hatası (%s): %s", target_date, e)
        return None


def fetch_today_rates_sync() -> Optional[TCMBResponse]:
    """TCMB today.xml'den güncel (saatlik güncellenen) kurları çek."""
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(TODAY_URL, follow_redirects=True)
            if resp.status_code == 404:
                logger.info("TCMB today.xml erişilemedi")
                return None
            resp.raise_for_status()
            return parse_tcmb_xml(resp.content)
    except httpx.HTTPError as e:
        logger.error("TCMB today.xml istek hatası: %s", e)
        return None


def _parse_turkish_float(text: Optional[str]) -> Optional[float]:
    """Türkçe formatlı sayıyı parse et: '51,2816' → 51.2816"""
    if not text or not text.strip():
        return None
    try:
        return float(text.strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


CURRENCY_NAMES = {"USD": "ABD DOLARI", "EUR": "EURO", "GBP": "İNGİLİZ STERLİNİ"}


def parse_hourly_xml(xml_content: bytes) -> Optional[TCMBResponse]:
    """TCMB saatlik kur XML'ini parse et (reeskontkur formatı)."""
    try:
        root = etree.fromstring(xml_content)
    except etree.XMLSyntaxError as e:
        logger.error("TCMB saatlik XML ayrıştırma hatası: %s", e)
        return None

    kur_liste = root.find("doviz_kur_liste")
    if kur_liste is None:
        return None

    # Tarih: gecerlilik_tarihi="2026-3-10"
    date_str = kur_liste.get("gecerlilik_tarihi")
    hour_str = kur_liste.get("saat", "")
    if not date_str:
        return None

    parts = date_str.split("-")
    try:
        rate_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        logger.error("TCMB saatlik tarih ayrıştırma hatası: %s", date_str)
        return None

    rates: List[TCMBRate] = []
    for kur_el in kur_liste.findall("kur"):
        code = (kur_el.findtext("doviz_cinsi") or "").strip()
        if code not in CURRENCIES:
            continue

        alis = _parse_turkish_float(kur_el.findtext("alis"))
        unit_text = kur_el.findtext("birim")

        # Saatlik kurda sadece alış fiyatı var → satışı da aynı değerle doldur
        rate = TCMBRate(
            currency_code=code,
            currency_name=CURRENCY_NAMES.get(code),
            unit=int(unit_text) if unit_text else 1,
            forex_buying=alis,
            forex_selling=alis,
            banknote_buying=None,
            banknote_selling=None,
        )
        rates.append(rate)

    if not rates:
        return None

    logger.info("TCMB saatlik kur parse: %s saat %s — %d döviz", rate_date, hour_str, len(rates))
    return TCMBResponse(date=rate_date, rates=rates)


def fetch_hourly_rates_sync(target_date: date) -> Optional[TCMBResponse]:
    """Belirli tarih için TCMB saatlik kurlarını çek. En son yayınlanan saati dener."""
    yyyymm = target_date.strftime("%Y%m")
    ddmmyyyy = target_date.strftime("%d%m%Y")

    try:
        with httpx.Client(timeout=15.0) as client:
            for hhmm in HOURLY_SLOTS:
                url = HOURLY_URL_TEMPLATE.format(yyyymm=yyyymm, ddmmyyyy=ddmmyyyy, hhmm=hhmm)
                resp = client.get(url, follow_redirects=True)
                if resp.status_code == 200:
                    result = parse_hourly_xml(resp.content)
                    if result and result.rates:
                        logger.info("TCMB saatlik kur bulundu: %s saat %s", target_date, hhmm)
                        return result
                # 404 → o saat henüz yayınlanmamış, bir önceki saati dene
            logger.info("TCMB %s için saatlik kur yok (iş günü değil veya saat erken)", target_date)
            return None
    except httpx.HTTPError as e:
        logger.error("TCMB saatlik kur istek hatası (%s): %s", target_date, e)
        return None
