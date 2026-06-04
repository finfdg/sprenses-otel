"""PDKS çalışma-zamanı ayarları — yönetici panelinden düzenlenir (tek satır, id=1).

Şimdilik tek tunable: kiosk QR token'ının geçerlilik süresi (saniye). Ekran yenileme
süresi bundan türetilir (her zaman TTL'den kısa). İleride başka PDKS ayarı gerekirse
bu tabloya kolon eklenir.
"""
from sqlalchemy import Column, DateTime, Integer, func

from app.database import Base

# QR token varsayılan geçerlilik süresi (saniye) — migration tek satırı bununla kurar
DEFAULT_TOKEN_TTL_SEC = 7
MIN_TOKEN_TTL_SEC = 5
MAX_TOKEN_TTL_SEC = 120


class AttendanceSetting(Base):
    __tablename__ = "attendance_settings"

    id = Column(Integer, primary_key=True)  # daima 1 (tekil satır)
    token_ttl_sec = Column(Integer, nullable=False, default=DEFAULT_TOKEN_TTL_SEC)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
