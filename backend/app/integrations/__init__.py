"""Dış sistem istemcileri — Sedna (SQL Server), banka API'leri, TCMB, SMTP, Amadeus.

Kural: bu paket `app.services` / `app.routers` import ETMEZ (yalnız `app.config`, `app.parsers`,
`app.models` okuma). Domain mantığı servislerdedir; buradaki modüller yalnız veri getirir/gönderir.
Testler bu modüllerin `fetch_*`/HTTP fonksiyonlarını modül niteliği üzerinden monkeypatch'ler →
servisler bu fonksiyonları modül düzeyinde adla import eder (`from app.integrations.sedna_client import fetch_x`).
2026-09-02 yeniden yapılandırmasında `app/utils/` altından buraya taşındı.
"""
