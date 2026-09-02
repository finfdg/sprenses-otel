"""Dosya/ekstre ayrıştırıcıları — banka PDF/Excel, kredi kartı ekstresi, çek, rezervasyon, cari raporu.

Saf fonksiyonlar: DB ve servis import'u YOK; yalnız `app.config`/`app.paths`. Aynı dizin derinliği
korunmalı (`bank_parser.TESSDATA_DIR` artık `app.paths`'ten gelir, derinlik bağımsız).
2026-09-02 yeniden yapılandırmasında `app/utils/` altından buraya taşındı.
"""
