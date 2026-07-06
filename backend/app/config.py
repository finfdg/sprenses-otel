import os
import warnings

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    timezone: str = "Europe/Istanbul"
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_mailto: str = "mailto:admin@sprenses.com"
    cors_origins: str = "https://sprenses.com"
    public_base_url: str = "https://sprenses.com"  # e-posta bağlantılarında kullanılır
    internal_secret: str
    # Sedna SQL Server (cari içe aktarma — ters SSH tüneli üzerinden, opsiyonel)
    # Bağlantı yalnızca "Sedna'dan İçe Aktar" tetiklenince kurulur; uygulamanın
    # normal işleyişi bu bağlantıya bağlı DEĞİLDİR (tünel kapalıysa import hata verir).
    sedna_host: str = "127.0.0.1"
    sedna_port: int = 11433
    sedna_database: str = "SednaPrensesMhs2026"
    sedna_pms_database: str = "SednaPrenses"  # önbüro/PMS DB (rezervasyon/doluluk)
    sedna_user: str = "prenses\\btadmin"   # domain hesabı → pymssql/FreeTDS NTLM
    sedna_password: str = ""               # .env: SEDNA_PASSWORD (boşsa import devre dışı)
    sedna_charset: str = "CP1254"          # Türkçe collation (İ/Ş/ğ doğru okunsun)
    sedna_account_prefix: str = "320"      # içe aktarılacak cari grubu (satıcılar)
    # SMTP (giden e-posta bildirimleri — opsiyonel, TurkTicaret.net kurumsal e-posta)
    # SMTP_PASSWORD boşsa e-posta gönderimi devre dışıdır (SEDNA_PASSWORD deseni gibi).
    # Port 465 → SSL (smtp_use_ssl=True) · Port 587 → STARTTLS (smtp_use_ssl=False)
    smtp_host: str = "smtp.turkticaret.net"
    smtp_port: int = 465
    smtp_use_ssl: bool = True               # 465=SSL(True), 587=STARTTLS(False)
    smtp_user: str = "bilgi@sprenses.com"   # tam e-posta adresi (kimlik doğrulama)
    smtp_password: str = ""                 # .env: SMTP_PASSWORD (boşsa gönderim kapalı)
    smtp_from_name: str = "Sprenses Otel"   # gönderen görünen adı

    class Config:
        env_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
        )
        extra = "ignore"  # .env'de fazladan alan olursa pydantic'i durdurma


settings = Settings()

# Production'da güvenli olmayan secret key kullanılmasını engelle
_UNSAFE_KEYS = {"change-me-in-production", "secret", "test", "",
                "sprenses-hotel-jwt-secret-key-change-in-prod"}
if settings.secret_key in _UNSAFE_KEYS or len(settings.secret_key) < 32:
    warnings.warn(
        "SECRET_KEY güvenli değil! .env dosyasında en az 32 karakterlik güçlü bir anahtar belirleyin.",
        stacklevel=2,
    )
