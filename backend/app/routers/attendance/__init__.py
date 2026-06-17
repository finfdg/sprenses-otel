"""Personel Devam Takip (PDKS) — kiosk dönen QR, telefon basışı, yönetici paneli.

Akış:
- Girişteki ekran `/devam/ekran?key=KIOSK_KEY` → `GET /attendance/kiosk/qr` ile
  her ~10sn'de dönen QR gösterir. QR, `PUBLIC/devam?k=<token>` URL'ini taşır.
- Personel telefonun YERLEŞİK kamerasıyla QR'ı okutur → URL açılır → kimlik çerezi
  (pdks_token) + k token doğrulanır → giriş/çıkış kaydedilir.
- Personel kimliği: kişisel `access_token` (kurulum linki bir kez açılınca çerez olur).

Güvenlik:
- Zaman-damgalı token HMAC(SECRET, unix_ts) — geçerlilik = panel `refresh_sec` + GRACE(3sn).
- Tek kullanım yerine personel-bazlı debounce (çift basışı engeller).
- Yönetici işlemleri require_permission(hr.attendance); kiosk/setup/punch public.
- Bu modül onay akışından muaftır (Sunucu/Yedekleme gibi ops modülü).

Paket yapısı (1189-satır tek dosyadan bölündü — 2026-06-17):
- `_helpers.py`  — ortak sabitler/token-cihaz-log yardımcıları/Excel parser/şemalar (`import *`)
- `kiosk.py`     — public kiosk + personel kimlik/basış + QR ayarları
- `personnel.py` — yönetici personel CRUD + Excel içe aktarma + QR kart + cihaz sıfırlama
- `logs.py`      — yönetici izleme/raporlar + elle giriş/düzenle/sil + onay bekleyenler
"""
from fastapi import APIRouter

from .kiosk import router as _kiosk_router
from .logs import router as _logs_router
from .personnel import router as _personnel_router

router = APIRouter()
router.include_router(_kiosk_router)
router.include_router(_personnel_router)
router.include_router(_logs_router)
