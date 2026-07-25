"""Doküman izin-kodu drift regresyon testi — DOC-D05 (v4 denetim, Boyut 13).

Bulgu: `docs/modules/finans-mimarisi.md` modül tablosundaki izin kodları
gerçekle örtüşmüyordu — `finance.advances` ve `finance.exchange_rates`
yazıyordu; oysa modules tablosundaki gerçek kodlar `finance.avanslar` ve
`finance.doviz`. Bu test, dokümanın modül tablosunda listelenen HER izin
kodunun modules tablosunda fiilen mevcut olmasını zorunlu kılar.

Kapanış kriteri: Dokümandaki tüm izin kodları modules tablosunda mevcut.
"""

import os
import re

from app.models.module import Module

# backend/tests/ -> proje kökü (iki üst) -> docs/modules/finans-mimarisi.md
FINANS_MIMARISI_MD = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "docs",
        "modules",
        "finans-mimarisi.md",
    )
)


def _module_table_codes():
    """finans-mimarisi.md 'Genel Bakış' modül tablosundaki izin kodlarını döndürür.

    Tablo satırları: `| <Ad> | \\`<kod>\\` | <Açıklama> |`
    Yalnızca 'namespace.name' biçimindeki backtick kodları toplanır.
    """
    text = open(FINANS_MIMARISI_MD, encoding="utf-8").read()
    codes = []
    for line in text.splitlines():
        # Modül tablosu satırı: üç boru arası, ortada backtick içinde kod
        m = re.match(
            r"^\|\s*[^|]+\|\s*`([a-z_]+\.[a-z_]+)`\s*\|", line
        )
        if m:
            codes.append(m.group(1))
    return codes


def test_module_table_has_codes():
    """Doküman modül tablosu ayrıştırılabilmeli (regex sessizce boş dönmesin)."""
    codes = _module_table_codes()
    assert len(codes) >= 5, (
        "finans-mimarisi.md modül tablosundan izin kodu çıkarılamadı; "
        "tablo biçimi değişmiş olabilir: " + repr(codes)
    )


def test_all_doc_permission_codes_exist_in_modules(db):
    """Dokümandaki tüm izin kodları modules tablosunda mevcut olmalı (DOC-D05).

    Düzeltme geri alınırsa (`finance.advances` / `finance.exchange_rates`
    geri gelirse) bu test kırmızıya döner.
    """
    doc_codes = _module_table_codes()
    existing = {
        c for (c,) in db.query(Module.code)
        .filter(Module.code.in_(doc_codes))
        .all()
    }
    missing = sorted(set(doc_codes) - existing)
    assert not missing, (
        "finans-mimarisi.md'deki şu izin kodları modules tablosunda YOK "
        "(doküman drift'i): " + ", ".join(missing)
    )
