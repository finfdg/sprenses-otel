"""Acente/cari adı token eşleştirme — ASCII fold + büyük harf + ayırt edici token kümesi.

D1-1 (2026-06-22): `_norm_tokens` eskiden `routers/finance/advances.py` içindeydi ve
`sales_invoices.py` oradan import ediyordu (router→router). Saf string yardımcısı →
utils'e taşındı; `advances` + `sales_invoice_service` buradan alır.
"""
import re



# Acente adı eşleştirme — ayırt edici olmayan kelimeler atılır (token çakışmasını azaltır)
_STOP_TOKENS = {
    "TUR", "TURIZM", "TIC", "TICARET", "LTD", "STI", "SAN", "VE", "AS", "ANONIM", "SIRKETI",
    "ONLINE", "GMBH", "SLU", "SL", "OTEL", "OTELCILIK", "INS", "INSAAT", "ITH", "IHR",
}


def _norm_tokens(s: str) -> set:
    """Acente adını ASCII'ye fold + büyük harf + ayırt edici token kümesi."""
    s = s or ""
    for a, b in (("İ", "I"), ("ı", "i"), ("Ş", "S"), ("ş", "s"), ("Ğ", "G"), ("ğ", "g"),
                 ("Ü", "U"), ("ü", "u"), ("Ö", "O"), ("ö", "o"), ("Ç", "C"), ("ç", "c")):
        s = s.replace(a, b)
    s = s.upper()
    return {t for t in re.split(r"[^A-Z0-9]+", s) if len(t) >= 2 and t not in _STOP_TOKENS}
