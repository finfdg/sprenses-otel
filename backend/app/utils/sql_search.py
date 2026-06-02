"""Arama / LIKE pattern güvenlik yardımcıları.

Kullanıcı girdisini SQL LIKE/ILIKE pattern'ine güvenli şekilde gömmek için kullanılır.
LIKE operatörleri için `%`, `_`, `\\` özel karakterlerdir; escape edilmezse:
- Kullanıcı `%admin%` yazarak filtreyi anlamsız hale getirebilir (wildcard injection)
- `_` ile tek karakter wildcard tetiklenir (yanlış sonuç)
- `\\` PostgreSQL escape karakteri olduğundan SQL hatası veya beklenmedik davranış olur
- `%` ile başlayan uzun pattern'ler indeks kullanamayıp tablo taraması yapar (performans DoS)

Kullanım:
    from app.utils.sql_search import like_pattern

    q = db.query(User).filter(User.email.ilike(like_pattern(search), escape="\\"))

`like_pattern(s, max_len=200)` döner: `%{escape edilmiş s}%`.
İçeride trim + max uzunluk koruması yapılır (DoS).
"""


def escape_like(value: str) -> str:
    """LIKE/ILIKE pattern'inde özel karakterleri escape et."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_pattern(value: str, max_len: int = 200) -> str:
    """Kullanıcı arama girdisini güvenli `%...%` LIKE pattern'ine çevir.

    - Çevreleyen boşluklar atılır
    - max_len ile uzunluk sınırlanır (varsayılan 200)
    - %, _, \\ karakterleri escape edilir
    - Çağırıcıda `.ilike(like_pattern(s), escape="\\")` kullanılmalıdır
    """
    if not value:
        return "%"
    trimmed = value.strip()[:max_len]
    return f"%{escape_like(trimmed)}%"
