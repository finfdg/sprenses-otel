"""Dosya sunma endpoint'i — auth kontrolü ile."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import user_can
from app.models.conversation import ConversationMember
from app.models.message import Message
from app.models.user import User
from app.paths import UPLOADS_DIR
from app.utils.security import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter()

# Yükleme dizini — file_upload.py ile aynı konum
_uploads_dir = UPLOADS_DIR

# Dizin öneki → modül eşlemesi. serve_file yalnız kimlik değil, dosyanın ait olduğu
# modülün görüntüleme iznini de arar (IDOR koruması). Buraya eklenmemiş önekler
# deny-by-default reddedilir; yeni bir modül dosya sunmaya başlarsa buraya eklenir.
_PREFIX_MODULE = {
    "cc_statements": "finance.krediler",
}

# MIME type eşlemesi
_EXT_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".3gp": "video/3gpp",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
}

# Cookie adı — auth middleware ile aynı
COOKIE_NAME = "access_token"


def _authenticate_from_request(request: Request) -> Optional[int]:
    """
    Request'ten kullanıcı kimliğini doğrula.
    Sırasıyla: Authorization header → Cookie
    """
    token: Optional[str] = None

    # 1. Bearer header
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # 2. Cookie
    if not token:
        token = request.cookies.get(COOKIE_NAME)

    if not token:
        return None

    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if sub is None:
            return None
        user_id = int(sub)
        session_id = payload.get("session_id")
        return user_id, session_id
    except (JWTError, ValueError):
        return None


def _authorize_file_access(db: Session, user: User, file_path: str) -> bool:
    """Dosyanın ait olduğu modülün görüntüleme iznini ve kaynak sahipliğini doğrula.

    Kimlik doğrulaması yeterli değildir (IDOR): dosya hangi modüle aitse o modülün
    view izni aranır. Mesaj ekleri için ayrıca konuşma üyeliği (kaynak sahipliği)
    kontrol edilir. Tanınmayan dizin öneki deny-by-default reddedilir → yol tahminiyle
    başka modülün dosyasına erişim kapatılır.
    """
    parts = Path(file_path).parts
    if not parts:
        return False
    prefix = parts[0]

    # Bilinen modül dizinleri (ör. cc_statements → finance.krediler)
    module_code = _PREFIX_MODULE.get(prefix)
    if module_code is not None:
        return user_can(db, user, module_code, "view")

    # Mesaj ekleri: /uploads/YYYY/MM/uuid.ext → messaging modülü + konuşma üyeliği
    if prefix.isdigit() and len(prefix) == 4:
        if not user_can(db, user, "messaging", "view"):
            return False
        file_url = "/uploads/" + file_path
        member = (
            db.query(ConversationMember.id)
            .join(Message, Message.conversation_id == ConversationMember.conversation_id)
            .filter(
                Message.file_url == file_url,
                ConversationMember.user_id == user.id,
            )
            .first()
        )
        return member is not None

    # Tanınmayan önek → deny-by-default
    return False


@router.get("/uploads/{file_path:path}")
def serve_file(file_path: str, request: Request, db: Session = Depends(get_db)):
    """
    Dosya sunma endpoint'i. Kimlik doğrulama gerektirir.
    Tarayıcılar <img> ve <video> tag'ları için cookie gönderir,
    API çağrıları Bearer header kullanır.
    """
    # Auth kontrolü
    auth_result = _authenticate_from_request(request)
    if auth_result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dosya erişimi için kimlik doğrulama gerekli",
        )

    user_id, session_id = auth_result

    # Kullanıcının aktif olduğunu ve oturumunun geçerli olduğunu doğrula
    user = db.query(User).filter(
        User.id == user_id, User.is_active == True
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı bulunamadı",
        )
    # Tek oturum kontrolü: çıkış yapmış veya başka cihazdan giriş yapılmış olabilir
    if user.active_session_id is None or session_id != user.active_session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturumunuz sonlandırılmış",
        )

    # Yetkilendirme: kimlik yeterli değil — dosyanın modül izni + kaynak sahipliği (IDOR)
    if not _authorize_file_access(db, user, file_path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu dosyaya erişim yetkiniz yok",
        )

    # Path traversal koruması
    try:
        resolved = (_uploads_dir / file_path).resolve()
        if not str(resolved).startswith(str(_uploads_dir.resolve())):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Erişim reddedildi")
    except (ValueError, OSError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz dosya yolu")

    if not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dosya bulunamadı")

    # MIME type belirle
    ext = resolved.suffix.lower()
    media_type = _EXT_MIME.get(ext, "application/octet-stream")

    # Cache header — UUID dosya adları sayesinde agresif cache güvenli
    response_headers = {
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }

    # SVG (ve diğer "aktif" içerik) doğrudan gezinmede (top-level document) script
    # çalıştırabilir → stored XSS riski. İki katmanlı savunma:
    #  1) Content-Disposition: attachment → tarayıcı inline render etmek yerine indirir
    #     (<img src> ile gösterim ETKİLENMEZ; SVG'ler logolarda görünmeye devam eder).
    #  2) Sıkı CSP → render edilse bile script/dış kaynak yüklenemez.
    # Global middleware CSP'si mevcut header'ı ezmez; burada set edilen daha sıkıdır.
    if ext == ".svg" or media_type in ("image/svg+xml", "text/html"):
        response_headers["Content-Disposition"] = f'attachment; filename="{resolved.name}"'
        response_headers["Content-Security-Policy"] = "default-src 'none'; sandbox"

    return FileResponse(
        path=str(resolved),
        media_type=media_type,
        headers=response_headers,
    )
