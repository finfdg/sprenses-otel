import logging
import os
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.paths import LOGS_DIR, UPLOADS_DIR
from app.routers import (
    accounting,
    ai,
    approval,
    attendance,
    core,
    finance,
    hr,
    messages,
    sales,
    stock,
    system,
)

# ─── Merkezi Log Yapılandırması ──────────────────────────────────────────────
LOG_DIR = str(LOGS_DIR)
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s:%(lineno)d] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Root logger ayarı — tüm modüller bu formatı kullanır
_root = logging.getLogger()
_root.setLevel(logging.INFO)

# Konsol çıktısı (uvicorn/systemd journal)
_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
_root.addHandler(_console)

# Dosya çıktısı — 10 MB, 10 yedek (toplam ~100 MB)
_file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "sprenses-api.log"),
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding="utf-8",
)
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
_root.addHandler(_file_handler)

# Hata logları ayrı dosyaya da yazılsın — sadece ERROR ve üstü
_error_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "sprenses-error.log"),
    maxBytes=10 * 1024 * 1024,
    backupCount=10,
    encoding="utf-8",
)
_error_handler.setLevel(logging.ERROR)
_error_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
_root.addHandler(_error_handler)

# error_logs tablosu köprüsü — ERROR ve üstü her log kaydı "Hata Logları" UI'ında
# görünsün (LOG-001, 2026-07-25). Öncesinde yalnız global exception handler ve
# sedna_sync yazıyordu; 100+ logger.error çağrısı DB'ye hiç düşmüyordu.
from app.utils.db_log_handler import DBLogHandler  # noqa: E402

_db_log_handler = DBLogHandler()
_root.addHandler(_db_log_handler)

logger = logging.getLogger(__name__)

app = FastAPI(title="Sprenses Hotel Management API", version="1.0.0")


# --- Güvenlik header'ları middleware (saf ASGI — BaseHTTPMiddleware TaskGroup hatalarını önler) ---
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-xss-protection", b"1; mode=block"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(self), microphone=(self), geolocation=()"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    # Backend yalnızca JSON API + dosya yanıtı döner (SvelteKit HTML'i ayrı sunulur).
    # default-src/script-src belirtilmez → FastAPI /docs (Swagger, CDN script) çalışmaya
    # devam eder. Eklenen kısıtlar her zaman güvenli ve anlamlıdır: eklenti/object yok,
    # <base> ile URL kaçırma yok, çerçeveleme yok (X-Frame-Options'ı CSP ile pekiştirir).
    # Dosya sunumu (files.py) kendi DAHA SIKI CSP'sini (default-src 'none'; sandbox) set
    # eder → SVG vb. doğrudan gezinmede script çalıştıramaz (middleware mevcut header'ı ezmez).
    (b"content-security-policy",
     b"object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing_keys = {h[0].lower() for h in headers}
                for key, value in _SECURITY_HEADERS:
                    if key not in existing_keys:
                        headers.append((key, value))
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Internal-Secret"],
)

# GZip — büyük JSON liste yanıtlarını (nakit akım/cariler 2000+ kayıt) sıkıştırır (~%70 ağ kazancı).
# minimum_size: küçük yanıtları sıkıştırma (CPU israfı olmasın).
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback as tb_module
    # _skip_db_log: DBLogHandler bu kaydı atlasın — aşağıda zaten zengin request
    # bağlamıyla (method/path/user_id/ip) ErrorLog yazılıyor; çift kayıt olmasın.
    logger.error(
        "Beklenmeyen hata: %s %s — %s",
        request.method, request.url.path, exc,
        exc_info=True, extra={"_skip_db_log": True},
    )

    # Hata logunu veritabanına kaydet
    try:
        from app.database import SessionLocal
        from app.middleware.rate_limit import get_client_ip
        from app.models.error_log import ErrorLog
        db = SessionLocal()
        try:
            error_entry = ErrorLog(
                level="ERROR",
                source=type(exc).__module__ + "." + type(exc).__name__ if type(exc).__module__ else type(exc).__name__,
                message=str(exc)[:2000],
                traceback=tb_module.format_exc()[:5000],
                method=request.method,
                path=str(request.url.path)[:500],
                ip_address=get_client_ip(request),
            )
            # user_id'yi cookie'den almaya çalış
            try:
                from app.utils.security import decode_access_token
                token = request.cookies.get("access_token")
                if token:
                    payload = decode_access_token(token)
                    if payload:
                        error_entry.user_id = payload.get("sub")
            except Exception:
                pass
            db.add(error_entry)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        pass  # DB yazımı başarısızsa sessiz geç, dosya logu zaten yazıldı

    return JSONResponse(status_code=500, content={"detail": "Sunucu hatası oluştu"})

# Router kablolaması — her paket kendi alt-router etiket/öneklerini __init__'inde taşır
# (2026-09-02 yeniden yapılandırması; yol/metot/etiket kümesi tests/test_route_manifest.py ile dondurulmuştur).
app.include_router(core.router, prefix="/api")                                   # health, auth/, ws, push/, notifications/
app.include_router(system.router, prefix="/api/system")                          # users/ roles/ modules/ server backup docs/ denetim/ audit-logs/ error-logs/
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(finance.router, prefix="/api/finance", tags=["finance"])
app.include_router(accounting.router, prefix="/api/accounting", tags=["accounting"])
app.include_router(hr.router, prefix="/api/hr")                                  # salary/ withholding/ sgk/ + shifts + shift-schedule
app.include_router(attendance.router, prefix="/api", tags=["attendance"])       # /api/attendance/* — yol koruma (QR kartlar/PWA)
app.include_router(sales.router, prefix="/api/sales", tags=["sales"])
app.include_router(stock.router, prefix="/api/stok", tags=["stock"])
app.include_router(ai.router, prefix="/api/ai")
app.include_router(core.files_router)                                            # /uploads/{path} (öneksiz)
app.include_router(core.internal_router)                                         # /api/internal/* (router-düzeyi önek)
app.include_router(approval.router, prefix="/api/system/approval", tags=["approval"])

# Yükleme dizinini oluştur (dosya endpoint'i tarafından kullanılır)
_uploads_dir = UPLOADS_DIR
_uploads_dir.mkdir(exist_ok=True)
