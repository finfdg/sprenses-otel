"""Sayfalama yardımcıları — liste endpoint'lerinde tekrar eden offset/count/meta mantığı.

CLAUDE.md Pagination kuralı: yanıt `{items, total, page, page_size, pages}`.
Baskın konvansiyon: boş sonuçta `pages = 1` (kullanıcı 1. sayfada kalır).

Not: `approval/` endpoint'leri boşta `pages = 0` döndürdüğünden bu helper'a GEÇİRİLMEZ
(davranış sapması olmaması için) — onlar kendi hesabını tutar.
"""
import math
from typing import Any, Callable, List, Optional

from sqlalchemy.orm import Query


def page_meta(items: List[Any], total: int, page: int, page_size: int) -> dict:
    """Önceden oluşturulmuş item listesinden standart sayfalama yanıtı kurar."""
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
    }


def paginate(
    query: Query,
    page: int,
    page_size: int,
    serializer: Optional[Callable[[Any], Any]] = None,
) -> dict:
    """Query'yi sayfalar: count + offset/limit + standart meta.

    serializer verilirse her satır ona geçirilir (response builder); yoksa ham ORM
    nesneleri döner. Dönüş: `{items, total, page, page_size, pages}`.
    """
    offset = (page - 1) * page_size
    total = query.count()
    rows = query.offset(offset).limit(page_size).all()
    items = [serializer(r) for r in rows] if serializer else rows
    return page_meta(items, total, page, page_size)
