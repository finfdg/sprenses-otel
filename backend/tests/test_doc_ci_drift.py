"""Doküman drift regresyon testi — DOC-D01 (v4 denetim, Boyut 13).

Bulgu: CLAUDE.md 'Sürüm Kontrolü ve CI' bölümü, CI'nin her push/PR'da fiilen
çalıştığını iddia ediyordu; oysa deponun GitHub Actions'ı KAPALI (0 koşu).
Bu test, ifade gerçekle örtüşene kadar (Actions açılana kadar) CI bölümünün
'kapalı / etkin değil' uyarısını taşımasını zorunlu kılar. Actions açıldığında
CLAUDE.md 'her push/PR'da çalışır' olarak güncellenir ve bu test, uyarıyı
şart koşan dalı bırakır (aşağıdaki not).
"""

import os
import re

# backend/tests/ -> proje kökü (iki üst)
CLAUDE_MD = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "CLAUDE.md")
)


def _ci_bullet() -> str:
    """CLAUDE.md içindeki '- **CI...**' madde imini döndürür."""
    text = open(CLAUDE_MD, encoding="utf-8").read()
    # '### Sürüm Kontrolü ve CI' bölümündeki CI madde imi
    m = re.search(r"^- \*\*CI[^\n]*\*\*[^\n]*", text, re.MULTILINE)
    assert m, "CLAUDE.md içinde '- **CI...**' madde imi bulunamadı"
    return m.group(0)


def test_ci_claim_notes_actions_disabled():
    """CI fiilen çalışmıyorsa (Actions kapalı) ifade bunu açıkça belirtmeli.

    Bu, DOC-D01 drift'inin regresyonunu yakalar: eski metin
    'her push/PR'da ... çalıştırır' diyordu ama Actions kapalıydı.
    """
    bullet = _ci_bullet().lower()
    disabled_markers = ("etkin değil", "kapalı", "fiilen çalışmıyor", "0 koşu")
    assert any(mk in bullet for mk in disabled_markers), (
        "CLAUDE.md CI ifadesi, Actions kapalıyken CI'nin çalışmadığını "
        "belirtmiyor (DOC-D01 drift geri döndü):\n" + _ci_bullet()
    )


def test_ci_claim_has_no_bare_active_assertion():
    """Kapalı uyarısı olmadan çıplak 'çalıştırır' iddiası bulunmamalı.

    Uyarı ('etkin değil' vb.) varken 'çalıştıracak şekilde' gibi gelecek/koşullu
    ifade serbesttir; yasak olan, uyarısız present-tense 'çalıştırır'dır.
    """
    bullet = _ci_bullet()
    has_disabled_note = any(
        mk in bullet.lower()
        for mk in ("etkin değil", "kapalı", "fiilen çalışmıyor", "0 koşu")
    )
    # 'çalıştırır' (present, iddia) VE uyarı yoksa → drift
    bare_active = re.search(r"push/PR'da[^\n]*çalıştırır", bullet)
    assert not (bare_active and not has_disabled_note), (
        "CLAUDE.md, Actions kapalı uyarısı olmadan CI'nin her push/PR'da "
        "çalıştığını iddia ediyor (DOC-D01):\n" + bullet
    )
