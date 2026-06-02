"""Dosya yükleme yardımcısı — mesajlarda dosya/görsel paylaşımı için."""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Set

import pytz
from fastapi import HTTPException, UploadFile

from app.config import settings

_tz = pytz.timezone(settings.timezone)

# Yükleme dizini — proje kökünden göreceli
UPLOAD_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))).joinpath("uploads")

# Maksimum dosya boyutu: 20 MB
MAX_FILE_SIZE = 20 * 1024 * 1024

# İzin verilen MIME type'lar (SVG çıkarıldı — XSS riski)
ALLOWED_MIME_TYPES: Set[str] = {
    # Görseller
    "image/jpeg", "image/png", "image/gif", "image/webp",
    # Video
    "video/mp4", "video/webm", "video/quicktime", "video/3gpp",
    # Belgeler
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Metin
    "text/plain", "text/csv",
}

# MIME type → message_type eşlemesi
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/3gpp"}

# Dosya imzaları (magic bytes) — MIME type doğrulaması için
MAGIC_BYTES: Dict[str, list] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF....WEBP — 4. bayttan sonra WEBP kontrolü ayrıca yapılır
    "video/mp4": [b"\x00\x00\x00\x18ftyp", b"\x00\x00\x00\x1cftyp", b"\x00\x00\x00\x20ftyp", b"ftyp"],
    "video/quicktime": [b"\x00\x00\x00\x14ftypqt", b"\x00\x00\x00\x18ftyp", b"\x00\x00\x00\x1cftyp", b"\x00\x00\x00\x20ftyp", b"ftyp"],
    "video/3gpp": [b"\x00\x00\x00\x18ftyp3gp", b"\x00\x00\x00\x1cftyp3gp", b"\x00\x00\x00\x20ftyp", b"ftyp"],
    "video/webm": [b"\x1a\x45\xdf\xa3"],
    "application/pdf": [b"%PDF"],
    "application/msword": [b"\xd0\xcf\x11\xe0"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [b"PK\x03\x04"],
    "application/vnd.ms-excel": [b"\xd0\xcf\x11\xe0"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [b"PK\x03\x04"],
}

# Magic bytes gerektirmeyen türler (metin dosyaları — imza yok)
NO_MAGIC_CHECK_TYPES: Set[str] = {"text/plain", "text/csv"}


def _verify_magic_bytes(contents: bytes, claimed_mime: str) -> bool:
    """Dosya içeriğinin magic bytes'ını kontrol ederek MIME type'ı doğrula."""
    if claimed_mime in NO_MAGIC_CHECK_TYPES:
        return True

    signatures = MAGIC_BYTES.get(claimed_mime)
    if signatures is None:
        return False

    for sig in signatures:
        if contents[:len(sig)] == sig:
            # WebP ek kontrolü: RIFF başlıyor ama WEBP olmalı
            if claimed_mime == "image/webp":
                return len(contents) >= 12 and contents[8:12] == b"WEBP"
            return True

    # mp4/quicktime/3gpp için offset'li ftyp kontrolü (bazı videolar farklı offset'te başlar)
    if claimed_mime in ("video/mp4", "video/quicktime", "video/3gpp") and b"ftyp" in contents[:32]:
        return True

    return False


def get_message_type_for_mime(mime_type: str) -> str:
    """MIME type'a göre mesaj tipini belirle."""
    if mime_type in IMAGE_TYPES:
        return "image"
    if mime_type in VIDEO_TYPES:
        return "video"
    return "file"


async def save_upload(file: UploadFile) -> Dict[str, object]:
    """
    Yüklenen dosyayı diske kaydet.

    Dönen dict:
        file_url: str   — /uploads/2026/02/uuid.ext şeklinde URL
        file_name: str  — orijinal dosya adı
        file_size: int  — bayt cinsinden boyut
        file_type: str  — MIME type
        message_type: str — "image" | "video" | "file"
    """
    # MIME type kontrolü
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Bu dosya türü desteklenmiyor. Desteklenen türler: resim, video, PDF, Word, Excel, metin"
        )

    # Dosya içeriğini oku
    contents = await file.read()
    file_size = len(contents)

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Boş dosya yüklenemez")

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Dosya boyutu {MAX_FILE_SIZE // (1024 * 1024)} MB'den büyük olamaz"
        )

    # Magic bytes doğrulaması — client'ın MIME type'ına güvenme
    if not _verify_magic_bytes(contents, content_type):
        raise HTTPException(
            status_code=400,
            detail="Dosya içeriği belirtilen türle eşleşmiyor. Lütfen geçerli bir dosya yükleyin"
        )

    # UUID tabanlı dosya adı
    now = datetime.now(_tz)
    year_month = now.strftime("%Y/%m")
    raw_name = file.filename or "dosya"
    # Path traversal koruması: sadece dosya adını al, dizin yollarını çıkar
    original_name = Path(raw_name).name.replace("\x00", "")
    if not original_name:
        original_name = "dosya"
    ext = Path(original_name).suffix.lower() or _mime_to_ext(content_type)

    # Uzantı whitelist kontrolü — beklenmeyen uzantıları engelle
    allowed_extensions = {
        ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".mp4", ".webm", ".mov", ".3gp",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".txt", ".csv",
    }
    if ext not in allowed_extensions:
        ext = _mime_to_ext(content_type)

    unique_name = f"{uuid.uuid4().hex}{ext}"

    # Dizin oluştur
    target_dir = UPLOAD_DIR / year_month
    target_dir.mkdir(parents=True, exist_ok=True)

    # Dosyayı kaydet
    target_path = target_dir / unique_name
    with open(target_path, "wb") as f:
        f.write(contents)

    file_url = f"/uploads/{year_month}/{unique_name}"

    return {
        "file_url": file_url,
        "file_name": original_name,
        "file_size": file_size,
        "file_type": content_type,
        "message_type": get_message_type_for_mime(content_type),
    }


def _mime_to_ext(mime_type: str) -> str:
    """MIME type'dan dosya uzantısı tahmin et."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/3gpp": ".3gp",
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/plain": ".txt",
        "text/csv": ".csv",
    }
    return mapping.get(mime_type, ".bin")
