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
    # Yapay Zeka Asistanı (Anthropic Claude API) — ANTHROPIC_API_KEY boşsa asistan
    # devre dışıdır (SEDNA_PASSWORD/SMTP_PASSWORD deseni gibi). Model varsayılanı
    # claude-opus-4-8; tool-use ile salt-okuma finans sorgularını yanıtlar.
    anthropic_api_key: str = ""             # .env: ANTHROPIC_API_KEY
    anthropic_model: str = "claude-opus-4-8"
    # VakıfBank Açık Bankacılık API (banka hesap hareketleri doğrudan çekme — opsiyonel).
    # VAKIFBANK_API_SECRET boşsa özellik devre dışıdır (SEDNA_PASSWORD deseni gibi).
    # Kimlik bilgileri YALNIZCA .env'den okunur — kodda gerçek değer default OLARAK verilmez.
    # Gateway + endpoint'ler bankanın resmî Postman collection'ıyla DOĞRULANDI (2026-07-10,
    # Apiportaldestek e-postası "Rıza Numarası hk." — "Genel Test Dosyası - Hesap Bilgi"):
    # token=/auth/oauth/v2/token, /accountList, /accountDetail, /accountTransactions.
    vakifbank_base_url: str = "https://apigw.vakifbank.com.tr:8443"
    vakifbank_token_path: str = "/auth/oauth/v2/token"
    vakifbank_transactions_path: str = "/accountTransactions"
    vakifbank_account_list_path: str = "/accountList"  # hesap listesi (sandbox keşfi + teşhis)
    vakifbank_grant_type: str = "b2b_credentials"  # hesap servisleri B2B (client_credentials DEĞİL)
    vakifbank_resource: str = "sandbox"            # ortam: sandbox | production
    vakifbank_client_id: str = ""           # .env: VAKIFBANK_CLIENT_ID (= API Key)
    vakifbank_api_secret: str = ""          # .env: VAKIFBANK_API_SECRET (boşsa özellik kapalı; 5 hatada portal kilitlenir!)
    vakifbank_riza_no: str = ""             # .env: VAKIFBANK_RIZA_NO (consentId — Rıza; bankadan gelir)
    vakifbank_scope: str = "account"        # B2B kapsam (dokümanda "account")
    vakifbank_sync_lookback_days: int = 30  # her senkronda geriye kaç gün çekilsin (dedup çakışmayı önler)

    # Yapı Kredi API Portal (Account Transaction List — banka hesap hareketleri, opsiyonel).
    # YKB_CLIENT_SECRET boşsa özellik devre dışıdır (SEDNA_PASSWORD/VAKIFBANK deseni gibi).
    # Kimlik bilgileri YALNIZCA .env'den okunur — kodda gerçek değer default OLARAK verilmez.
    # OAuth2 client_credentials → token_url; hareketler POST /accountTransactionList.
    ykb_token_url: str = "https://api.yapikredi.com.tr/auth/oauth/v2/token"  # portal Authorization
    ykb_client_id: str = ""       # .env: YKB_CLIENT_ID (uygulama Client ID)
    ykb_client_secret: str = ""   # .env: YKB_CLIENT_SECRET (boşsa özellik kapalı)
    ykb_scope: str = "oob"        # OAuth2 scope (portala göre ayarlanır)
    ykb_lookback_days: int = 7    # her senkronda geriye kaç gün çekilsin (dedup çakışmayı önler)

    # QNB Açık Bankacılık — Account Statement V2 (hesap hareketleri, opsiyonel).
    # ⚠️ grant_type=refresh_token ROTATING: her token çağrısı YENİ refresh_token döndürür →
    # `.qnb_refresh_token` dosyasına kalıcı yazılır (eskisi geçersizleşir). İLK refresh_token
    # e-posta ile gelir (QNB_REFRESH_TOKEN tohumu). QNB_CLIENT_SECRET/REFRESH_TOKEN boşsa kapalı.
    qnb_token_url: str = "https://sandbox-api.qnb.com.tr/token"
    qnb_base_url: str = "https://sandbox-api.qnb.com.tr/v0/account-statement"
    qnb_client_id: str = ""       # .env: QNB_CLIENT_ID
    qnb_client_secret: str = ""   # .env: QNB_CLIENT_SECRET (boşsa kapalı)
    qnb_refresh_token: str = ""   # .env: QNB_REFRESH_TOKEN (e-posta ile gelen İLK token; sonra dosyada döner)
    qnb_grant_type: str = "refresh_token"
    qnb_lookback_days: int = 7    # doğrudan GET 1-günlük → lookback gün-gün döngüyle çekilir

    # Garanti BBVA — Account Transactions (Electronic Bank Statement, opsiyonel).
    # OAuth2 client_credentials; ⚠️ access token TEK KULLANIMLIK (her istek için yeni token, cache YOK).
    # consentId ZORUNLU (enrollment sonrası alınır; VakıfBank Rıza gibi). Max 30 gün aralık.
    # GARANTI_CLIENT_SECRET/CONSENT_ID boşsa özellik kapalı. Token URL doküman ile teyit edilmeli.
    garanti_base_url: str = "https://apis.garantibbva.com.tr:443"
    garanti_token_url: str = "https://apis.garantibbva.com.tr/auth/oauth/v2/token"  # TODO: doküman ile teyit
    garanti_transactions_path: str = "/balancesandmovements/accountinformation/transaction/v1/gettransactions"
    garanti_client_id: str = ""       # .env: GARANTI_CLIENT_ID
    garanti_client_secret: str = ""   # .env: GARANTI_CLIENT_SECRET (boşsa kapalı)
    garanti_consent_id: str = ""      # .env: GARANTI_CONSENT_ID (enrollment sonrası; zorunlu)
    garanti_scope: str = ""           # opsiyonel OAuth2 scope (portala göre)
    garanti_lookback_days: int = 30   # banka limiti max 30 gün

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
