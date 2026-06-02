"""Dosya sunma endpoint'i — auth kontrolü ile."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from jose import JWTError

from app.database import SessionLocal
from app.models.user import User
from app.utils.security import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter()

# Yükleme dizini — file_upload.py ile aynı konum
_uploads_dir = Path(__file__).resolve().parent.parent.parent / "uploads"

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


@router.get("/uploads/{file_path:path}")
def serve_file(file_path: str, request: Request):
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
    db = SessionLocal()
    try:
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
    finally:
        db.close()

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
    return FileResponse(
        path=str(resolved),
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )
