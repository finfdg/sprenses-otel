# Proje Yapısı ve Katman Kuralları (2026-09-02 yeniden yapılandırması)

Bu doküman **dizin düzeyinde** ağacı ve katman yönü kurallarını tutar. Dosya bazlı listeler için:
endpoint kataloğu [`api-haritasi.md`](api-haritasi.md), modül dokümanları [`modules/README.md`](modules/README.md),
testler [`test-sistemi.md`](test-sistemi.md). Kuralların makine bekçisi: `backend/tests/test_layering.py`
(AST: katman ihlali + eski yol kalıntısı), `backend/tests/test_paths.py` (merkezi yol sabitleri),
`backend/tests/test_route_manifest.py` (465 rotanın yol/metot/endpoint/etiket kümesi dondurulmuştur).

## Katman yönü (backend)

```
routers → approval → services → (integrations | parsers | realtime | utils) → models
```

| Paket | Rol | Kural |
|---|---|---|
| `app/routers/<paket>/` | HTTP katmanı: endpoint, `Depends`, izin (`require_permission`), onay kapısı (`check_approval`), audit. | İş mantığı **taşımaz**; başka router PAKETİNDEN iş fonksiyonu import etmez (paket-içi `_helpers` serbest). Paket `__init__`'i alt-router önek/etiketlerini kablolar. |
| `app/approval/` | Onay motoru: `approval_check` (kapı), `approval_service` (workflow eşleme + durum makinesi), `approval_executor` (onaylanan payload'ı domain servisiyle uygular). | Router import etmez. Handler'lar router endpoint'iyle **aynı servis fonksiyonunu** çağırır. |
| `app/services/` | Domain iş mantığı (HTTP'siz): Sedna içe-aktarım, FIFO, eşleştirme, KPI/T-Hesap/runway/aging çekirdekleri, CRUD servisleri. | **Asla** `app.routers` import etmez (tek istisna `audit_finance_invariants.py`, bkz. aşağıda). `date.today()` varsayılanları ve yuvarlama kuralları finansal parmak izinin parçasıdır — verbatim korunur. |
| `app/integrations/` | Dış sistem istemcileri: Sedna (SQL Server), banka API'leri (Garanti/QNB/YKB/Vakıf), TCMB, SMTP, Amadeus. | `app.services`/`app.routers` import etmez. Testler `fetch_*` fonksiyonlarını modül niteliği üzerinden monkeypatch'ler → servisler bu fonksiyonları **adla** import eder. |
| `app/parsers/` | Saf ayrıştırıcılar: banka PDF/Excel, kredi kartı ekstresi, çek, rezervasyon, cari raporu. | DB/servis import'u yok. |
| `app/realtime/` | WS yayını (`finance_broadcast`/`sales_broadcast`, debounce'lu), bildirim, web-push. | `websocket.manager` üzerinden yayınlar; router import etmez. |
| `app/utils/` | **Yalnız teknik yardımcı**: audit log, security (hash/JWT), pagination, file_validation/file_upload, pdf_fonts, pdf_bank_instruction, md_docx, ai_export, db_log_handler, messaging_role_cache, finance_helpers, response_builders, sql_search, text_match. | Domain'e (`services`/`approval`) bağımlı olamaz. |
| `app/models/` · `app/schemas/` | SQLAlchemy modelleri (93 tablo; hepsi `models/__init__.py`'de kayıtlı → alembic autogenerate yüzeyi) · Pydantic şemaları. | `source_type` gibi DB'de saklanan sabitler **yalnız** `models/finance_event.py`'de tanımlıdır; `app/constants.py` re-export eder (`tests/test_constants.py`). |
| `app/paths.py` | `APP_DIR / BACKEND_DIR / REPO_ROOT / UPLOADS_DIR / LOGS_DIR / TESSDATA_DIR / VENV_DIR / CRON_DENETIM_SCRIPT / QNB_REFRESH_TOKEN_FILE` | Yeni kodda `__file__` derinliğinden yol türetme **yasak** (dosya taşınınca sessizce kayar); `tests/test_paths.py` bunu yasaklar. |

**Bilinçli istisna — `app/services/audit_finance_invariants.py`:** finansal parmak-izi kapısının değişmez
kaydı; ölçüm için router endpoint fonksiyonlarını çağırır. Yolu ve adı **donmuştur** (`cron_denetim_auto.py`
DEPLOY_BLOCKERS + `tests/test_denetim.py`). `tests/test_layering.py` bu dosyayı açık istisna listesinde tutar;
router çekirdekleri servislere çıkarıldıkça bu dosyanın import'ları servis yollarına çevrilir.

## Dizin ağacı (dizin düzeyi)

```
/home/ec2-user/otel/
├── CLAUDE.md                    # kural kitabı (Claude Code her oturumda yükler)
├── README.md · docs/            # bkz. docs/README.md
├── .github/workflows/ci.yml     # lint&tip + backend(pytest) + frontend(vitest) — hesap billing kilidi (CICD-010b)
├── .claude/                     # hook'lar (Stop: otomatik yedek commit), komutlar, agent'lar, workflow'lar
├── scripts/                     # host/ops: deploy-frontend.sh, db-backup/restore, offsite, health-thresholds,
│   └── systemd/                 #   systemd birimleri (bir kısmı YALNIZ /etc'de — docs/modules/sunucu.md)
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI + güvenlik middleware + 13 paket include'u
│   │   ├── config.py · database.py · constants.py · paths.py
│   │   ├── routers/
│   │   │   ├── core/            # auth, health, ws, push, notifications, files (/uploads), internal
│   │   │   ├── system/          # users, roles, modules, server, backup, docs, denetim, audit_logs, error_logs
│   │   │   ├── approval/        # sistem onay akışı (workflows, requests) — /api/system/approval
│   │   │   ├── finance/         # banks, checks, cash_flow/, cariler/, krediler/, butce, advances, … (+CLAUDE.md)
│   │   │   ├── accounting/      # fabrika ile taxes/recurring/rent_*, dividend/, fis_icmali, mizan, mutabakat (+CLAUDE.md)
│   │   │   ├── hr/              # fabrika ile salary/withholding/sgk + shifts, shift_schedule (+CLAUDE.md)
│   │   │   ├── attendance/      # PDKS kiosk/personel/log — /api/attendance (yol koruma: QR kartlar)
│   │   │   ├── sales/           # reservations/, contracts, agency_*, acente_mahsup, room_types (+CLAUDE.md)
│   │   │   ├── messages/        # mesajlaşma
│   │   │   ├── ai/              # asistan
│   │   │   ├── common/          # scheduled_factory (paketler-arası HTTP fabrikası)
│   │   │   └── stock.py
│   │   ├── approval/            # onay motoru (check / service / executor)
│   │   ├── services/            # domain servisleri (*_service.py + matching_service, finance_event_service, auto_tagger, vendor_fifo, …)
│   │   ├── integrations/        # sedna_client, banka API'leri, tcmb, mail
│   │   ├── parsers/             # bank/cc/check/reservation/vendor parser'ları
│   │   ├── realtime/            # finance_broadcast, sales_broadcast, notification, push
│   │   ├── utils/               # 15 teknik yardımcı
│   │   ├── models/ · schemas/ · middleware/ · websocket/
│   ├── alembic/                 # migration zinciri (doğrusal, tek head)
│   ├── tests/                   # pytest (2050+ test; fixtures/route_manifest.json; ci/ bootstrap)
│   ├── cron_*.py · denetim_finans_parmak_izi.py · seed_denetim.py   # systemd/otomasyon giriş noktaları — YOLLARI DONMUŞ
│   ├── seed_data/ · tessdata/ · uploads/ (gitignore) · logs/ (gitignore) · venv/ (gitignore)
│   └── alembic.ini · pytest.ini · ruff.toml · requirements.txt · .env (gitignore)
└── frontend/
    ├── src/
    │   ├── routes/              # SvelteKit sayfaları (+page.svelte); dashboard/<alan>/<sayfa>
    │   ├── lib/
    │   │   ├── api.ts           # fetch sarmalayıcı (cookie auth, 401 yönlendirme)
    │   │   ├── components/
    │   │   │   ├── ui/          # tasarım-sistemi primitive'leri (Button, Modal, StatCard, MoneyInput, …) + colocated testler
    │   │   │   ├── layout/      # Sidebar, Topbar, NotificationBell, ToastContainer
    │   │   │   ├── dashboard/   # Panel widget'ları (CashFlowTAccount, RunwayChart, OverdueList, HeldList, AiDigestCard)
    │   │   │   ├── scheduled/   # ScheduledModule — 7 planlı gelir/gider rotasının ortak sayfa şablonu
    │   │   │   ├── finance/     # cash-flow/ (nakit akım), cariler/ (cari modalleri + PaymentInstructions)
    │   │   │   ├── sales/ · messaging/ · ai/
    │   │   ├── stores/          # auth, ui, toast, notification, websocket + cashflow/ (cache, runway) + messaging/ (store + handler'lar)
    │   │   ├── utils/           # saf yardımcılar (finance, cashflow, validation, paymentMethods, …) + testler
    │   │   ├── types/ · constants/ (realtime.ts backend constants.py ile birebir) · config/navigation.ts
    │   ├── app.css · app.html · service-worker.ts
    ├── static/                  # PWA varlıkları (kimlik doğrulamasız sunulur — belge KOYMA)
    └── svelte.config.js · vite.config.ts · vitest.config.ts · package.json
```

## Doğrulama kapıları (her yapısal değişiklikte)

1. `ruff check app tests --select E9,F63,F7,F82` (kritik hata kapısı) + `python -c "import app.main"`
2. `pytest tests/` — kırmızı kümesi taban çizgisiyle **birebir** (yeni kırmızı yok)
3. `npx svelte-check --threshold error` 0 hata · `npx vitest run` yeşil
4. Finansal parmak izi: `backend/denetim_finans_parmak_izi.py` eski kod / yeni kod aynı DB'de **41/41 değişmez aynı**
5. `tests/test_route_manifest.py` — API yol/metot/endpoint/etiket kümesi değişmedi
