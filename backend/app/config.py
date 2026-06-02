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
    internal_secret: str
    # Travelpayouts (uçak rezervasyon — opsiyonel)
    travelpayouts_token: str = ""
    travelpayouts_marker: str = ""

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
