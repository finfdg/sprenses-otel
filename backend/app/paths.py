"""Merkezi dosya-sistemi yolları — `__file__` derinliğine bağlı hesapların TEK kaynağı.

NEDEN VAR (2026-09-02 yeniden yapılandırma)
    Yeniden yapılandırmadan önce 15 modül kendi konumundan `os.path.dirname(...)` zinciriyle
    `backend/`, `otel/` ve `uploads/` dizinlerini türetiyordu. Bir dosya bir dizin derine
    taşınınca bu zincir SESSİZCE başka bir yere işaret eder (yüklemeler `app/uploads`'a
    yazılır, OCR tessdata bulunamaz, QNB yenileme token'ı kaybolur) ve hiçbir test kırmızı
    olmaz. Bu modül `app/` paketinin kökünde durur; taşınmaz. Diğer modüller yolları
    buradan alır → dosya taşımaları yol hesabını etkilemez.

KURAL
    Yeni kodda `__file__` tabanlı proje-dizini hesabı YAZMA; buradaki sabitleri kullan.
    `tests/test_paths.py` çözümlenen değerleri kilitler.
"""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent          # backend/app
BACKEND_DIR = APP_DIR.parent                        # backend/
REPO_ROOT = BACKEND_DIR.parent                      # otel/ (proje kökü)

UPLOADS_DIR = BACKEND_DIR / "uploads"               # kullanıcı yüklemeleri (git dışı)
LOGS_DIR = BACKEND_DIR / "logs"
TESSDATA_DIR = BACKEND_DIR / "tessdata"             # OCR dil verisi
VENV_DIR = BACKEND_DIR / "venv"
CRON_DENETIM_SCRIPT = BACKEND_DIR / "cron_denetim_auto.py"
QNB_REFRESH_TOKEN_FILE = REPO_ROOT / ".qnb_refresh_token"   # gitignore'lu döner token


def uploads_subdir(*parts: str) -> str:
    """`backend/uploads/<parts...>` yolunu str olarak döndür (os.path tabanlı eski API'lerle uyumlu)."""
    return os.path.join(str(UPLOADS_DIR), *parts)
