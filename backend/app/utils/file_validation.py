"""Dosya yükleme güvenlik doğrulaması.

Yüklenen dosyaları MIME türü ve boyut açısından kontrol eder.
Dosya uzantısı sahtekarlığını ve büyük dosya saldırılarını engeller.

Kullanım:
    from app.utils.file_validation import validate_upload_file, MAX_UPLOAD_SIZE

    # Endpoint'te:
    await validate_upload_file(file, allowed_types=["excel", "pdf"])
"""
import logging
import os
from typing import List

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

# Boyut limitleri
MAX_UPLOAD_SIZE = 20 * 1024 * 1024       # 20 MB — genel limit
MAX_EXCEL_SIZE  = 10 * 1024 * 1024       # 10 MB — Excel dosyaları
MAX_PDF_SIZE    = 25 * 1024 * 1024       # 25 MB — PDF dosyaları (banka ekstresi)

# MIME başlıkları (magic bytes)
EXCEL_MAGIC = {
    b"\x50\x4B\x03\x04",          # .xlsx (ZIP başlığı)
    b"\x50\x4B\x05\x06",          # .xlsx (boş ZIP)
    b"\xD0\xCF\x11\xE0",          # .xls (OLE2)
}

PDF_MAGIC = {b"%PDF"}              # %PDF

# İzin verilen uzantılar
ALLOWED_EXTENSIONS = {
    "excel": {".xlsx", ".xls"},
    "pdf":   {".pdf"},
}


def _check_magic_bytes(data: bytes, file_type: str) -> bool:
    """Dosyanın ilk baytları beklenen magic bytes ile eşleşiyor mu?"""
    if file_type == "excel":
        return any(data.startswith(magic) for magic in EXCEL_MAGIC)
    if file_type == "pdf":
        return any(data.startswith(magic) for magic in PDF_MAGIC)
    return True  # Bilinmeyen tip — sadece uzantı kontrolü


def _get_file_type(filename: str) -> str:
    """Uzantıdan dosya tipini belirle."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in (".xlsx", ".xls"):
        return "excel"
    if ext == ".pdf":
        return "pdf"
    return "unknown"


async def validate_upload_file(
    file: UploadFile,
    allowed_types: List[str],
    max_size: int = MAX_UPLOAD_SIZE,
) -> bytes:
    """Yüklenen dosyayı doğrula ve içeriğini döndür.

    Args:
        file: FastAPI UploadFile nesnesi
        allowed_types: İzin verilen tipler, ör. ["excel", "pdf"]
        max_size: Maksimum dosya boyutu (byte)

    Returns:
        Dosya içeriği (bytes)

    Raises:
        HTTPException 400: Geçersiz dosya tipi, boyut aşımı veya içerik uyuşmazlığı
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    file_type = _get_file_type(filename)

    # Uzantı kontrolü
    allowed_exts = set()
    for t in allowed_types:
        allowed_exts |= ALLOWED_EXTENSIONS.get(t, set())

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"İzin verilmeyen dosya türü: {ext}. Kabul edilenler: {', '.join(sorted(allowed_exts))}",
        )

    # Boyuta göre limit belirle
    if file_type == "excel":
        size_limit = min(max_size, MAX_EXCEL_SIZE)
    elif file_type == "pdf":
        size_limit = min(max_size, MAX_PDF_SIZE)
    else:
        size_limit = max_size

    # İçeriği oku (boyut kontrolü dahil)
    content = await file.read()
    await file.seek(0)  # Pointer'ı başa al — çağıran tekrar okuyabilsin

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Dosya boş")

    if len(content) > size_limit:
        limit_mb = size_limit / (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"Dosya boyutu sınırı aşıldı ({limit_mb:.0f} MB). "
                   f"Yüklenen: {len(content) / (1024*1024):.1f} MB",
        )

    # MIME doğrulaması (magic bytes)
    if file_type in ("excel", "pdf"):
        if not _check_magic_bytes(content, file_type):
            logger.warning(
                "Sahte dosya yükleme girişimi: filename=%s, ilk_4_byte=%s",
                filename, content[:4].hex(),
            )
            raise HTTPException(
                status_code=400,
                detail="Dosya içeriği uzantısıyla uyuşmuyor. Gerçek bir dosya yükleyin.",
            )

    return content
