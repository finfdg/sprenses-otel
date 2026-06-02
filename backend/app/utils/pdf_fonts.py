"""PDF için Türkçe + para birimi sembolü destekli font kaydı.

reportlab'ın varsayılan Bitstream Vera fontu Türk Lirası sembolünü (₺, U+20BA —
Unicode'a 2012'de eklendi) İÇERMEZ; bu yüzden ₺ içeren PDF tutarları kutu (□)
olarak görünür. DejaVu Sans (Vera'nın güncel çatalı; Latin metrikleri Vera ile
aynı olduğundan tablo düzeni değişmez) ₺ dahil tüm para birimi sembollerini
(€ £ $) içerir ve sistemde kuruludur. Bu yüzden DejaVu birincil tercihtir;
bulunamazsa Vera'ya, o da olmazsa Helvetica'ya düşülür.

Kullanım:
    from app.utils.pdf_fonts import register_turkish_fonts
    base_font, bold_font = register_turkish_fonts()
"""
import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Sistemde kurulu DejaVu Sans (₺ destekli) — Amazon Linux: dejavu-sans-fonts paketi
_DEJAVU_REGULAR = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"
_DEJAVU_BOLD = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"

_cached = None


def register_turkish_fonts():
    """PDF tabloları için (base_font, bold_font) font adlarını döner.

    Tercih sırası: DejaVuSans (₺ destekli) → Vera (₺ yok) → Helvetica.
    Sonuç süreç boyunca önbelleğe alınır — TTF dosyaları her PDF isteğinde
    yeniden okunmaz.
    """
    global _cached
    if _cached is not None:
        return _cached

    # 1) DejaVu Sans — Türk Lirası dahil tüm sembolleri içerir
    try:
        if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans", _DEJAVU_REGULAR))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", _DEJAVU_BOLD))
        _cached = ("DejaVuSans", "DejaVuSans-Bold")
        return _cached
    except Exception:
        pass

    # 2) Vera (reportlab paketi) — Türkçe harfler var ama ₺ YOK
    try:
        import reportlab

        font_dir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
        if "Vera" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("Vera", os.path.join(font_dir, "Vera.ttf")))
            pdfmetrics.registerFont(TTFont("VeraBd", os.path.join(font_dir, "VeraBd.ttf")))
        _cached = ("Vera", "VeraBd")
        return _cached
    except Exception:
        _cached = ("Helvetica", "Helvetica-Bold")
        return _cached
