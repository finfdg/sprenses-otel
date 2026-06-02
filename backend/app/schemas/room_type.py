"""Oda tipi Pydantic şemaları."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class RoomTypeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=40)
    name: str = Field(..., min_length=1, max_length=120)
    total_rooms: int = Field(..., ge=0)
    max_occupancy: int = Field(2, ge=1, le=20)
    sort_order: int = Field(0, ge=0)
    is_active: bool = True
    description: Optional[str] = None

    @field_validator("code")
    @classmethod
    def code_strip_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: str) -> str:
        return v.strip()


class RoomTypeUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=40)
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    total_rooms: Optional[int] = Field(None, ge=0)
    max_occupancy: Optional[int] = Field(None, ge=1, le=20)
    sort_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    description: Optional[str] = None

    @field_validator("code")
    @classmethod
    def code_strip_upper(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().upper() if v else v

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v


class RoomTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    total_rooms: int
    max_occupancy: int
    sort_order: int
    is_active: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoomTypeListResponse(BaseModel):
    """Liste yanıtı — UI'da toplam kapasiteyi göstermek için total_capacity de döner."""
    items: list[RoomTypeResponse]
    total_capacity: int  # SUM(total_rooms) — otel toplam oda sayısı
    active_count: int
