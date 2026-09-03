# Sprenses Otel Yönetim Sistemi

Otel finans/muhasebe/İK/satış yönetim uygulaması — **FastAPI + SQLAlchemy** (Python 3.9) backend,
**SvelteKit 2 + Svelte 5 + Tailwind 4** frontend, PostgreSQL 15. Canlı: `sprenses.com`.

| Nereye bakmalı | |
|---|---|
| Kural kitabı (her Claude Code oturumu yükler) | [`CLAUDE.md`](CLAUDE.md) |
| Proje ağacı + katman kuralları | [`docs/proje-yapisi.md`](docs/proje-yapisi.md) |
| Modül dokümanları | [`docs/modules/README.md`](docs/modules/README.md) |
| Endpoint kataloğu | [`docs/api-haritasi.md`](docs/api-haritasi.md) |
| Test sistemi | [`docs/test-sistemi.md`](docs/test-sistemi.md) |
| Sunucu / systemd / yedek | [`docs/modules/sunucu.md`](docs/modules/sunucu.md) · [`docs/modules/yedekleme.md`](docs/modules/yedekleme.md) |

**Test:** `cd backend && source venv/bin/activate && DATABASE_URL=postgresql://sprenses:PASS@127.0.0.1:5432/sprenses_test python -m pytest tests/ -q` · `cd frontend && npx vitest run && npm run check`

**Deploy:** backend `sudo systemctl restart sprenses-api.service` · frontend `scripts/deploy-frontend.sh` (build + restart; tek başına restart yetmez)
