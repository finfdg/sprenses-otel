"""E-posta (SMTP) gönderme yardımcıları.

Giden bildirim e-postaları TurkTicaret.net kurumsal SMTP sunucusu (smtp.turkticaret.net)
üzerinden gönderilir. Kimlik bilgileri `.env`'den okunur; `SMTP_PASSWORD` boşsa özellik
tamamen kapalıdır (SEDNA_PASSWORD deseni gibi) — uygulamanın normal işleyişi buna bağlı
DEĞİLDİR.

Gönderim BLOKLAYAN I/O'dur (SMTP el sıkışması saniyeler sürebilir). İstek/endpoint
içinde doğrudan çağırma — arka plan thread'inde çalıştır (bkz. utils/notification.py
`_send_email_background`).
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# HTML alternatifini görüntüleyemeyen istemciler için düz-metin yedeği
_PLAIN_FALLBACK = "Bu e-postayı görüntülemek için HTML destekli bir e-posta istemcisi kullanın."


def is_mail_enabled() -> bool:
    """SMTP yapılandırması tam mı? (host + user + password gerekli)."""
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
) -> bool:
    """Tek bir alıcıya e-posta gönder. Başarılıysa True, aksi halde False döner.

    BLOKLAYAN I/O — endpoint/istek içinde doğrudan çağırma; arka plan thread'i kullan.
    SMTP yapılandırılmamışsa (şifre boş) sessizce False döner.
    """
    if not is_mail_enabled():
        logger.debug("SMTP yapılandırılmadı — e-posta gönderilmedi (to=%s)", to)
        return False

    msg = EmailMessage()
    msg["From"] = formataddr((settings.smtp_from_name or "Sprenses Otel", settings.smtp_user))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_text or _PLAIN_FALLBACK)
    msg.add_alternative(body_html, subtype="html")

    try:
        context = ssl.create_default_context()
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, context=context, timeout=20
            ) as server:
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                server.starttls(context=context)
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        logger.info("E-posta gönderildi: to=%s subject=%s", to, subject)
        return True
    except Exception as e:
        logger.error("E-posta gönderilemedi (to=%s): %s", to, e)
        return False
