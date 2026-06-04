"""PDKS çalışma-zamanı ayarları — yönetici panelinden düzenlenir (tek satır, id=1).

Knob: **refresh_sec** = girişteki ekranda QR'ın ne sıklıkta değişeceği (saniye).
Güvenlik geçerliliği (token TTL) kodda `refresh_sec + TOKEN_GRACE_SEC` olarak türetilir
(taze QR'ı tararken pay bırakır). Böylece panele girilen sayı = ekranda görülen yenileme hızı.
İleride başka PDKS ayarı gerekirse bu tabloya kolon eklenir.
"""
from sqlalchemy import Column, DateTime, Integer, func

from app.database import Base

# QR ekran yenileme süresi (saniye) — migration tek satırı bununla kurar
DEFAULT_REFRESH_SEC = 7
MIN_REFRESH_SEC = 2
MAX_REFRESH_SEC = 120
# Token geçerliliği = refresh + grace (taze QR tarama payı)
TOKEN_GRACE_SEC = 3


class AttendanceSetting(Base):
    __tablename__ = "attendance_settings"

    id = Column(Integer, primary_key=True)  # daima 1 (tekil satır)
    refresh_sec = Column(Integer, nullable=False, default=DEFAULT_REFRESH_SEC)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
