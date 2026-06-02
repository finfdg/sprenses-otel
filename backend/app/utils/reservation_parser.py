"""Otel rezervasyon Crystal Reports XLS/XLSX ayrıştırıcısı.

Side Prenses Resort Hotel & Spa programının Crystal Reports ile ürettiği
rezervasyon raporlarını (xls/xlsx) okur ve dataclass listesine çevirir.

Beklenen yapı:
    R0: Otel adı (col 0) + 'Reservation Report' (col 1) + Print Date/Time
    R1: Checkin Date(s)/Sales Date(s)/Checkout Date(s)/Record Date(s) aralıkları
    R2: Boş
    R3: Sütun başlıkları (Room | RecId | Agency | Type | Voucher | Guests |
        C/In | C/Out | # | Record | Board | Viptype | Rm | Adl | Pch | Fch |
        Bby | Nation | Net | Curr | EUR Total | PerRoom | PerAdult | Rez.St | Status)
    R4+: Veri satırları (boş satırlar ve raporun sonundaki "Room/Adult/EUR Total"
         alt-toplam satırları atlanır)
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional


@dataclass
class ParsedReservation:
    rec_id: int
    agency: str
    room_type: str
    voucher: str
    guests: str
    checkin_date: date
    checkout_date: date
    nights: int
    record_date: date
    board: str
    vip_type: str
    rooms: int
    adult: int
    child_paid: int
    child_free: int
    baby: int
    nation: str
    net_amount: float
    currency: str
    eur_total: float
    per_room: float
    per_adult: float
    rez_status: str
    status: str


@dataclass
class ParseResult:
    hotel_name: Optional[str] = None
    checkin_start: Optional[date] = None
    checkin_end: Optional[date] = None
    record_start: Optional[date] = None
    record_end: Optional[date] = None
    reservations: List[ParsedReservation] = field(default_factory=list)


# Excel serial date epoch (Lotus/Excel 1900 sistemi, 1900-02-29 hatası dahil)
_EXCEL_EPOCH = datetime(1899, 12, 30)


def _serial_to_date(value) -> Optional[date]:
    """Excel serial sayısını date'e dönüştür. Geçersizse None."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # 1 (1900-01-01) — 100000 (2173) aralığını makul kabul et
    if f < 1 or f > 100000:
        return None
    return (_EXCEL_EPOCH + timedelta(days=f)).date()


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return s


def parse_reservation_excel(file_path: str) -> ParseResult:
    """Verilen dosyayı (xls/xlsx) ayrıştır ve `ParseResult` döndür."""
    ext = file_path.rsplit(".", 1)[-1].lower()
    if ext == "xls":
        rows = _read_xls(file_path)
    elif ext == "xlsx":
        rows = _read_xlsx(file_path)
    else:
        raise ValueError(f"Desteklenmeyen uzantı: .{ext}")

    if len(rows) < 5:
        raise ValueError("Dosya beklenenden çok az satır içeriyor (R0-R3 + veri yok)")

    result = ParseResult()

    # ── R0: otel adı ─────────────────────────────────────────
    if rows[0] and len(rows[0]) > 0:
        result.hotel_name = _to_str(rows[0][0])[:100] or None

    # ── R1: tarih aralıkları (sabit kolon pozisyonları) ──────
    if len(rows) > 1 and len(rows[1]) >= 21:
        r1 = rows[1]
        result.checkin_start = _serial_to_date(r1[2])
        result.checkin_end = _serial_to_date(r1[4])
        result.record_start = _serial_to_date(r1[18])
        result.record_end = _serial_to_date(r1[20])

    # ── R3: header doğrulaması ───────────────────────────────
    header = [_to_str(c).lower() for c in rows[3]] if len(rows) > 3 else []
    expected = ["recid", "agency", "type", "eur total"]
    if not all(any(e in h for h in header) for e in expected):
        raise ValueError(
            "Dosya başlık satırı tanınmadı. "
            "Beklenen sütunlar (RecId, Agency, Type, EUR Total) bulunamadı."
        )

    # ── R4+: veri satırları ──────────────────────────────────
    for raw in rows[4:]:
        if not raw or len(raw) < 21:
            continue
        rec_raw = raw[1] if len(raw) > 1 else None
        # RecId sayısal değilse satır atlanır (boşluk veya alt-toplam: "Room", "Adult", "EUR Total")
        if not isinstance(rec_raw, (int, float)) or rec_raw == "":
            continue
        try:
            rec_id = int(float(rec_raw))
        except (TypeError, ValueError):
            continue
        if rec_id <= 0:
            continue

        checkin = _serial_to_date(raw[6])
        checkout = _serial_to_date(raw[7])
        record = _serial_to_date(raw[9])
        if not checkin or not checkout or not record:
            # Tarihsiz satır işlenemez
            continue

        result.reservations.append(ParsedReservation(
            rec_id=rec_id,
            agency=_to_str(raw[2])[:50],
            room_type=_to_str(raw[3])[:40],
            voucher=_to_str(raw[4])[:40],
            guests=_to_str(raw[5]),
            checkin_date=checkin,
            checkout_date=checkout,
            nights=_to_int(raw[8]),
            record_date=record,
            board=_to_str(raw[10])[:10],
            vip_type=_to_str(raw[11])[:20],
            rooms=_to_int(raw[12], default=1),
            adult=_to_int(raw[13]),
            child_paid=_to_int(raw[14]),
            child_free=_to_int(raw[15]),
            baby=_to_int(raw[16]),
            nation=_to_str(raw[17])[:10],
            net_amount=_to_float(raw[18]),
            currency=_to_str(raw[19])[:5],
            eur_total=_to_float(raw[20]),
            per_room=_to_float(raw[21]) if len(raw) > 21 else 0.0,
            per_adult=_to_float(raw[22]) if len(raw) > 22 else 0.0,
            rez_status=_to_str(raw[23])[:20] if len(raw) > 23 else "",
            status=_to_str(raw[24])[:20] if len(raw) > 24 else "",
        ))

    return result


def _read_xls(file_path: str) -> List[list]:
    """xls (CDF V2 / OLE2) dosyasını oku — xlrd."""
    import xlrd  # lokal import: xlsx-only dosyalarda yüklemeye gerek yok
    wb = xlrd.open_workbook(file_path, formatting_info=False)
    sheet = wb.sheet_by_index(0)
    rows: List[list] = []
    for r in range(sheet.nrows):
        rows.append([sheet.cell_value(r, c) for c in range(sheet.ncols)])
    return rows


def _read_xlsx(file_path: str) -> List[list]:
    """xlsx dosyasını oku — openpyxl.

    Crystal Reports xlsx ihracı tarihleri normalde datetime olarak yazar; bu
    durumda `_serial_to_date` None döner. Bu yüzden datetime'ları serial sayısına
    çeviriyoruz — tek bir kod yolu kalır.
    """
    import openpyxl
    from datetime import datetime as _dt
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    sheet = wb.active
    rows: List[list] = []
    for raw_row in sheet.iter_rows(values_only=True):
        row = []
        for v in raw_row:
            if isinstance(v, _dt):
                # datetime → Excel serial
                delta = (v - _EXCEL_EPOCH).days + (v - _EXCEL_EPOCH).seconds / 86400.0
                row.append(delta)
            elif v is None:
                row.append("")
            else:
                row.append(v)
        rows.append(row)
    return rows
