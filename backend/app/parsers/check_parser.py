"""Verilen çekler Excel parser."""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedCheck:
    check_type: Optional[str]
    sequence_no: Optional[int]
    check_no: str
    vendor_code: Optional[str]
    vendor_name: str
    description: Optional[str]
    city: Optional[str]
    due_date: date
    amount_tl: float
    currency: str
    amount_currency: float
    transaction_type: Optional[str]


@dataclass
class CheckParseResult:
    checks: List[ParsedCheck] = field(default_factory=list)


def parse_check_excel(file_path: str) -> CheckParseResult:
    """Verilen çekler Excel dosyasını ayrıştır.

    Kolon sırası (başlık yok):
    0: Çek tipi (Yerel)
    1: Sıra no
    2: Çek no
    3: Hesap kodu (cari)
    4: Alıcı adı
    5: Açıklama
    6: Şehir
    7: Vade tarihi
    8: TL tutarı
    9: Para birimi (TL/EUR)
    10: Döviz tutarı
    11: İşlem tipi (Verilen Çek)
    """
    import xlrd

    wb = xlrd.open_workbook(file_path)
    ws = wb.sheet_by_index(0)

    result = CheckParseResult()

    for r in range(ws.nrows):
        # Boş satırları atla
        check_no_cell = ws.cell(r, 2)
        if not check_no_cell.value:
            continue

        # Sıra no sayı olmalı
        seq_cell = ws.cell(r, 1)
        if not isinstance(seq_cell.value, (int, float)):
            continue

        try:
            # Vade tarihi
            date_cell = ws.cell(r, 7)
            if date_cell.ctype == 3 and date_cell.value:  # XL_CELL_DATE
                dt = xlrd.xldate_as_datetime(date_cell.value, wb.datemode)
                due_date = dt.date()
            else:
                continue  # Tarih yoksa atla

            # Tutarlar
            amount_tl = float(ws.cell(r, 8).value or 0)
            currency = str(ws.cell(r, 9).value or "TL").strip()
            amount_currency = float(ws.cell(r, 10).value or 0)

            check = ParsedCheck(
                check_type=str(ws.cell(r, 0).value or "").strip() or None,
                sequence_no=int(seq_cell.value),
                check_no=str(int(check_no_cell.value) if isinstance(check_no_cell.value, float) else check_no_cell.value).strip(),
                vendor_code=str(ws.cell(r, 3).value or "").strip() or None,
                vendor_name=str(ws.cell(r, 4).value or "").strip(),
                description=str(ws.cell(r, 5).value or "").strip() or None,
                city=str(ws.cell(r, 6).value or "").strip() or None,
                due_date=due_date,
                amount_tl=amount_tl,
                currency=currency,
                amount_currency=amount_currency,
                transaction_type=str(ws.cell(r, 11).value or "").strip() or None,
            )
            result.checks.append(check)
        except Exception as e:
            logger.warning("Satır %d ayrıştırılamadı: %s", r, e)
            continue

    return result
