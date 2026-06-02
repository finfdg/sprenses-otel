"""Otel rezervasyon şemaları."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ReservationResponse(BaseModel):
    id: int
    rec_id: int
    agency: Optional[str] = None
    room_type: Optional[str] = None
    voucher: Optional[str] = None
    guests: Optional[str] = None
    checkin_date: date
    checkout_date: date
    nights: int
    record_date: date
    board: Optional[str] = None
    vip_type: Optional[str] = None
    rooms: int
    adult: int
    child_paid: int
    child_free: int
    baby: int
    nation: Optional[str] = None
    net_amount: Optional[float] = None
    currency: Optional[str] = None
    eur_total: float
    per_room: Optional[float] = None
    per_adult: Optional[float] = None
    rez_status: Optional[str] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True


class ReservationUploadResponse(BaseModel):
    id: int
    file_name: str
    hotel_name: Optional[str] = None
    period_checkin_start: Optional[date] = None
    period_checkin_end: Optional[date] = None
    period_record_start: Optional[date] = None
    period_record_end: Optional[date] = None
    total_rows: int
    new_rows: int
    updated_rows: int
    uploaded_by: Optional[int] = None
    uploader_name: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class RemovalCandidate(BaseModel):
    """Excel kapsamında olduğu halde dosyada bulunmayan rezervasyon — olası iptal."""
    id: int
    rec_id: int
    agency: Optional[str] = None
    room_type: Optional[str] = None
    voucher: Optional[str] = None
    guests: Optional[str] = None
    checkin_date: date
    checkout_date: date
    nights: int
    record_date: date
    rooms: int
    nation: Optional[str] = None
    eur_total: float
    rez_status: Optional[str] = None
    status: Optional[str] = None


class ReservationUploadResult(BaseModel):
    upload_id: int
    file_name: str
    hotel_name: Optional[str] = None
    period_checkin_start: Optional[date] = None
    period_checkin_end: Optional[date] = None
    total_rows: int
    new_rows: int
    updated_rows: int
    removal_candidates: List[RemovalCandidate] = Field(default_factory=list)


class BulkDeleteRequest(BaseModel):
    """Toplu silme isteği — silinecek rezervasyon ID'leri."""
    ids: List[int] = Field(default_factory=list)


class BulkDeleteResult(BaseModel):
    deleted: int = 0
    skipped: int = 0
    skipped_reasons: List[str] = Field(default_factory=list)


class KpiData(BaseModel):
    total_rez: int
    total_eur: float
    total_room_nights: int
    total_guest_nights: int
    total_pax: int
    total_adult: int
    total_child_paid: int
    total_child_free: int
    total_baby: int
    adr: float
    avg_los: float
    definite_count: int
    option_count: int
    # Doluluk metrikleri
    total_capacity: int  # SUM(room_types.total_rooms) — otelin toplam oda kapasitesi
    date_range_days: int  # Doluluk paydasındaki gün sayısı (filtre veya rezervasyon aralığı)
    occupancy_pct: float  # total_room_nights / (total_capacity × date_range_days) × 100


class MonthlyRow(BaseModel):
    month: str  # YYYY-MM
    rez: int  # O ayda en az 1 gece düşen rez sayısı (DISTINCT) — birden fazla aya yayılan rez birden fazla satırda görünür
    room_nights: int  # O ayda gerçekleşen oda-gece (rooms × o aydaki gece sayısı)
    pax: int  # O ayda gerçekleşen konuk-gece (pax × o aydaki gece sayısı)
    eur: float  # O aya orantılanan ciro (eur_total × o_aydaki_gece / total_nights)
    capacity_nights: int = 0  # Toplam mevcut oda-gece (total_capacity × ayın filtredeki gün sayısı)
    empty_nights: int = 0  # capacity_nights - room_nights (boş oda-gece)
    occupancy_pct: float = 0.0  # room_nights / capacity_nights × 100


class AgencyRow(BaseModel):
    name: str
    rez: int
    room_nights: int
    pax: int
    eur: float
    pct: float


class NationRow(BaseModel):
    code: str
    rez: int
    room_nights: int
    eur: float
    pct: float


class TypeRow(BaseModel):
    name: str
    rez: int
    room_nights: int
    eur: float
    pct: float
    total_rooms: int = 0  # Bu tipte toplam fiziksel oda sayısı (room_types tablosundan)
    occupancy_pct: float = 0.0  # tip_room_nights / (tip_total_rooms × date_range_days) × 100


class BoardRow(BaseModel):
    name: str
    rez: int
    eur: float
    pct: float


class PickupRow(BaseModel):
    month: str  # YYYY-MM
    rez: int
    eur: float
    pct: float


class LosBucket(BaseModel):
    bucket: str  # "1", "2", ..., "15-21", "22+"
    count: int


class DailyOccupancyRow(BaseModel):
    """Bir günün doluluk detayı — aylık dağılımın drill-down'ı için."""
    date: date  # YYYY-MM-DD
    weekday: int  # 0=Pazartesi ... 6=Pazar (ISO)
    room_nights: int  # O gün konaklayan oda sayısı
    capacity: int  # Toplam mevcut oda (total_capacity, sabit)
    empty: int  # capacity - room_nights
    occupancy_pct: float  # room_nights / capacity × 100
    pax: int  # O gün konaklayan kişi sayısı
    eur: float  # O güne orantılanmış ciro (eur_total / nights)
    checkin_count: int  # O gün giriş yapan rez sayısı
    checkout_count: int  # O gün çıkış yapan rez sayısı


class DailyOccupancyResponse(BaseModel):
    """Aylık drill-down — gün listesi + ay özeti."""
    month: str  # YYYY-MM
    days: List[DailyOccupancyRow]
    total_capacity: int  # Aktif room_types.total_rooms toplamı
    avg_occupancy_pct: float  # Ay ortalama doluluk
    peak_date: Optional[date] = None  # En yüksek doluluk günü
    peak_occupancy_pct: float = 0.0
    low_date: Optional[date] = None  # En düşük doluluk günü
    low_occupancy_pct: float = 0.0


class LeadTimeStats(BaseModel):
    avg: float
    median: int
    min: int
    max: int


class SummaryResponse(BaseModel):
    kpi: KpiData
    monthly: List[MonthlyRow]
    by_agency: List[AgencyRow]
    by_nation: List[NationRow]
    by_room_type: List[TypeRow]
    by_board: List[BoardRow]
    pickup: List[PickupRow]
    los_buckets: List[LosBucket]
    lead_time: LeadTimeStats
