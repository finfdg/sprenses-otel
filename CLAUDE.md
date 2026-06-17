# Sprenses Otel Yönetim Sistemi

## Temel Kurallar

### Dil ve Yerelleştirme
- **Tüm kullanıcıya görünen metinler Türkçe karakterlerle yazılmalıdır** (ö, ü, ç, ş, ı, ğ, İ, Ö, Ü, Ç, Ş, Ğ)
- Hata mesajları, buton metinleri, başlıklar, placeholder'lar, confirm diyalogları, label'lar — hepsi doğru Türkçe karakterlerle olmalıdır
- ASCII Türkçe (ornegin "kullanici", "duzenle", "sifre") **kesinlikle kullanılmamalıdır**
- URL path'leri ASCII kalabilir (ör: `/dashboard/sistem/kullanicilar`)

### Saat Dilimi
- **Saat dilimi: Europe/Istanbul (UTC+3)**
- Backend'de `database.py` içinde her bağlantıda `SET timezone = 'Europe/Istanbul'` çalıştırılır
- JWT token oluşturmada `datetime.now(tz_istanbul)` kullanılır (`pytz` ile)
- `config.py` içinde `timezone: str = "Europe/Istanbul"` tanımlıdır

### İzin Sistemi
- İzinler 2 seviyedir: **can_view** (görme) ve **can_use** (kullanma = ekleme + düzenleme + silme)
- Backend'de `require_permission(module_code, "view"|"use")` middleware'i kullanılır
- Frontend'de `hasPermission(moduleCode, "view"|"use")` helper'ı kullanılır
- Yeni modül eklerken bu izin yapısına uyulmalıdır

### Onay Akışı Entegrasyonu — Zorunlu
- **Tüm modüllerin POST/PATCH/DELETE endpoint'leri** onay kontrolünden geçmelidir
- Yeni modül eklerken CRUD endpoint'lerine `check_approval()` çağrısı **zorunludur**
- Onay kontrolü varlık doğrulaması (404) **sonra**, DB mutasyonları **önce** yerleştirilir
- Onay gerekiyorsa endpoint 202 döner ve işlem `payload_json` olarak saklanır
- Onay gerekmiyorsa (eşleşen workflow yoksa) endpoint normal çalışır
- Dosya yükleme, toplu işlem, eşleştirme gibi özel endpoint'ler hariç tutulabilir
- Kullanım:
  ```python
  from app.utils.approval_check import check_approval

  # POST (create) — entity_id=0
  approval_resp = check_approval(db, "module.code", 0, current_user.id, "create", data.model_dump())
  if approval_resp:
      return approval_resp

  # PATCH (update) — entity_id=kayıt ID
  approval_resp = check_approval(db, "module.code", entity_id, current_user.id, "update", data.model_dump(exclude_unset=True))
  if approval_resp:
      return approval_resp

  # DELETE — entity_id=kayıt ID
  approval_resp = check_approval(db, "module.code", entity_id, current_user.id, "delete", {})
  if approval_resp:
      return approval_resp
  ```
- Onaylanan talepler `approval_executor.py`'deki handler ile uygulanır — yeni modül için handler eklenmeli
  - **Handler model alanları gerçek kolonlarla birebir olmalı.** Handler'lar yalnızca onay onaylanınca çalıştığı için yanlış import yolu / yanlış model alanı sessizce kalır (kapsam düşük). `tests/test_approval_system.py::TestExecutorImportIntegrity` iki AST testiyle (her `from app...import` ve her `Model(kwarg=...)` çağrısı) bu hata sınıfını **otomatik yakalar** — yeni handler bu testlerden geçmeli
  - Tüm onay motoru (workflow + talep + executor) `tests/test_approval_system.py` ile test edilir (49 test, uçtan-uca onay→uygula dahil)
- Detaylı bilgi: `docs/modules/onay-akisi.md`

### Python 3.9 Uyumluluğu
- `str | None` sözdizimi **kullanılamaz** — yerine `Optional[str]` kullanılmalıdır (`from typing import Optional`)
- Bu kural tüm type hint'ler için geçerlidir

### Güvenlik Kuralları
- **Credentials:** Tüm hassas bilgiler `.env` dosyasından okunur, kodda default değer **kullanılmaz**
- **Token Yönetimi:** JWT token **yalnızca HttpOnly cookie** ile taşınır — `localStorage`'da token saklanması **kesinlikle yasaktır**
  - Backend: `_set_auth_cookie()` ile `httponly=True, secure=True, samesite="lax"` cookie set edilir
  - Frontend: `credentials: 'include'` ile fetch yapılır, `Authorization` header kullanılmaz
  - Login/register response body'de `access_token` döndürülmez (cookie yeterli)
  - WebSocket: Upgrade request'teki cookie'den auth yapılır, fallback olarak auth mesajı desteklenir
- **Secret Karşılaştırma:** Internal secret ve hassas değer karşılaştırmalarında `secrets.compare_digest()` kullanılır (timing attack koruması)
- **CORS:** `allow_methods` ve `allow_headers` **whitelist** ile sınırlıdır — `["*"]` kullanılmaz
  - İzin verilen metodlar: `GET, POST, PUT, PATCH, DELETE, OPTIONS`
  - İzin verilen header'lar: `Content-Type, Authorization, X-Internal-Secret`
- **SECRET_KEY:** En az 32 karakter, kriptografik rastgele değer olmalıdır — `config.py`'de uzunluk kontrolü yapılır
- **Rate Limiting:** Login endpoint'inde IP bazlı rate limiting aktif (5 deneme/dakika)
- **Güvenlik Header'ları:** `SecurityHeadersMiddleware` ile X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy, **HSTS** ve **Content-Security-Policy** eklenir
  - **CSP (global):** `object-src 'none'; base-uri 'none'; frame-ancestors 'none'` — `default-src`/`script-src` **bilerek belirtilmez** ki FastAPI `/docs` (Swagger, CDN script) çalışsın; backend yalnızca JSON+dosya döndüğünden bu kısıtlar yeterli
  - **Dosya sunumu CSP:** `files.py` SVG/HTML için `Content-Disposition: attachment` + sıkı per-response CSP (`default-src 'none'; sandbox`) uygular → stored-XSS engellenir (mevcut SVG'ler `<img>` ile gösterilmeye devam eder ama doğrudan gezinmede script çalışmaz)
- **Logo/Dosya Yükleme — SVG yasak:** Logo yüklemesinde **SVG kabul edilmez** (stored-XSS riski; eski blacklist `onerror=`/`xlink:href` gibi vektörleri kaçırıyordu). Logolar raster (PNG/JPG/WEBP) olmalı ve **magic-byte** ile doğrulanır
- **Global Exception Handler:** Beklenmeyen hatalar loglanır, kullanıcıya generic mesaj döner
- **Audit Logging:** Tüm CRUD işlemleri ve giriş/çıkış olayları `audit_logs` tablosuna kaydedilir
- **SSH Ters Tünel Anahtarı — yalnızca-tünel sertleştirme:** Sedna ters tüneli (`127.0.0.1:11433`) için EC2 `authorized_keys`'teki anahtar **hem `command=` hem `permitopen=`** taşımalıdır. `restrict` **tek başına yetmez** (no-pty kabuğu kapatır ama komut çalıştırmayı engellemez → `ssh -i key host 'cat .env'` ile dosya okunur). `command="..."` keyfi komutu, `permitopen="127.0.0.1:1"` (`-L`/`-D` ölü porta) DB/IMDS pivotunu engeller. **`permitopen="none"` kullanma** — OpenSSH 8.7 anahtarı reddeder. Kalıcı zorlama: `scripts/ssh-key-audit.py` + systemd `ssh-key-audit.path`/`.timer` her yeni tünel anahtarını ~1 sn'de otomatik sertleştirir. Tam-erişimli admin anahtarları Ubuntu LAN makinesinde bulunmamalı. Detay: `docs/modules/ssh-tunel-guvenligi.md`

### Gerçek Zamanlılık — Polling Yasak
- **Polling (`setInterval` + HTTP) kesinlikle kullanılmamalıdır** — tüm gerçek zamanlı veri akışı WebSocket event'leri üzerinden yapılır
- Online durum, yeni mesaj, typing göstergesi, okundu bilgisi, konuşma güncellemeleri vb. **tamamı WS event-driven** olmalıdır
- WS `connected` event'i ilk bağlantıda gerekli başlangıç verisini (online kullanıcılar vb.) içerir — ayrıca HTTP çağrısı gerekmez
- Yalnızca WS bağlantısı olmayan sayfalar veya WS ile taşınamayan veriler için HTTP çağrısı yapılabilir (ör: ilk sayfa yüklemesi, arama)
- `setInterval` yalnızca WS keepalive (ping) için kullanılabilir, veri çekme amaçlı **kullanılamaz**
- **İstisna — Sunucu izleme (`/dashboard/sistem/sunucu`):** sistem metrikleri (CPU/RAM/disk/servis durumu) WS ile taşınmaz, 30 sn'lik `setInterval` ile fetch edilir. Sayfa kapanınca timer durur (`onDestroy`). Bu sınırlı istisna — başka sayfalarda polling yapılamaz.

### Kod Kalitesi Kuralları
- **Response Builder:** `utils/response_builders.py` — kullanıcı/rol yanıtları ortak helper ile oluşturulur (N+1 sorgu yok)
- **Form Validation:** Frontend'de `lib/utils/validation.ts` helper'ları kullanılır
- **Modal:** Frontend'de `lib/components/Modal.svelte` reusable bileşeni kullanılır
- **Hata Yakalama:** Boş `catch {}` blokları **yasaktır** — her catch bloğunda `console.error` ve gerekirse kullanıcı bildirimi olmalıdır
- **Pagination:** List endpoint'leri `{ items, total, page, page_size, pages }` formatında döner
- **Merkezi Sabitler (sihirli string yasak):** WS event tipleri, broadcast modül adları ve planlı `source_type` değerleri **literal yazılmaz** — backend `app/constants.py` (`WSEvent`/`BroadcastModule`/`SourceType`), frontend `lib/constants/realtime.ts` (`WS_EVENT`/`BROADCAST_MODULE`). İki taraf birebir aynı tutulur (otomatik senkron yok). Finans `source_type`'ları `models/finance_event.py`'den re-export edilir (çift tanım yok). DB-saklı değerler değiştirilemez. `onWsEvent`/`emitLocal` `WsEventType` union ile tiplidir → typo derleme hatası. Detay: `docs/modulerlik-iyilestirmeleri.md`

### Dosya İçi Kod Düzeni — Zorunlu

Tüm yeni dosyalar aşağıdaki sıralamaya uymalıdır. Mevcut dosyalarda da bu düzen korunur.

#### Backend Python Dosyası (Router)
```
1. Modül docstring               """Açıklama..."""
2. Standart kütüphane import     import math, from typing import Optional
3. Üçüncü parti import           from fastapi import ..., from sqlalchemy import ...
4. Proje içi import              from app.database import ..., from app.models import ...
5. Sabitler                       SOURCE_BANK = "bank", DIRECTION_INCOME = 1
6. Router / sınıf tanımlama      router = APIRouter()
7. Yardımcı fonksiyonlar          def _build_response(...):  (alt çizgi ile başlar)
8. Endpoint'ler (CRUD sırası)     @router.get → post → patch → delete
9. Özet / aggregate endpoint      @router.get("/summary")
```

#### Backend Python Dosyası (Model)
```
1. Modül docstring
2. SQLAlchemy import             from sqlalchemy import Column, String, ...
3. Proje içi import              from app.database import Base
4. Sabitler                       STATUS_ACTIVE = "active"
5. Model sınıfı                   class User(Base): ...
   - __tablename__
   - Kolonlar (PK → FK → veri → zaman damgası → flags)
   - İlişkiler (relationship)
   - Index tanımları (__table_args__)
```

#### Backend Python Dosyası (Schema)
```
1. Modül docstring
2. Import                         from pydantic import BaseModel, Field
3. Create şeması                  class UserCreate(BaseModel): ...
4. Update şeması                  class UserUpdate(BaseModel): ...
5. Response şeması                class UserResponse(BaseModel): ...
```

#### Frontend Svelte Dosyası
```
<script lang="ts">
1. Import'lar
   - Svelte              import { onMount, onDestroy } from 'svelte';
   - SvelteKit           import { goto } from '$app/navigation';
   - Proje store/api     import { api } from '$lib/api';
   - Bileşenler          import Modal from '$lib/components/Modal.svelte';
2. Props ($props)         let { title, apiPrefix } = $props();
3. Sabitler               const MONTH_NAMES = [...];
4. Türetilmiş ($derived)  let canUse = $derived(hasPermission(...));
5. State ($state)
   - Veri state           let items = $state<any[]>([]);
   - UI state             let loading = $state(true);
   - Form state           let form = $state({ name: '', ... });
6. Formatlama fn          function fmt(n): string { ... }
7. Veri fonksiyonları     async function loadData() { ... }
8. CRUD fonksiyonları     openAdd → openEdit → handleSave → confirmDelete
9. UI yardımcıları        function toggleExpand(id) { ... }
10. Lifecycle             onMount(() => { ... }); onDestroy(() => { ... });
</script>

TEMPLATE:
1. <svelte:head>          <title>...</title>
2. Sayfa başlığı          header + filtreler + butonlar
3. Özet kartları          istatistik kartları
4. Ana içerik             loading → empty state → veri listesi/tablo
5. Modal'lar              sayfanın en altında

```

#### Frontend TypeScript Dosyası (store, utils)
```
1. Import'lar
2. Type / interface tanımları
3. Sabitler / konfigürasyon
4. Export edilen state ($state)
5. Export edilen fonksiyonlar (public)
6. Yardımcı fonksiyonlar (private, export edilmeyen)
```

### Değişiklik Dokümantasyonu — Zorunlu
- **Her değişiklik sonrası** ilgili modülün `CLAUDE.md` dosyası güncellenmeli (ör: `backend/app/routers/finance/CLAUDE.md`)
- İş kuralları, mimari kararlar, "neden böyle yapıldı" açıklamaları mutlaka kayıt altına alınmalı
- Kullanıcı hatırlatmasına gerek kalmadan, değişiklik tamamlandığında otomatik olarak yazılmalı
- Sadece kod değişikliği değil, **iş mantığı kararları** da belgelenmeli (ör: "FIFO ile ödeme kırpma", "match_number neden tekrar kullanılmaz")
- Modül bazlı dokümanlar `docs/modules/` altında, geliştirici rehberleri ilgili modül klasöründeki `CLAUDE.md`'de tutulur

## Tech Stack

| Teknoloji | Sürüm | Açıklama |
|---|---|---|
| **PostgreSQL** | 15.15 | Veritabanı |
| **Python** | 3.9.25 | Backend (venv) |
| **FastAPI** | 0.115.11 | API framework |
| **Uvicorn** | 0.34.0 | ASGI server |
| **SQLAlchemy** | 2.0.38 | ORM |
| **Alembic** | 1.14.1 | DB migrations |
| **Svelte** | 5.53.2 | Frontend framework (Runes: $state, $props, $effect) |
| **SvelteKit** | 2.53.0 | Full-stack framework |
| **Tailwind CSS** | 4.2.0 | CSS framework (Vite plugin) |
| **Node.js** | 20.20.0 | JS runtime |
| **pytz** | 2025.2 | Saat dilimi |
| **pytest** | 8.3.4 | Backend test framework |
| **Vitest** | latest | Frontend test framework |

## Sunucu

- **OS:** Amazon Linux 2023 (EC2)
- **Web Server:** Nginx 1.28.1 + Let's Encrypt SSL
- **Domain:** sprenses.com

## Proje Yapısı

```
/home/ec2-user/otel/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint + security middleware
│   │   ├── config.py            # Pydantic Settings (.env'den, default yok)
│   │   ├── database.py          # SQLAlchemy engine + timezone ayarı
│   │   ├── models/              # User, Role, Module, RoleModulePermission,
│   │   │                        # Conversation, Message, AuditLog, PushSubscription,
│   │   │                        # Notification, ErrorLog, Vendor, VendorUpload,
│   │   │                        # VendorTransaction, BankAccount, BankStatement,
│   │   │                        # BankTransaction, Check, CheckUpload, CreditProduct,
│   │   │                        # CreditPayment, CreditCardStatement, Advance,
│   │   │                        # Department, Budget, BudgetCategory, FinanceEvent,
│   │   │                        # ScheduledDefinition, ScheduledEntry, ExchangeRate,
│   │   │                        # TransactionCategory, QualityTemplate, QualityForm,
│   │   │                        # Reservation, ReservationUpload, RoomType
│   │   ├── schemas/             # Pydantic şemaları (user, role, module, message,
│   │   │                        # push, pagination, check, credit, budget, scheduled)
│   │   ├── routers/             # auth, health, system_users, system_roles,
│   │   │                        # system_modules, messages, audit, ws, push,
│   │   │                        # notifications, files, error_logs, internal,
│   │   │                        # finance/ (banks, checks, cariler/,
│   │   │                        #   cash_flow/, krediler, cc_statements,
│   │   │                        #   exchange_rates, transaction_tags, onay,
│   │   │                        #   butce, departmanlar, advances,
│   │   │                        #   banks_cc_match),
│   │   │                        # accounting/__init__.py  — taxes, recurring,
│   │   │                        #   rent_income, rent_expense, dividend altmodüllerini
│   │   │                        #   `create_scheduled_router(module_code, ...)` fabrikasıyla üretir
│   │   │                        # hr/__init__.py          — salary, withholding, sgk altmodülleri (aynı fabrika)
│   │   │                        # quality/ (templates, forms, scheduler)
│   │   │                        # sales/ (reservations, room_types, agency_groups, flights)
│   │   │                        # approval/ (workflows, requests) — sistem onay akışı
│   │   │                        # finance/bank_instructions — EFT/havale/döviz PDF üretim
│   │   ├── middleware/
│   │   │   ├── auth.py          # JWT auth + require_permission()
│   │   │   └── rate_limit.py    # IP bazlı rate limiting
│   │   ├── utils/
│   │   │   ├── security.py      # Password + JWT helpers
│   │   │   ├── response_builders.py # Ortak yanıt oluşturucular
│   │   │   ├── audit.py         # Audit log helper
│   │   │   ├── push.py          # Push bildirim helper
│   │   │   ├── notification.py  # Bildirim oluşturma + gönderme
│   │   │   ├── finance_event_service.py  # Merkezi finance_events servisi
│   │   │   ├── finance_broadcast.py      # WS broadcast + debounce
│   │   │   ├── entry_generator.py        # Planlı gider giriş üretici
│   │   │   └── file_validation.py        # MIME + boyut doğrulaması
│   │   └── websocket/
│   │       └── manager.py       # WebSocket bağlantı yönetimi
│   ├── alembic/                 # DB migrations
│   ├── tests/                   # pytest testleri (900+ test, ~%60 satır kapsamı)
│   │   ├── conftest.py          # Test fixture'ları (SAVEPOINT rollback)
│   │   ├── test_health.py
│   │   ├── test_auth.py
│   │   ├── test_system.py, test_system_users.py, test_system_roles.py, test_system_modules.py
│   │   ├── test_messages.py, test_messages_extended.py
│   │   ├── test_finance.py, test_finance_performance.py
│   │   ├── test_scheduled_base.py   # Muhasebe + İK (8 modül)
│   │   ├── test_credits.py, test_checks.py, test_budget.py, test_onay.py
│   │   ├── test_advances.py, test_quality_module.py
│   │   ├── test_approval_system.py  # Sistem onay akışı motoru (workflow/talep/executor)
│   │   ├── test_security.py         # CSP başlığı + logo/SVG XSS sertleştirme
│   │   ├── test_notifications.py    # Bildirim testleri
│   │   ├── test_permissions.py      # İzin kontrolleri
│   │   ├── test_ws_push_audit.py
│   │   └── ci/                      # CI/test DB bootstrap (alembic upgrade head + reset_data.sql + 02_seed.sql + seed_admin.py)
│   ├── venv/                    # Python sanal ortam
│   ├── requirements.txt
│   ├── pytest.ini
│   └── .env                     # Ortam değişkenleri (GİT'E EKLENMEMELİ)
├── frontend/
│   ├── src/
│   │   ├── routes/              # SvelteKit sayfalar
│   │   │   ├── +page.svelte     # Login
│   │   │   └── dashboard/
│   │   │       ├── +page.svelte          # Panel
│   │   │       ├── mesajlasma/           # Mesajlaşma
│   │   │       ├── finans/               # Bankalar, Çekler, Cariler, Krediler,
│   │   │       │                         # Nakit Akım, Avanslar, Döviz, Bütçe, Onay
│   │   │       ├── muhasebe/             # Vergiler, Düzenli Ödemeler, Kiralar, Temettü
│   │   │       ├── ik/                   # Maaş, Stopaj, SGK
│   │   │       ├── kalite/               # Şablonlar, Formlar
│   │   │       └── sistem/               # Kullanıcılar, Roller, Modüller,
│   │   │                                 # Audit Loglar, Hata Logları
│   │   ├── lib/
│   │   │   ├── api.ts                    # Fetch wrapper (401/403 handling)
│   │   │   ├── stores/auth.ts            # Auth store + hasPermission()
│   │   │   ├── stores/ui.svelte.ts       # UI state (sidebar açık/kapalı)
│   │   │   ├── stores/notification.svelte.ts # Bildirim sesi
│   │   │   ├── stores/websocket.svelte.ts    # WebSocket yönetimi
│   │   │   ├── components/
│   │   │   │   ├── Modal.svelte          # Reusable modal bileşeni
│   │   │   │   ├── Sidebar.svelte        # Sol menü
│   │   │   │   ├── Topbar.svelte         # Üst bar
│   │   │   │   └── StatCard.svelte       # İstatistik kartı
│   │   │   └── utils/
│   │   │       ├── finance.ts            # formatCurrency, groupByMonth, getTodayKeys
│   │   │       ├── finance.test.ts       # Finans yardımcı testleri (23 test)
│   │   │       ├── paymentMethods.ts     # Ödeme yöntemi haritası + helper
│   │   │       ├── paymentMethods.test.ts # Ödeme yöntemi testleri (16 test)
│   │   │       ├── colorMap.ts           # Kategori renk haritası + getColor
│   │   │       ├── colorMap.test.ts      # Renk haritası testleri (16 test)
│   │   │       ├── push.ts              # Push bildirim yardımcıları
│   │   │       ├── push.test.ts          # Push testleri (6 test)
│   │   │       ├── validation.ts         # Form doğrulama yardımcıları
│   │   │       └── validation.test.ts    # Doğrulama testleri (12 test)
│   │   ├── api.test.ts              # API wrapper testleri (22 test)
│   │   └── app.css              # Tailwind import
│   ├── build/                   # Production build output
│   ├── svelte.config.js         # adapter-node
│   ├── vite.config.ts           # Tailwind + SvelteKit plugin
│   └── vitest.config.ts         # Vitest test yapılandırması
├── docs/
│   └── modules/                 # Modül bazlı CLAUDE.md dosyaları
│       └── nakit-akim.md        # Nakit Akım modülü dokümantasyonu
└── CLAUDE.md
```

## Servisler

| Servis | Port | Systemd Unit |
|---|---|---|
| FastAPI (Backend) | 8001 | `sprenses-api.service` |
| SvelteKit (Frontend) | 3000 | `sprenses-frontend.service` |
| PostgreSQL | 5432 | `postgresql.service` |
| Nginx | 443/80 | `nginx.service` |

### Deploy Akışı — Zorunlu

- **Backend:** Kod değişikliği yapıldığında `sudo systemctl restart sprenses-api.service` yeterli (uvicorn yeniden başlar, yeni Python dosyalarını yükler).
- **Frontend:** SvelteKit production modda (`node build`) çalışır — kaynak dosya değişikliği **build alınmadan yansımaz**. Her UI değişikliğinden sonra:
  ```bash
  /home/ec2-user/otel/scripts/deploy-frontend.sh
  ```
  Bu script `npm run build` + `systemctl restart` zincirini çalıştırır. Tek başına `restart` yetmez.
- **Tarayıcı önbelleği:** Deploy sonrası kullanıcının hard-refresh yapması gerekebilir (Cmd/Ctrl+Shift+R · iPad Safari: yenile ikonuna uzun bas → "Sürüm Yenile").

### Sürüm Kontrolü ve CI

- **Git:** Proje `master` branch'inde versiyon kontrolü altındadır. `.gitignore` hassas/üretilen her şeyi hariç tutar (`.env`, `venv`, `node_modules`, `build`, `.svelte-kit`, loglar, `uploads/`, `.claude/settings.local.json`). `.env` **asla** commit edilmez — şablon: `backend/.env.example`.
- **CI:** `.github/workflows/ci.yml` her push/PR'da backend (pytest) + frontend (vitest) çalıştırır. Postgres service container + `tests/ci/` bootstrap ile sıfırdan test DB kurulur.
- **Test DB bootstrap (`backend/tests/ci/`):** Şema doğrudan migration zincirinden kurulur — `alembic upgrade head` (zincir prod ile birebir) → `reset_data.sql` (migration'ın eklediği veriyi temizle) → `02_seed.sql` (RBAC referans verisi) → `seed_admin.py` (admin kullanıcısı). Ayrı şema dump'ı (`01_schema.sql`) artık yok. Yerelde: `scripts/setup-test-db.sh`. Detay ve migration-zinciri doğrulaması: `backend/tests/ci/README.md`.

## API Endpoints

### Kimlik Doğrulama
- `POST /api/auth/login` — Giriş (rate limited: 5/dk)
- `POST /api/auth/register` — Kayıt
- `GET /api/auth/me` — Mevcut kullanıcı bilgisi
- `POST /api/auth/change-password` — Şifre değiştirme (kendi şifresi)

### Sistem Yönetimi
- `GET/POST/PATCH/DELETE /api/system/users/` — Kullanıcı CRUD (paginated)
- `POST /api/system/users/{id}/reset-password` — Şifre sıfırlama (admin)
- `GET/POST/PATCH/DELETE /api/system/roles/` — Rol CRUD (izin matrisi dahil)
- `GET/POST/PATCH/DELETE /api/system/modules/` — Modül CRUD
- `GET /api/system/modules/tree` — Modül ağacı (hiyerarşik)
- `GET /api/system/audit-logs/` — Audit logları (paginated, filtrelenebilir)

### Mesajlaşma
- `GET /api/messages/conversations` — Konuşma listesi
- `POST /api/messages/conversations` — Yeni konuşma başlat
- `GET /api/messages/conversations/{id}` — Konuşma mesajları
- `POST /api/messages/conversations/{id}` — Mesaj gönder
- `PATCH /api/messages/conversations/{id}/messages/{msg_id}` — Mesaj düzenle
- `DELETE /api/messages/conversations/{id}/messages/{msg_id}` — Mesaj sil (soft delete)
- `PATCH /api/messages/conversations/{id}/read` — Okundu olarak işaretle
- `GET /api/messages/unread-count` — Okunmamış mesaj sayısı
- `GET /api/messages/users` — Mesajlaşılabilir kullanıcı listesi

### Finans — Nakit Akım
- `GET /api/finance/cash-flow/` — Kayıt listesi (paginated, type/source/start_date/end_date/search filtresi)
- `GET /api/finance/cash-flow/mobile-dashboard` — Mobil dashboard özeti (banka bakiyeleri dahil)
- `GET /api/finance/cash-flow/summary` — Toplam gelir, gider, bakiye
- `GET /api/finance/cash-flow/monthly-summary` — Aylık gelir/gider/bakiye özeti
- `GET /api/finance/cash-flow/eur-balances` — EUR bakiye özeti
- `GET /api/finance/cash-flow/credit-payments-unpaid` — Ödenmemiş kredi taksitleri
- `GET /api/finance/cash-flow/cc-statements-unpaid` — Ödenmemiş kredi kartı ekstreleri
- `POST /api/finance/cash-flow/match-vendor-tx` — Cari işlem eşleştirme
- `POST /api/finance/cash-flow/match-cc-payment` — Kredi kartı ödeme eşleştirme
- `POST /api/finance/cash-flow/match-credit-payment` — Kredi taksit ödeme eşleştirme
- `POST /api/finance/cash-flow/unmatch-cc-payment` — Kredi kartı eşleştirme iptali
- Detaylı bilgi: `docs/modules/nakit-akim.md`

### Finans — Satış Faturaları (Otel oda satışları + tahsilat)
- `GET /api/finance/sales-invoices/` — Satış faturaları listesi (FIFO tahsil durumu; filtre: `customer_type` munferit/agency, `status` paid/partial/open, `start_date`/`end_date`/`search`, paginated). 120/Alıcılar = cariler'in (320) aynası
- `GET /api/finance/sales-invoices/summary` — Özet: toplam faturalanan/tahsil/açık + münferit/acente kırılımı + durum sayıları + **kullanılmamış net avans** bakiyesi
- `GET /api/finance/sales-invoices/advances` — **Acente avans bakiyeleri** (acentelerin yatırıp henüz fatura ile kapatmadığı net avans; yatırılan/kapanan/kalan). Acente avansı = 120 hesabına ALACAK, faturalarla (Borç) FIFO mahsup. Liste `by_advance` rozeti taşır
- `POST /api/finance/sales-invoices/sedna-import` — **Sedna'dan satış faturası + tahsilat içe aktarma** (120 Borç=fatura DocumentType=1, 120 Alacak=tahsilat; FIFO ile fatura bazında ödendi/kısmi/açık). finance.sales_invoices use, audit'li, onaydan muaf. Merkezi Sedna sync'in adımı. Detay: `docs/modules/satis-faturalari.md`

### Finans — Sedna Senkronizasyonu (Merkezi)
- `POST /api/finance/sedna/sync-all` — **Tek noktadan tüm Sedna içe aktarmaları** (cari hareketleri + cari IBAN'ları + verilen çekler + **satış faturaları** + **stok/depo** + **otel rezervasyonları** + düzenli ödeme cari senkronu). Topbar'daki tek "Sedna" butonu bunu çağırır. Her adım izin kontrollü (kullanıcının `use` izni olmayan adım "Yetki yok" atlanır), adım-bazlı izole (biri hata verirse diğerleri sürer). Yanıt: `{ok_count, total, steps:[{key,label,ok,skipped,summary}]}`
- `GET /api/finance/sedna/status` — Merkezi sync etkin mi + kullanıcının çalıştırabileceği adımlar (buton gösterimi)
- **Genişletme:** Yeni Sedna içe aktarma = `run_xxx_import(db, user, ip)` servis fonksiyonu yaz + `sedna_sync.py:_STEPS`'e ekle → Topbar butonu otomatik kapsar. **Sayfa-içi ayrı Sedna butonu eklenmez** (eski cariler/çekler kutuları kaldırıldı). Tekil endpoint'ler (`/cariler/sedna-import`, `/cariler/sedna-import-ibans`, `/checks/sedna-import`) orchestrator + hedefli kullanım için korunur.

### Finans — Cariler
- `POST /api/finance/cariler/upload` — Excel dosya yükleme (response içinde `removal_candidates` döner: kapsamda olup Excel'de bulunmayan kayıtlar)
- `POST /api/finance/cariler/sedna-import` — **Sedna (muhasebe SQL Server) doğrudan içe aktarma** (ters SSH tüneli `127.0.0.1:11433` üzerinden 320/satıcı cari hareketleri). Excel yükleme ile **aynı upsert + tx_hash dedup** → mükerrer olmaz. Yanıt Excel ile aynı (`removal_candidates` dahil). Tünel kapalıysa 503. finance.cariler use, audit'li, onaydan muaf
- `POST /api/finance/cariler/sedna-import-ibans` — **Sedna cari IBAN içe aktarma** (`dbo.Bank` → `vendor_bank_accounts`; cari koduna bağlı, firma başına çok IBAN). Yalnız mevcut carilere işler, dedup + ilk varsayılan + boş banka adını doldurur (idempotent). Ödeme talimatı IBAN'larını besler. finance.cariler use, audit'li, onaydan muaf
- `GET /api/finance/cariler/sedna-status` — Sedna içe aktarma etkin mi (`{configured}`; buton gösterimi). Detay: `docs/modules/cariler.md`
- `GET /api/finance/cariler/uploads` — Yükleme geçmişi
- `DELETE /api/finance/cariler/uploads/{id}` — Yükleme sil
- `POST /api/finance/cariler/transactions/bulk-delete` — Toplu işlem silme (kaynakta olmayan kayıtlar için; korumalı kayıtlar atlanır)
- `GET /api/finance/cariler/vendors` — Cari listesi (paginated, arama)
- `GET /api/finance/cariler/vendors/{id}` — Cari detay + işlemler
- `GET/POST/PATCH/DELETE /api/finance/cariler/vendors/{id}/bank-accounts[/{ba_id}]` — **Cari banka hesapları (IBAN)** — bir cari → 0..N IBAN; biri varsayılan. Sedna'da cari IBAN'ı boş olduğundan burada yönetilir; ödeme talimatında kullanılır. IBAN normalize + mükerrer 409 + varsayılan devri. finance.cariler use, audit'li
- `GET /api/finance/cariler/payment-schedule` — Haftalık ödeme planı
- Detaylı bilgi: `docs/modules/cariler.md`

### Finans — Ödeme Talimat Listeleri
- `GET/POST /api/finance/payment-instructions/` — Talimat listesi listele/oluştur
- `GET/PATCH/DELETE /api/finance/payment-instructions/{id}` — Liste detay/güncelle/sil
- `POST /api/finance/payment-instructions/{id}/items` — Cari kalem(ler) ekle (tutar bakiyeden gelir, mükerrer vendor atlanır; **carinin varsayılan banka/IBAN'ı otomatik gelir**, kalemde override edilebilir). Kalem `bank_name`+`iban` snapshot'ı taşır; PDF/Excel dökümünde **Banka + IBAN sütunları** yer alır
- `PATCH/DELETE /api/finance/payment-instructions/{id}/items/{item_id}` — Kalem tutarı güncelle / çıkar
- `GET /api/finance/payment-instructions/{id}/export/excel` — Excel dökümü (okunur liste)
- `GET /api/finance/payment-instructions/{id}/export/pdf` — PDF dökümü
- `GET /api/finance/payment-instructions/{id}/export/ykb-excel?debtor_account=` — **Yapı Kredi toplu ödeme** Excel'i (bankanın yükleme şablonu birebir: sayfa `ykb excel`, 11 kolon, IBAN boşluksuz, TUTAR düz ondalık, DÖVİZ=TL; BORÇLU HESAP = `debtor_account` param)
- Frontend: Cariler sayfasında "Ödeme Talimatı" sekmesi · İzin: `finance.cariler`
- Detaylı bilgi: `docs/modules/cariler.md` (Ödeme Talimat Listeleri bölümü)

### Finans — Onay (Departman Onay İş Akışı)
- `POST /api/finance/onay/assign/{vtx_id}` — Cari kaydına departman ata
- `GET /api/finance/onay/my-approvals` — Onay bekleyen kayıtlar
- `GET /api/finance/onay/pending-count` — Onay bekleyen sayısı (badge)
- `POST /api/finance/onay/approve/{vtx_id}` — Onayla
- `POST /api/finance/onay/reject/{vtx_id}` — Reddet
- `POST /api/finance/onay/remove/{vtx_id}` — Atamayı kaldır
- Detaylı bilgi: `docs/modules/onay.md`

### Muhasebe — Vergiler, Düzenli Ödemeler, Kiralar
- `GET/POST/PATCH/DELETE /api/accounting/taxes/` — Vergi tanım CRUD + giriş üretimi
- `PATCH /api/accounting/taxes/entries/{id}` — Vergi girişi güncelle (tutar, ödendi)
- `GET /api/accounting/taxes/summary/totals` — Vergi özeti
- `GET/POST/PATCH/DELETE /api/accounting/recurring/` — Düzenli ödeme CRUD (tanım `vendor_id` ile cariye bağlanabilir)
- `PATCH /api/accounting/recurring/entries/{id}` — Düzenli ödeme girişi güncelle
- `GET /api/accounting/recurring/summary/totals` — Düzenli ödeme özeti
- `POST /api/accounting/recurring/sync-vendors` — **Cari senkronu**: cari-bağlı kalemleri (Elektrik→CK, Su→ASAT) cari gerçek fatura + FIFO ödeme durumuyla senkronla. Faturası gelen ay tahmini→gerçek + recurring FE silinir (çift sayım önleme), gelecek aylar tahmini kalır. Merkezi Sedna butonu da çağırır (`recurring_sync` adımı). Detay: `docs/modules/muhasebe-ik.md`
- `GET/POST/PATCH/DELETE /api/accounting/rent-income/` — Alınan kira CRUD (gelir, direction=+1)
- `PATCH /api/accounting/rent-income/entries/{id}` — Alınan kira girişi güncelle
- `GET /api/accounting/rent-income/summary/totals` — Alınan kira özeti
- `GET/POST/PATCH/DELETE /api/accounting/rent-expense/` — Verilen kira CRUD (gider, direction=-1)
- `PATCH /api/accounting/rent-expense/entries/{id}` — Verilen kira girişi güncelle
- `GET /api/accounting/rent-expense/summary/totals` — Verilen kira özeti
- `GET/POST/PATCH/DELETE /api/accounting/dividend/` — Temettü tanım CRUD
- `PATCH /api/accounting/dividend/entries/{id}` — Temettü girişi güncelle
- `GET /api/accounting/dividend/summary/totals` — Temettü özeti
- Detaylı bilgi: `docs/modules/muhasebe-ik.md`

### Muhasebe — Kullanıcı Fiş İcmali (Sedna canlı)
- `GET /api/accounting/fis-icmali/summary?start_date&end_date&granularity&date_field` — **Sedna muhasebe fişlerini KESEN kullanıcıya göre gün/ay icmali** (kim ne zaman ne kadar fiş kesmiş). `AccountingOwner.RecordUser` + `Users` (ad); kullanıcı × dönem pivot. `granularity`=month|day, `date_field`=record (kayıt tarihi)|fiche (fiş tarihi). Canlı sorgu (model/import yok); ≤400 gün; tünel kapalı→503. accounting.fis_icmali view
- `GET /api/accounting/fis-icmali/vouchers?user_code&start_date&end_date&date_field` — **Drill-down:** bir kullanıcının aralıkta kestiği fişler (rec_id/no/tarih/tutar/açıklama)
- `GET /api/accounting/fis-icmali/voucher-detail?rec_id` — **Drill-down:** tek fişin muhasebe satırları (hesap kodu/adı, borç, alacak, toplam, kesen/değiştiren)
- `GET /api/accounting/fis-icmali/status` — Sedna etkin mi (`{configured}`)
- Detaylı bilgi: `docs/modules/fis-icmali.md`

### Muhasebe — Mizan (Geçici Mizan / Sedna canlı)
- `GET /api/accounting/mizan/summary?start_date&end_date&level&parent&search` — **Sedna hesaplarının dönem borç/alacak/bakiye mizanı** (kademe bazında: 1=ana hesap → alt hesap). `AccountingTrans` (borç/alacak) + `Accounting` (ad); leaf bazında çekilip kademe Python'da toplanır. `level`=kademe, `parent`=drill (alt hesaplar), `search`=Türkçe-duyarsız kod/ad. Yanıt `grand_total_borc/alacak` + `balanced` (denge: borç=alacak). Canlı sorgu (model/import yok); ≤800 gün; 60sn TTL cache; tünel kapalı→503. accounting.mizan view
- `GET /api/accounting/mizan/transactions?code&start_date&end_date` — **Drill-down:** hesabın (+ alt hesapları) hareketleri (defter) + yürüyen bakiye (ilk 1000)
- `GET /api/accounting/mizan/status` — Sedna etkin mi (`{configured}`)
- Detaylı bilgi: `docs/modules/mizan.md`

### İnsan Kaynakları — Maaş & Stopaj
- `GET/POST/PATCH/DELETE /api/hr/salary/` — Maaş tanım CRUD + giriş üretimi
- `PATCH /api/hr/salary/entries/{id}` — Maaş girişi güncelle
- `GET /api/hr/salary/summary/totals` — Maaş özeti
- `GET/POST/PATCH/DELETE /api/hr/withholding/` — Stopaj tanım CRUD
- `PATCH /api/hr/withholding/entries/{id}` — Stopaj girişi güncelle
- `GET /api/hr/withholding/summary/totals` — Stopaj özeti
- `GET/POST/PATCH/DELETE /api/hr/sgk/` — SGK tanım CRUD
- `PATCH /api/hr/sgk/entries/{id}` — SGK girişi güncelle
- `GET /api/hr/sgk/summary/totals` — SGK özeti
- Detaylı bilgi: `docs/modules/muhasebe-ik.md`

### İnsan Kaynakları — Devam Takip (PDKS)
- `GET /api/attendance/kiosk/qr?key=` — Girişteki ekranın dönen QR'ı (SVG, KIOSK_KEY gerekli; token panelden ayarlanan süre kadar geçerli)
- `GET /api/attendance/kiosk/config?key=` — Kiosk ekran yenileme süresi (KIOSK_KEY; ~15sn'de bir otomatik uyarlanır)
- `GET /api/attendance/kiosk/recent?key=` — Kiosk sağ paneli için son giriş/çıkış hareketleri (KIOSK_KEY)
- `GET /api/attendance/kiosk-link` — Kiosk ekranı linki (admin; KIOSK_KEY dahil)
- `GET/PATCH /api/attendance/settings` — QR yenileme süresi ayarı (hr.attendance; 2-120sn; geçerlilik=yenileme+3sn; panelden Ayarlar)
- `POST /api/attendance/setup` — Kişisel kurulum (enrollment): access_token ile **bu cihazı bağlar**, cihaza özel `device_token` döndürür (anti-buddy-punch). Zaten başka cihaza bağlıysa **409** → admin "Cihaz Sıfırla" gerekir
- `GET /api/attendance/pdks-manifest?t=` — Kişiye özel PWA manifest'i (public): "Ana Ekrana Ekle" ikonu kişisel basış sayfasını (token'lı start_url, standalone) açar — login'e değil. Global manifest `/devam`'da kullanılmaz; geçmiş silinse de token URL'de kalır
- `GET /api/attendance/me` — Personelin durumu (`X-Pdks-Device` başlığı)
- `POST /api/attendance/punch` — Giriş/çıkış kaydet (`X-Pdks-Device` cihaz token'ı + canlı kiosk token `k`)
- `POST /api/attendance/personnel/{id}/reset-device` — Bağlı cihazı çöz (hr.attendance use; audit'li) → yeni telefon/veri-silme sonrası tekrar kurulum için
- `GET/POST/PATCH/DELETE /api/attendance/personnel[/{id}]` — Personel CRUD (hr.attendance; sicil no=employee_code, departman, **görev**; liste `device_bound` durumu döner)
- `POST /api/attendance/personnel/import` — Excel sicil listesi içe aktar (Sicil No/Ad Soyad/Departman/Görev; upsert; .xls+.xlsx)
- `GET /api/attendance/personnel/{id}/qr` — Kişisel kurulum QR (kart)
- `GET /api/attendance/personnel/cards.pdf` — Tüm aktif personelin QR kartları tek PDF (yazdırılıp kesilebilir)
- `GET /api/attendance/status` — Şu an içeride kim
- `GET /api/attendance/logs` — Giriş/çıkış geçmişi (filtreli)
- `GET /api/attendance/summary?month=` — Aylık puantaj
- `POST /api/attendance/manual` — Yönetici elle giriş/çıkış (zaman seçilebilir; çift giriş/çıkış engelli; hr.attendance workflow'u varsa onaya düşer → `_handle_attendance` executor)
- `PATCH /api/attendance/logs/{id}` — Kaydı elle düzenle (tip/zaman/not; çift engelli; audit + onay)
- `DELETE /api/attendance/logs/{id}` — Kaydı sil (soft delete: deleted_at; Geçmiş'te soluk kalır, aktif hesaplara girmez; audit + onay)
- `GET /api/attendance/logs/{id}/history` — Kaydın değişiklik tarihçesi (audit) + bekleyen işlem
- `GET /api/attendance/pending` — Bekleyen onay talepleri (ekle/düzenle/sil; can_cancel)
- `POST /api/attendance/pending/{request_id}/cancel` — Kendi bekleyen talebini iptal (modül-içi)
- Gerçek zamanlı: basış/düzenleme/silme sonrası `attendance_updated`; onay verilince `approval_status_changed` → panel canlı tazelenir (polling yok)
- Public sayfalar: `/devam/ekran` (kiosk), `/devam/kur` (kurulum), `/devam` (basış)
- Detaylı bilgi: `docs/modules/devam-takip.md`

### İnsan Kaynakları — Vardiyalar (Shift)
- `GET /api/hr/shifts` — Vardiya tanımları (süre + gece/split bilgisi dahil)
- `POST /api/hr/shifts` — Yeni vardiya (ad, renk, başlangıç/bitiş, split 2. segment, açıklama; onay akışına tabi)
- `PATCH /api/hr/shifts/{id}` — Vardiya güncelle
- `DELETE /api/hr/shifts/{id}` — Vardiya sil
- Model: `shift_definitions` (start_time/end_time, split için start_time2/end_time2; gece vardiyası end<=start). Frontend: `/dashboard/ik/vardiyalar`. İzin: `hr.shifts`. Onay executor: `_handle_shifts`.

### İnsan Kaynakları — Vardiya Çizelgesi (Rota)
- `GET /api/hr/shift-schedule?start&end&department` — Aralık rota: aktif vardiyalar + aktif personel + atamalar + departman listesi (tek çağrı, ≤45 gün)
- `POST /api/hr/shift-schedule` — Tek hücre ata (upsert; `(personnel_id, work_date)` benzersiz) — onay akışına tabi
- `DELETE /api/hr/shift-schedule/{id}` — Hücreyi sil (çıkar) — onay akışına tabi
- `POST /api/hr/shift-schedule/bulk` — Toplu ata/temizle (`shift_id=null` → sil; ≤2000 hücre) — onaydan muaf (toplu işlem)
- `POST /api/hr/shift-schedule/copy-week` — Kaynak haftayı hedef haftaya kopyala — onaydan muaf
- Model: `shift_assignments` (personnel_id+shift_id+work_date; unique (personnel_id, work_date); CASCADE). Frontend: `/dashboard/ik/vardiya-cizelgesi` (haftalık grid + fırça boyama). İzin: `hr.shift_schedule`. Onay executor: `_handle_shift_schedule`. WS: `shift_schedule_updated`. Detay: `docs/modules/vardiyalar.md` (Rota bölümü)

### Finans — Bankalar
- `GET /api/finance/banks/accounts/` — Banka hesap listesi
- `POST /api/finance/banks/accounts/` — Banka hesabı oluştur
- `PATCH /api/finance/banks/accounts/{id}` — Banka hesabı güncelle
- `DELETE /api/finance/banks/accounts/{id}` — Banka hesabı sil
- `POST /api/finance/banks/upload` — Ekstre yükleme (otomatik tanıma)
- `POST /api/finance/banks/accounts/{id}/upload` — Hesaba özel ekstre yükleme
- `POST /api/finance/banks/accounts/{id}/manual-transaction` — Ekstre-dışı (manuel) hareket ekle (`source='manual'`; işaretli tutar; bakiye=son+tutar). İlgili ekstre yüklenince o tarih aralığında **otomatik silinir** → çift kayıt olmaz. finance.banks use, audit'li, onaydan muaf (özel/düzeltme endpoint'i)
- `GET /api/finance/banks/accounts/{id}/transactions` — Hesap işlemleri (yanıt `source` alanı döner: statement/manual)
- `GET /api/finance/banks/accounts/{id}/statements` — Ekstre listesi
- Detaylı bilgi: `docs/modules/bankalar.md`

### Finans — Çekler
- `GET /api/finance/checks/` — Çek listesi (paginated, filtrelenebilir)
- `POST /api/finance/checks/upload` — Çek Excel yükleme
- `POST /api/finance/checks/sedna-import` — **Sedna (muhasebe SQL Server) verilen çek içe aktarma** (ters SSH tüneli; `AccCheckTrans`+`AccCheck` → **320 satıcı + 159 avans + 335 personel/ortak** verilen çekleri). Excel ile **aynı dedup** (check_no+vendor_code+currency+native tutar) → mükerrer olmaz. Durum Sedna pozisyonundan: Verilen Çek=bekliyor, Bankadan/Kasadan Ödeme=ödendi, Geri Al=iptal — eşleşmemiş çeklerde **durum + vade senkronize edilir**. **Tutar-kayması heal:** aynı (no,cari,vade) UNIQUE'inde tutarı bozuk eşleşmemiş kayıt Sedna'ya hizalanır (eşleşmişe dokunulmaz). finance.checks use, audit'li, onaydan muaf
- `GET /api/finance/checks/sedna-status` — Sedna çek içe aktarma etkin mi (`{configured}`; buton gösterimi)
- `GET /api/finance/checks/uploads` — Yükleme geçmişi
- `DELETE /api/finance/checks/uploads/{id}` — Yükleme sil
- `PATCH /api/finance/checks/{id}/status` — Çek durumu güncelle
- `GET /api/finance/checks/summary` — Çek özeti
- `POST /api/finance/checks/match-bank` — Otomatik banka eşleştirme
- Detaylı bilgi: `docs/modules/cekler.md`

### Finans — Krediler
- `GET/POST /api/finance/krediler/` — Kredi ürünü listele/oluştur
- `GET/PATCH/DELETE /api/finance/krediler/{id}` — Kredi ürünü detay/güncelle/sil
- `POST /api/finance/krediler/{id}/payments` — Ödeme planı ekle (toplu)
- `PATCH /api/finance/krediler/payments/{id}` — Ödeme güncelle
- `DELETE /api/finance/krediler/payments/{id}` — Ödeme sil
- `POST /api/finance/krediler/{id}/close` — Krediyi kapat (erken tahsil; ödenmemiş taksitler nakit akımdan çıkar)
- `POST /api/finance/krediler/{id}/reopen` — Kapalı krediyi yeniden aç (geri al)
- `GET /api/finance/krediler/summary/by-type` — Tip bazlı kredi özeti
- `GET /api/finance/krediler/upcoming-payments` — Yaklaşan ödemeler
- `GET /api/finance/krediler/{id}/kmh-status` — KMH için anlık adat/faiz/projeksiyon (sadece type='kmh')
- `GET /api/finance/krediler/export/pdf` — Kredi PDF raporu (açılış + vade tarihleri dahil; tip/durum/arama filtreli; landscape A4, para-birimi-bazında toplam; EUR kredileri mavi vurgulu; ₺ sembolü DejaVuSans ile düzgün render)
- Detaylı bilgi: `docs/modules/krediler.md`

### Finans — Avanslar
- `GET/POST/PATCH/DELETE /api/finance/avanslar/` — Avans CRUD (elle/planlama; beklenen avanslar)
- `GET /api/finance/avanslar/summary` — Avans özeti
- `GET /api/finance/avanslar/sedna-reconciliation` — **Manuel avans ↔ Sedna mutabakatı**. Acente avansları Sedna'da **340 "Alınan Sipariş Avansları"** hesabındadır (159=bizim verdiğimiz; 320/120 ile karıştırma). Manuel acente adı ↔ Sedna 340 adı **token eşleştirmeli** kıyaslanır: manuel alınan vs Sedna alınan + kalan avans + fark + Sedna'da olup manuelde olmayan avanslar. Canlı 340 çekilir (tünel kapalıysa 503). Frontend: avanslar sayfasında "Sedna Mutabakatı" butonu. İlk canlı: Alltours manuel 4,75M € = Sedna 340 4,75M € (birebir)
- Detaylı bilgi: `docs/modules/avanslar.md`

### Finans — Döviz
- `GET /api/finance/exchange-rates/latest` — Güncel kurlar
- `GET /api/finance/exchange-rates/history` — Kur geçmişi
- Detaylı bilgi: `docs/modules/doviz.md`

### Finans — Bütçe
- `GET/POST/PATCH/DELETE /api/finance/butce/kategoriler` — Bütçe kategorisi CRUD
- `GET /api/finance/butce/` — Bütçe kayıtları (yıl zorunlu)
- `POST /api/finance/butce/` — Bütçe kaydı oluştur/güncelle (upsert)
- `POST /api/finance/butce/bulk` — Toplu bütçe kaydı
- `DELETE /api/finance/butce/{id}` — Bütçe kaydı sil
- `GET /api/finance/butce/summary` — Yıllık bütçe özeti
- `GET /api/finance/butce/monthly-summary` — Aylık bütçe özeti
- Detaylı bilgi: `docs/modules/butce.md`

### Finans — Departmanlar
- `GET/POST/PATCH/DELETE /api/finance/departmanlar/` — Departman CRUD

### Kalite Yönetimi
- `GET/POST/PATCH/DELETE /api/quality/templates/` — Kalite şablonu CRUD
- `GET/POST /api/quality/forms/` — Kalite formu listele/oluştur
- `PATCH /api/quality/forms/{id}` — Form güncelle
- `POST /api/quality/forms/{id}/fill` — Form doldur
- `POST /api/quality/forms/{id}/submit` — Form gönder
- `POST /api/quality/forms/{id}/review` — Form onayla/reddet

### Diğer
- `GET /api/health` — Sağlık kontrolü
- `WS /api/ws?token=JWT` — WebSocket bağlantısı
- `GET /api/push/vapid-key` — VAPID public key
- `POST /api/push/subscribe` — Push aboneliği
- `DELETE /api/push/unsubscribe` — Push abonelik iptali
- `GET /api/uploads/{path}` — Dosya sunma (auth gerekli)
- `GET /api/notifications/` — Bildirim listesi
- `PATCH /api/notifications/{id}/read` — Bildirimi okundu işaretle
- `GET /api/system/error-logs/` — Hata logları
- `GET /api/system/server/info` — Sunucu durumu (CPU/RAM/disk/servisler/DB boyutu)
- `POST /api/system/server/services/{name}/restart` — Servisi yeniden başlat (whitelist + sudo NOPASSWD)
- `GET /api/system/server/services/{name}/logs?lines=N` — Servis journalctl logu (son N satır)
- `GET /api/system/backup/status` — Git/GitHub yedek durumu (son commit, bekleyen değişiklik, senkron, geçmiş)
- `POST /api/system/backup/run` — Manuel yedek (commit + GitHub push)
- `POST /api/system/backup/restore` — Seçilen commit'e güvenli geri yükleme (ileri-commit, force-push yok). Detay: `docs/modules/yedekleme.md`

### Satış — Otel Rezervasyon
- `POST /api/sales/reservations/upload` — Crystal Reports XLS/XLSX yükleme (RecId bazlı upsert). Response'a `removal_candidates: RemovalCandidate[]` eklenir — yüklemenin check-in + record-date kapsamı içinde olup dosyada bulunmayan kayıtlar (olası iptaller)
- `GET /api/sales/reservations/uploads` — Yükleme geçmişi
- `DELETE /api/sales/reservations/uploads/{id}` — Yüklemeyi sil (rezervasyon satırları korunur, FK SET NULL)
- `POST /api/sales/reservations/bulk-delete` — `removal_candidates` listesinden seçilen ID'leri toplu sil (max 5000, audit loglu)
- `POST /api/sales/reservations/sedna-import` — **SednaPrenses önbüro/PMS DB'sinden canlı rezervasyon senkronu** (XLS'siz doluluk). `Reservation` join `Agency`; `RecId` aynı ID uzayı → mükerrer yapmaz. Pencere=cari yıl+; aktif (Status≠−1) upsert, iptal/silinmiş süpürülür → tablo Sedna aktif rezervasyonlarının aynası (`occupancy_metrics` aktif-yalnız değişmezliği). Merkezi Sedna sync'in adımı. sales.hotel_reservation use, audit'li, onaydan muaf. Detay: `docs/modules/otel-rezervasyon.md`
- `GET /api/sales/reservations/sedna-status` — Sedna rezervasyon senkronu etkin mi (`{configured}`)
- `GET /api/sales/reservations/` — Paginated liste (start_date, end_date, agency, nation, room_type, rez_status, search)
- `GET /api/sales/reservations/summary` — Dashboard KPI + dağılımlar + **doluluk metrikleri** (total_capacity, occupancy_pct, aylık/tip başına doluluk)
- `GET /api/sales/reservations/daily-occupancy?month=YYYY-MM` — Aylık drill-down: günlük doluluk + check-in/out sayıları (takvim heatmap için)
- Detaylı bilgi: `docs/modules/otel-rezervasyon.md`

### Satış — Günlük Hareketler (gelen rezervasyon / iptal akışı)
- `GET /api/sales/daily-activity/summary?start_date&end_date` — **Gün gün gelen rezervasyon + iptal özeti** (adet/gece/misafir/EUR ciro, net, `cancel_rate`; hareketsiz günler 0'larla, en yeni üstte; ≤92 gün). **Sedna canlı** (Mizan/Fiş İcmali kalıbı): yerel tabloda iptal tarihçesi yoktur (senkron iptalleri siler) — `RecordDate` ekseni=gelen, `CancelDate` ekseni=iptal. 60sn TTL cache. sales.daily_reservations view
- `GET /api/sales/daily-activity/details?activity_date&type=new|cancelled` — **Drill-down:** günün rezervasyon satırları (voucher/acente/ülke/oda/konaklama/pax/EUR; gelenlerde sonradan-iptal `is_cancelled` rozeti, iptallerde kayıt tarihi). **Misafir adı bilinçli yer almaz** (kişisel veri — Sedna sorgusu `Guests` kolonunu çekmez)
- `GET /api/sales/daily-activity/status` — Sedna etkin mi (`{configured}`); tünel kapalı→503
- Salt-okunur (yalnız GET) → onay akışı kapsam dışı. Detaylı bilgi: `docs/modules/gunluk-hareketler.md`

### Satış — Oda Tipleri
- `GET /api/sales/room-types/` — Oda tipi listesi + toplam kapasite (`total_capacity`)
- `GET /api/sales/room-types/{id}` — Tek kayıt
- `POST /api/sales/room-types/` — Yeni oda tipi
- `PATCH /api/sales/room-types/{id}` — Güncelle
- `DELETE /api/sales/room-types/{id}` — Sil (bağlı rezervasyon varsa engellenir; pasif yapma önerilir)
- Detaylı bilgi: `docs/modules/oda-tipleri.md`

### Satış — Acente Grupları
- `GET /api/sales/agency-groups/` — Grup listesi (üye acenteler dahil)
- `POST /api/sales/agency-groups/` — Yeni grup
- `PATCH /api/sales/agency-groups/{id}` — Grup adı / üyeleri güncelle
- `DELETE /api/sales/agency-groups/{id}` — Grubu sil
- `POST /api/sales/agency-groups/assign` — Atomik atama (acente ↔ grup) — drag-drop için
- Detaylı bilgi: `docs/modules/otel-rezervasyon.md` (acente gruplama bölümü)

### Finans — Banka Talimatları (PDF üretim)
- `POST /api/finance/bank-instructions/transfer` — EFT/Havale/Transfer PDF'i (kaynak/hedef hesap + tutar)
- `POST /api/finance/bank-instructions/currency-exchange` — Döviz bozma talimatı PDF'i
- `GET /api/finance/bank-instructions/accounts` — Aktif banka hesapları (PDF formunda dropdown için)
- Detaylı: `backend/app/routers/finance/CLAUDE.md` (Banka Talimatları bölümü)

### Finans — Etiketleme ve Kategoriler
- `GET /api/finance/tags/categories` — Kategori listesi (etiket havuzu)
- `POST /api/finance/tags/categories` — Yeni kategori
- `GET /api/finance/tags/payment-methods` — Standart ödeme yöntemleri haritası
- `GET /api/finance/tags/untagged-count` — Etiketlenmemiş işlem sayısı (badge)
- `PATCH /api/finance/tags/transactions/{tx_id}` — Tek işlemi etiketle (banka/cari/kategori)
- `POST /api/finance/tags/transactions/bulk` — Toplu etiketleme
- `POST /api/finance/tags/auto-tag` — Otomatik etiketleme (geçmiş eşleşmelere göre)
- `POST /api/finance/tags/auto-match-vendors` — Açıklamadan cari eşleştirme önerisi
- Detaylı: `docs/modules/transaction-tags.md`

### Sistem — Onay Akışı (Workflow Yönetimi)
- `GET /api/system/approval/modules-with-roles` — Onay tanımlanabilir modüller + roller
- `GET /api/system/approval/workflows` — Tüm workflow'lar
- `GET /api/system/approval/workflows/{id}` — Tek workflow
- `POST /api/system/approval/workflows` — Yeni workflow (modül + requestor rolleri + approver rolleri + adımlar)
- `PATCH /api/system/approval/workflows/{id}` — Workflow güncelle
- `DELETE /api/system/approval/workflows/{id}` — Workflow sil
- `GET /api/system/approval/requests/pending` — Onayım bekleyen talepler
- `GET /api/system/approval/requests/pending/count` — Bekleyen sayı (badge)
- `GET /api/system/approval/requests/my-submissions` — Kendi taleplerim
- `GET /api/system/approval/requests/history` — Onay geçmişi
- `GET /api/system/approval/requests/{id}` — Tek talep detayı
- `POST /api/system/approval/requests/{id}/approve` — Onayla
- `POST /api/system/approval/requests/{id}/reject` — Reddet
- `POST /api/system/approval/requests/{id}/return` — İade et
- `POST /api/system/approval/requests/{id}/cancel` — Kendi talebimi iptal
- `POST /api/system/approval/requests/{id}/resubmit` — İade edilenı tekrar gönder
- `POST /api/system/approval/trigger` — Internal: modüllerin `check_approval()` tetiklediği endpoint
- `POST /api/system/approval/status/bulk` — Toplu durum sorgu
- `GET /api/system/approval/status/{entity_type}/{entity_id}` — Tek kaydın onay durumu

### Satış — Uçak Rezervasyon
- **Yaklaşım:** Travelpayouts/Aviasales **JS Widget** embed (REST API yerine)
- **Sayfa:** `frontend/src/routes/dashboard/satis/ucak-rezervasyon/+page.svelte` — Aviasales arama form widget'ını host eder
- **Widget URL:** `https://tp.media/content?shmarker=722928&promo_id=7879&campaign_id=100&locale=tr&currency=try&...&color_button=%230d9488` (teal tema, TR locale, TRY currency)
- **Affiliate marker:** 722928 (Travelpayouts) — komisyon takibi widget içinde otomatik
- **Veri kalitesi:** Aviasales'in tam arama motoru — Skyscanner kalitesinde 20-30+ uçuş, gerçek zamanlı fiyatlar
- **Backend client'ı (`utils/travelpayouts_client.py`) ve `routers/sales/flights.py` yedekte korunur** — gelecekte API tabanlı yaklaşıma dönmek istersek hazır
- **Neden API değil widget:** Travelpayouts Flight Search API v1 50.000 MAU şartı koyar (otel sitesi için ulaşılmaz), v3 `prices_for_dates` tek yönde rota başına 1 sonuç döner (yetersiz). Widget her iki sorunu çözer — sınırsız arama + gerçek veri + sıfır maliyet.
- **TURSAB gerekmez:** Widget bilet satmıyor, sadece arama gösteriyor; tıklayan misafir Aviasales'te satın alıyor (biz affiliate)
- Detaylı bilgi: `docs/modules/ucak-rezervasyon.md`

## Veritabanı

- **DB adı:** sprenses
- **Kullanıcı:** sprenses
- **Tablolar (63):** stock_depots, stock_products, stock_movements, personnel, attendance_logs, attendance_settings, shift_definitions, shift_assignments, users, roles, modules, role_module_permissions, conversations, conversation_members, messages, audit_logs, push_subscriptions, notifications, error_logs, vendors, vendor_uploads, vendor_transactions, vendor_bank_accounts, sales_invoices, sales_collections, sales_advances, transaction_categories, bank_accounts, bank_statements, bank_transactions, checks, check_uploads, credit_products, credit_payments, credit_card_statements, credit_card_transactions, advances, departments, budgets, budget_categories, finance_events, scheduled_definitions, scheduled_entries, exchange_rates, cash_flows, quality_templates, quality_template_sections, quality_template_fields, quality_template_assignees, quality_forms, quality_form_values, reservations, reservation_uploads, room_types, agency_groups, approval_workflows, approval_workflow_requestor_roles, approval_workflow_approver_roles, approval_workflow_steps, approval_requests, approval_request_logs, payment_instruction_lists, payment_instruction_items
- **Saat dilimi:** Europe/Istanbul (her bağlantıda SET edilir)
- **Migrations:** `cd backend && source venv/bin/activate && alembic upgrade head`

## RBAC Sistemi

| Tablo | Açıklama |
|---|---|
| **roles** | Roller (Admin, Personel vb.) |
| **modules** | Modüller — hiyerarşik (parent_id), code alanı unique |
| **role_module_permissions** | Rol-modül izin matrisi: can_view, can_use |

**Mevcut modüller:**
- Panel (dashboard)
- Mesajlaşma (messaging)
- Finans (finance) → Nakit Akım (finance.cash_flow), Cariler (finance.cariler), Satış Faturaları (finance.sales_invoices), Bankalar (finance.banks), Çekler (finance.checks), Krediler (finance.krediler), Avanslar (finance.avanslar), Döviz (finance.doviz), Bütçe (finance.butce), Onay (finance.onay)
- Muhasebe (accounting) → Vergiler (accounting.taxes), Düzenli Ödemeler (accounting.recurring), Alınan Kiralar (accounting.rent_income), Verilen Kiralar (accounting.rent_expense), Temettü (accounting.dividend), Kullanıcı Fiş İcmali (accounting.fis_icmali), Mizan (accounting.mizan)
- İnsan Kaynakları (hr) → Maaş (hr.salary), Stopaj (hr.withholding), SGK (hr.sgk), Devam Takip (hr.attendance), Vardiyalar (hr.shifts), Vardiya Çizelgesi (hr.shift_schedule)
- Kalite (quality) → Şablonlar (quality.templates), Formlar (quality.forms)
- Sistem (system) → Kullanıcılar (system.users), Roller (system.roles), Modüller (system.modules), Audit Loglar (system.audit_logs), Hata Logları (system.error_logs), Onay Akışı (system.approval), Sunucu (system.server), Yedekleme (system.backup)
- Satış (sales) → Uçak Rezervasyon (sales.flight), Otel Rezervasyon (sales.hotel_reservation), Günlük Hareketler (sales.daily_reservations), Oda Tipleri (sales.room_types)
- Stok (stok) → Maliyet Kontrol (stok.maliyet — operasyonel KPI), Ürünler & Stok (stok.urunler), Hareketler (stok.hareketler), Depolar (stok.depolar)
- Yönetim Paneli (yonetim) → Panel (yonetim.panel — GM/Finans 10 KPI + uyarılar)

## Giriş Bilgileri

- **E-posta:** admin@sprenses.com
- **Şifre:** admin123

## Ortam Değişkenleri (.env)

| Değişken | Açıklama |
|---|---|
| `DATABASE_URL` | PostgreSQL bağlantı URL'si |
| `SECRET_KEY` | JWT imzalama anahtarı (güçlü olmalı!) |
| `ALGORITHM` | JWT algoritması (HS256) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token süresi (dakika) |
| `VAPID_PRIVATE_KEY` | Push bildirim özel anahtarı |
| `VAPID_PUBLIC_KEY` | Push bildirim genel anahtarı |
| `VAPID_MAILTO` | Push bildirim e-posta |
| `CORS_ORIGINS` | İzin verilen origin'ler (virgülle ayrılmış) |
| `TRAVELPAYOUTS_TOKEN` | Travelpayouts (Aviasales) affiliate API token — uçak rezervasyon arama için (opsiyonel, yoksa mock veri) |
| `TRAVELPAYOUTS_MARKER` | Travelpayouts affiliate partner ID (komisyon takibi için, opsiyonel) |
| `SEDNA_PASSWORD` | Sedna SQL Server (muhasebe) cari içe aktarma şifresi — boşsa özellik kapalı. Host/port/db/user/charset/prefix `config.py`'de varsayılan (tünel `127.0.0.1:11433`, db `SednaPrensesMhs2026`, user `prenses\btadmin`, charset `CP1254`, prefix `320`) |

## Nginx Konfigürasyonu

- `/etc/nginx/conf.d/sprenses.conf` — Site konfigürasyonu
- `/etc/nginx/conf.d/sprenses.conf.bak` — Yedek

## Mesajlaşma Sistemi

- **Rota:** `/dashboard/mesajlasma`
- **Modül kodu:** `messaging`
- **Tür:** Özel (private) ve grup konuşmaları
- **Gerçek zamanlılık:** WebSocket event-driven (polling yasak)
- **Mesaj düzenleme:** Sadece gönderen düzenleyebilir (`is_edited`, `edited_at`)
- **Mesaj silme:** Soft delete (`is_deleted` = true, "Bu mesaj silindi" gösterilir, içerik korunur)
- **Okundu bilgisi:** `ConversationMember.last_read_at` ile tek/çift tik gösterimi
- **Okunmamış sayısı:** Sidebar'da badge olarak gösterilir (tek SQL sorgusu ile)
- **Push notification:** VAPID destekli web push bildirimleri
- **PWA:** Service worker + manifest.json mevcut (`frontend/static/manifest.json`)

## Audit Log Sistemi

- **Tablo:** `audit_logs`
- **Kaydedilen eylemler:** login, register, change_password, reset_password, create, update, delete
- **Alanlar:** user_id, action, entity_type, entity_id, details, ip_address, created_at
- **API:** `GET /api/system/audit-logs/` (paginated, action/entity_type/user_id filtresi)
- **Kullanım:** `log_action(db, user_id, action, entity_type, entity_id, details, ip_address)`

## Test Sistemi

### Backend (pytest)
```bash
# DATABASE_URL TEST DB'sine işaret etmeli — adı '_test' içermeli (örn: sprenses_test)
cd backend && source venv/bin/activate
export DATABASE_URL=postgresql://sprenses:PASS@127.0.0.1:5432/sprenses_test
python -m pytest tests/ -v

# Coverage raporu (pytest-cov):
python -m pytest tests/ --cov=app --cov-report=term --cov-report=html
# → htmlcov/index.html — dosya bazlı satır kapsamı
```

**Test DB kurulumu (ilk kullanım):**
```bash
sudo -u postgres psql -c "CREATE DATABASE sprenses_test OWNER sprenses;"
PGPASSWORD=PASS pg_dump -h 127.0.0.1 -U sprenses --schema-only sprenses \
  | PGPASSWORD=PASS psql -h 127.0.0.1 -U sprenses -d sprenses_test
PGPASSWORD=PASS pg_dump -h 127.0.0.1 -U sprenses --data-only \
  --table=users --table=roles --table=modules --table=role_module_permissions \
  --table=departments --table=transaction_categories sprenses \
  | PGPASSWORD=PASS psql -h 127.0.0.1 -U sprenses -d sprenses_test
```

**Test altyapı notları:**
- Token çıkarma: `conftest.py` içindeki `extract_token(response)` helper'ı HttpOnly cookie'den token alır
- Test ortamında `CORS_ORIGINS=http://testserver` set edilir → `secure=False` cookie → TestClient cookie geri döner
- `integration_quality.py` — Production API'ye karşı çalışan entegrasyon scripti (pytest tarafından toplanmaz)
- Rate limiter'lar her test öncesi otomatik sıfırlanır (`autouse` fixture)
- **Test DB izolasyonu zorunlu:** `conftest.py` `DATABASE_URL` set edilmemişse veya adı `_test` içermiyorsa testleri durdurur. Bilerek prod-benzeri DB kullanılacaksa `ALLOW_PROD_DB_TESTS=1` ile bypass edilir (önerilmez).
- **Onay akışı sigortası:** `_disable_admin_approval_workflows` autouse fixture'ı her test başında admin rolünün requestor olduğu aktif workflow'ları SAVEPOINT içinde deaktive eder — CRUD testlerinin onay akışı yüzünden sessizce 202'ye düşmesini engeller. Onay akışını test edenler kendi workflow'larını yarattığı için etkilenmez.
- **Non-admin test fixture'ları:** `viewer_user_headers` (sadece `can_view`), `use_user_headers` (`can_view+can_use`), `no_perm_user_headers` (hiç izin yok), `make_user_with_perms({module: {view, use}})` factory — admin-dışı izin matrisi davranışını test etmek için. Her fixture yeni `Role` + `User` oluşturup login ederek auth header döner; test bitince SAVEPOINT rollback'i ile temizlenir.
- **pg_hba.conf:** `sprenses_test` DB için ayrı bir `host ... md5` satırı `/var/lib/pgsql/data/pg_hba.conf`'ta tanımlıdır (yoksa ident auth'a düşer, fail eder).

### Frontend (Vitest)
```bash
cd frontend && npx vitest run
```

**Test dosyaları (267 test, 21 dosya):**
- `src/lib/api.test.ts` — API wrapper (GET/POST/PATCH/DELETE, upload, hata yönetimi, 401/403, signal, fetchRaw) (22 test)
- `src/lib/utils/finance.test.ts` — formatCurrency, formatCompact, groupByMonth, getTodayKeys, transfer hariç tutma (23 test)
- `src/lib/utils/paymentMethods.test.ts` — PAYMENT_METHODS, SELECTABLE, CATEGORIES, getPaymentMethod fallback (16 test)
- `src/lib/utils/colorMap.test.ts` — categoryColorMap, filterColorMap, availableColors, getColor fallback (16 test)
- `src/lib/utils/validation.test.ts` — validateEmail, validatePassword, validateRequired, validateModuleCode (12 test)
- `src/lib/utils/push.test.ts` — isPushSupported, getPushPermissionState (6 test)
- `src/lib/constants/finance.test.ts` — Kaynak tipleri, ödeme yöntemleri, kredi tipleri, para birimleri, sabit tutarlılığı (15 test)
- `src/lib/stores/auth.test.ts` — setAuth, loadAuth, hasPermission (izin matrisi) (15 test)
- `src/lib/stores/toast.test.ts` — showToast, removeToast, otomatik kaldırma (12 test)
- `src/lib/stores/notification.test.ts` — setMutedConversations, updateMutedConversation, isConversationMuted, toggleSound (11 test)
- `src/lib/stores/ui.test.ts` — sidebar state, toggleSidebar, closeSidebar (6 test)

## Modül Bazlı Dokümantasyon

Her modülün kendi CLAUDE.md dosyası `docs/modules/` altında bulunur. **Yeni modül eklerken bu klasöre modül dokümantasyonu oluşturulmalıdır.**

> **Yeni modül eklerken — frontend zorunluluğu:** Sayfalar tasarım sistemine uymalıdır (Button/PageHeader/StatCard/StatusBadge/ConfirmDialog/EmptyState/MoneyInput/Pagination — elle `bg-teal-*` buton yazma, AA kontrast). Referans sayfa: `finans/avanslar` veya `sistem/kullanicilar`. Kurallar: **[UI Tasarım Kuralları → Yeni Modül/Sayfa Eklerken — Zorunlu](#ui-tasarım-kuralları)** ve `docs/ui-kurallari.md`. Backend tarafı için ayrıca: izin sistemi (`require_permission`), onay akışı (`check_approval` + executor handler), audit log.

### Modül Dokümantasyon Şablonu
Her modül dosyası şu bölümleri içermelidir:
1. **Genel Bilgi** — Modül kodu, üst modül, frontend rota, backend prefix, izin kodu
2. **Dosya Haritası** — Backend (model, schema, router) ve Frontend (sayfa, bileşen) dosyaları
3. **Veritabanı Şeması** — Tablo yapısı, kolonlar, indeksler
4. **API Endpoint'leri** — Method, path, izin seviyesi, açıklama
5. **Frontend UI Yapısı** — Tasarım sistemi bileşenleri (Button/PageHeader/StatCard… — referans: avanslar/kullanicilar, detay `docs/ui-kurallari.md`), state yönetimi, renk şeması
6. **Audit Log Entegrasyonu** — entity_type, kaydedilen eylemler
7. **Geliştirme Kuralları** — Modüle özel iş kuralları ve kısıtlamalar

### Mevcut Modül Dokümantasyonları
| Modül | Dosya |
|---|---|
| Finans Mimarisi | `docs/modules/finans-mimarisi.md` |
| Nakit Akım | `docs/modules/nakit-akim.md` |
| Bankalar | `docs/modules/bankalar.md` |
| Cariler | `docs/modules/cariler.md` |
| Çekler | `docs/modules/cekler.md` |
| Krediler | `docs/modules/krediler.md` |
| Avanslar | `docs/modules/avanslar.md` |
| Döviz | `docs/modules/doviz.md` |
| Bütçe | `docs/modules/butce.md` |
| Onay | `docs/modules/onay.md` |
| İşlem Etiketleme | `docs/modules/transaction-tags.md` |
| Muhasebe & İK | `docs/modules/muhasebe-ik.md` |
| Kullanıcı Fiş İcmali | `docs/modules/fis-icmali.md` |
| Mizan (Geçici Mizan) | `docs/modules/mizan.md` |
| Kimlik Doğrulama | `docs/modules/auth.md` |
| Sistem — Kullanıcılar | `docs/modules/sistem-kullanicilar.md` |
| Sistem — Roller | `docs/modules/sistem-roller.md` |
| Sistem — Modüller | `docs/modules/sistem-moduller.md` |
| Sistem — Audit Log | `docs/modules/audit-log.md` |
| Sistem — Hata Logları | `docs/modules/hata-loglari.md` |
| Mesajlaşma | `docs/modules/mesajlasma.md` |
| Bildirimler | `docs/modules/bildirimler.md` |
| Push Bildirim | `docs/modules/push-bildirim.md` |
| WebSocket Altyapısı | `docs/modules/websocket.md` |
| Uçak Rezervasyon | `docs/modules/ucak-rezervasyon.md` |
| Otel Rezervasyon | `docs/modules/otel-rezervasyon.md` |
| Günlük Hareketler (rezervasyon/iptal) | `docs/modules/gunluk-hareketler.md` |
| Oda Tipleri | `docs/modules/oda-tipleri.md` |
| Yedekleme | `docs/modules/yedekleme.md` |
| Devam Takip (PDKS) | `docs/modules/devam-takip.md` |
| Vardiyalar (Shift) | `docs/modules/vardiyalar.md` |
| Satış Faturaları | `docs/modules/satis-faturalari.md` |
| Stok / Depo Maliyet | `docs/modules/stok.md` |
| Yönetim Paneli + Maliyet Kontrol | `docs/modules/yonetim-paneli.md` |
| SSH Tünel Güvenliği | `docs/modules/ssh-tunel-guvenligi.md` |

## UI Tasarım Kuralları

**Tüm UI tutarlılık spec'i → [`docs/ui-kurallari.md`](docs/ui-kurallari.md)** (sayfa iskeleti, paylaşılan bileşen API'leri, renk kodları, faz planı)

### Yeni Modül/Sayfa Eklerken — Zorunlu

Yeni veya yeniden tasarlanan **her frontend sayfası** tasarım sistemini kullanır. Referans (kanonik uygulamalar): **`finans/avanslar`** ve **`sistem/kullanicilar`** — yeni sayfa yazmadan önce bunlardan birini örnek al.

- **Butonlar:** `Button.svelte` kullanılır (`variant`: primary/secondary/danger/ghost; `size`, `loading`, `fullWidth`). Elle `bg-teal-* ... rounded-lg` buton **yazma** — AA kontrast (teal-700, 5.5:1) ve tutarlılık tek kaynaktan gelir. Layout için `class` prop'u **yalnızca** genişlik/boşluk içindir (renk/stil variant'tan gelir).
  - Birincil aksiyon `<Button>` (primary), düzenle `variant="secondary"` + `<Pencil>`, sil `variant="danger"` + `<Trash2>`, modal İptal `variant="secondary"`.
  - **İstisnalar (bilerek):** yoğun tablo satır-aksiyonları ikon-only kalabilir; sıkı mini-chip kümeleri / sekme / ısı-haritası hücresi buton değildir — bunlar Button'a alınmaz, gerekiyorsa sadece teal-700'e çekilir (AA).
- **Sayfa başlığı:** `PageHeader.svelte` (`<h1>` + açıklama + `{#snippet actions()}`). Her sayfada in-page başlık zorunlu (sadece Topbar başlığı yetmez).
- **Diğer zorunlu bileşenler:** `StatCard`, `StatusBadge`, `ConfirmDialog` (native `confirm()` **yasak**), `EmptyState`, `MoneyInput` (tüm para girişleri), `FileDropzone` (yükleme), `Pagination`, `Modal`.
- **Liste sayfası iskeleti:** Yeni liste/CRUD sayfaları `ListPage.svelte` ile kurulur (PageHeader → Stat kartları → Filtre barı → İçerik[loading/empty/children] → Pagination tek yerde). Sayfa yalnızca içeriğini (tablo, modallar) snippet verir. Referans migrasyon: `sistem/audit-loglar`. Detay: `docs/modulerlik-iyilestirmeleri.md`
- **Sidebar + route guard tek konfigten:** Menü yapısı ve "rota → gerekli modül izni" haritası `lib/config/navigation.ts` (`NAV_GROUPS` + `requiredModuleForPath`) içindedir. Yeni sayfa eklerken **buraya bir `NavItem` ekle** → sidebar linki + route koruması (`+layout.svelte` guard'ı) otomatik gelir. Sidebar bu konfigi loop ile render eder (elle link bloğu yazma). Backend `require_permission` asıl kapıdır; guard derinlemesine savunmadır.
- **İkonlar:** **Lucide** (`lucide-svelte`) — emoji/inline SVG yasak.
- **Kontrast:** Tüm metin/buton WCAG AA (≥4.5:1). teal **600 değil 700** (beyaz üzerinde 600 ≈ 3.8:1 → AA-fail).
- Bileşen API'leri + detay: `docs/ui-kurallari.md`.

### Modüller Arası Tutarlılık Standardı (Tasarımcı Denetimi — 2026-06-02, güncelleme 2026-06-09)

Tasarımcı denetimi tüm modüllerin **birbiriyle aynı iskelet, aynı bileşen, aynı sırada** olmasını şart koşar. Yeni modüller de bu standarda uyar. **Kanonik sayfa anatomisi (liste/CRUD sayfası), yukarıdan aşağıya değişmez sıra:**

```
1. PageHeader      → <h1> (SOL hizalı) + açıklama + actions snippet (birincil "+ Yeni X" butonu BURADA)
2. Stat Cards      → StatCard bileşeni (yatay grid), başlığın hemen altında
3. Filtre barı     → sol: arama (debounce 300ms + ✕) · orta: durum/dönem dropdown/chip · sağ: kayıt sayısı + export
4. Ana içerik      → tablo / kart listesi / accordion (loading=Skeleton, boş=EmptyState+CTA)
5. Pagination      → altta (varsa)
6. Modal'lar       → dosya sonunda
```

**Tek-standart kuralları (denetimde bulunan sapmaları kapatır):**

| Konu | TEK standart | Sapma yazma |
|---|---|---|
| **Özet kart** | **`StatCard` bileşeni** (ikon accent + label + value + hint). Tüm sayfalar aynı. | Renkli-tinted kart, ikonsuz beyaz kart, inline custom kart **yok** (nakit-akım/cariler/döviz/dashboard/ScheduledModule hepsi StatCard'a hizalanmalı) |
| **Sayfa başlığı** | **`PageHeader`** her sayfada — **sol hizalı**, üstte. Sadece Topbar başlığı **yetmez**. | Başlıksız sayfa **yok** (bankalar, nakit-akım eksik); ortalanmış/fazla-padding'li başlık **yok** (audit-loglar); ham `<h1>` yerine PageHeader |
| **Birincil aksiyon** | PageHeader `actions` snippet'inde (başlık yanında, sağ) | Filtre barına / section header'a gömme **yok** (ScheduledModule, bankalar) |
| **İskelet sırası** | StatCards **filtreden önce** (yukarıdaki sıra) | ScheduledModule'deki "filtre→StatCards" sırası standarda çekilmeli |
| **Boş durum** | `EmptyState` (ikon + mesaj + CTA buton) | Düz "Henüz X yok" metni yerine bileşen |
| **Loading** | Skeleton (`TableSkeleton`/`FormSkeleton`) | Spinner / "Yükleniyor..." metni **yok** |
| **Tehlikeli aksiyon** | `Button variant="danger"` (dolu kırmızı) veya `ConfirmDialog` | Ham kırmızı-outline buton **yok** (hata-loglar "Tümünü Temizle") |
| **Para değeri** | `tabular-nums` + taşmaya karşı yeterli kolon/kart genişliği; uzun TRY tutarı kırpılmaz | Sabit dar stat kartında uzun tutar taşması **yok** (cariler) |
| **Silme/onay diyaloğu** | `ConfirmDialog.svelte` | Native `confirm()` **kesinlikle yok** (bütçe:286, otel-rezervasyon:460'ta yakalandı) |
| **Focus ring** | `focus:ring-teal-500` (tüm input/select/checkbox; checkbox `accent-teal-700`) | `focus:ring-blue-*` / `focus:ring-cyan-*` **yok** (bankalar, bütçe'de yakalandı) |
| **İkincil metin / hint** | En açık ton **`text-gray-500`**; tablo başlığı `text-gray-600` | `text-gray-400`/`text-gray-300` gövde metni **yok** (AA-fail; maliyet, yönetim, mizan'da yakalandı) |
| **Teal tonu** | Dolu zemin + beyaz metin = **teal-700** (Button.svelte tek kaynak) | `bg-teal-600` inline buton/sayfa göstergesi **yok** (EmptyState/Pagination/FileDropzone/MessageInput dahil paylaşılan bileşenlerde bile yakalandı — bileşen içinde de teal-700) |
| **Sayısal oran/yüzde girişi** | Para → `MoneyInput`; oran/yüzde (faiz, BSMV, komisyon) → MoneyInput `decimals` ile veya TR-formatlı kontrollü input | `<input type="number" step="0.01">` ile ondalık/para girişi **yok** (krediler, cariler'de yakalandı) |
| **Inline spinner** | Veri yükleme = `TableSkeleton`/`FormSkeleton`; buton-içi bekleme = `Button loading` (Loader2) | Elle `animate-spin` div/SVG + "Yükleniyor..." **yok** (nakit-akım, cariler, krediler, çekler, onay-akışı, devam-takip'te yakalandı) |
| **Sessiz hata** | Her `catch` → `console.error` + `showToast('... yüklenemedi', 'error')` | `.catch(() => {})` **yok** (dashboard panelinde 6 adet yakalandı); yalnız-`console.error` da yetmez — kullanıcıya toast |
| **Form hata gösterimi** | `fieldErrors: Record<string,string>` + `aria-invalid`/`aria-describedby` (referans: avanslar) | Tek `formError` string'iyle alan hatası gömme **yok** (devam-takip, vardiyalar) |

**Sapma envanteri (2026-06-09 denetimi): 12 maddenin TAMAMI aynı gün kapatıldı.** Yeni sayfa bu listeye madde ekletmez; yeni sapma bulunursa buraya tarihli madde olarak yazılır, kapatılınca düşülür. Kapatma kapsamı: 2× native `confirm()` → ConfirmDialog; ~14 sayfaya PageHeader; ScheduledModule tam standardizasyon (PageHeader+StatCard+iskelet sırası+Button+toast, 7 sayfayı birden düzeltti); tüm inline spinner'lar → TableSkeleton/`Loader2`; paylaşılan bileşenlerdeki `bg-teal-600` → teal-700 (EmptyState/Pagination/FileDropzone/mesajlaşma); elle aksiyon butonları → Button; krediler oran girişleri → MoneyInput; devam-takip mobil tablo→kart; AA kontrast düzeltmeleri (gray-400→500, amber rozet, teal-600 tab/heatmap→700, kiosk metni); manuel pagination'lar → Pagination; eksik EmptyState'ler; hata-loglar inline modal → Modal; cyan/blue focus ring'ler → teal-500; `EmptyState message=` prop hatası → `description=` (3 dosya).

**Sapma kapatma (2026-06-17 mobil/tasarım geçişi):** emoji-as-icon → Lucide [cariler ödeme-yöntemi rozetleri 🏦💳💵📄📜 → Landmark/CreditCard/Banknote/FileText/Scroll; mizan lejant 📖 → "defter ikonu" (BookOpen zaten satır-aksiyonunda); otel-rezervasyon 👥 → Users]; mizan + fiş-icmali yükleme/lejant metinleri `text-gray-400` → `text-gray-500` (AA). **Denetim düzeltmesi:** önceki mobil denetimin "15 sayfa kart görünümü yok" bulgusu büyük ölçüde **yanlış pozitifti** — cekler/cariler/butce/audit-loglar/onay-akisi/otel-rezervasyon **zaten `sm:hidden` kart bloğuna sahip** (grep `overflow-x-auto`'yu görüp komşu kart bloğunu kaçırmış). **krediler de gerçek kart eksiği DEĞİL** (ikinci doğrulama): ana listesi zaten kart-tabanlı + responsive (başlıkta `hidden sm:inline` ile ikincil bilgi mobilde gizli), tek tablosu açılan **KMH/taksit çizelgesi** (8 sütun yoğun matris → yatay-scroll doğru kalıp, mizan/fiş-icmali gibi). Sonuç: **hiçbir liste sayfasında kart-görünümü rewrite gerekmiyor**. **Yapıldı (2026-06-17):** krediler 5 aksiyon butonuna (`+Taksit/Düzenle/Kapat/Yeniden Aç/Sil`) `touch-target` (mobil 44×44). **Kalan (dedikli görsel geçiş, mobil ekranda doğrulanmalı):** diğer sayfaların satır-aksiyon `touch-target`'ları; form ARIA (`aria-invalid`/`aria-describedby`) yayılımı; spinner→TableSkeleton; dekoratif `gray-300/400` kuyruğu; krediler detay butonlarının `Button.svelte`'e taşınması (inline bg hâlâ var).

**Bilinçli bırakılanlar (sapma DEĞİL):** döviz grafik lejantındaki `bg-teal-600` renk çizgisi (dekoratif, grafik rengiyle eşleşir); yoğun tablo satır-aksiyonları ikon-only (istisna); kalite şablon eşiği ve cariler vade günü `type="number"` (para değil — yüzde puanı/gün sayısı); stok/depolar bar'ı `bg-amber-400` (salt dekoratif, üzerinde metin yok); kiosk polling'i (public WS'siz sayfa).

**Bilerek istisna olan sayfalar (kanonik iskelete uymaz, normaldir):** Mesajlaşma (iki-panel sohbet), Uçak Rezervasyon (gömülü widget), Döviz (salt-okunur kur paneli + grafik), Panel/Dashboard (karşılama + özet — kendi başlığı), Nakit Akım iç accordion'u, public `/devam` sayfaları (kiosk/kurulum/basış — dashboard iskeleti yok; kiosk'ta sınırlı polling WS'siz public sayfa olduğu için kabul). Bunlar yine de **Button/Lucide/AA/StatCard/hata yönetimi** ilkelerine uyar.

**Yeni modül "tasarımcı" kontrol listesi** (10 boyut — her yeni sayfa için):
1. **Kullanılabilirlik** — arama+filtre+CTA çalışıyor mu, aksiyonlar keşfedilebilir mi?
2. **Tutarlılık** — kanonik iskelet + StatCard + PageHeader + Button (referans: avanslar)?
3. **Görsel hiyerarşi** — başlık → özet → filtre → içerik; en önemli sayı en büyük?
4. **Hız** — Skeleton loading, WS event-driven (polling yasak), 2000+ kayıtta truncation uyarısı?
5. **Mobil** — `<md`'de sidebar hamburger, tablo→kart, butonlar `w-full sm:w-auto`, taşma yok?
6. **Erişilebilirlik** — AA kontrast (teal-700), StatusBadge semantik renk, form label+ARIA, focus halkası?
7. **Hata yönetimi** — Toast + ErrorLog, boş `catch{}` yasak, EmptyState, ConfirmDialog?
8. **Tasarım** — kart `rounded-xl shadow-sm`, teal tema, Lucide ikon, tutarlı padding?
9. **Bir bakışta anlaşılma** — StatCard'lar + renk kodlama durumu anında okutuyor mu?
10. **Başarı ölçütü** — sayfa tek bakışta "ne durumdayım"ı cevaplıyor; birincil eylem ≤1 tık?

Hızlı özet:
- **Renk paleti:** Cyan/Teal (ana), Gray (nötr), Red (tehlike), Amber (uyarı), Green (başarı), Blue (bilgi)
- **Layout:** Sidebar (sol, açılır/kapanır) + Topbar (üst, kullanıcı dropdown + geri butonu)
- **Buton:** `Button.svelte` — primary rengin tek kaynağı (teal-700, AA). Elle buton yazma. `variant`/`size`/`loading`/`fullWidth`/`class` (layout-only)
- **Sayfa başlığı:** `PageHeader.svelte` — `<h1>` + açıklama + `actions` snippet (her sayfada zorunlu)
- **Kart stili:** `bg-white border border-gray-200 rounded-xl shadow-sm`
- **İkon kütüphanesi:** **Lucide** (`lucide-svelte`) — emoji/inline SVG yeni kodda kullanılmaz
- **Sayfa iskeleti:** PageHeader → Stat Cards → Filtre barı (sol arama + filtre chip + sağ export/Yeni) → Tablo/liste → Pagination
- **Modal:** `Modal.svelte` — `md` (600px) varsayılan; `sm` (400px) onay, `lg` (800px) detay
- **Silme onayı:** `ConfirmDialog.svelte` — native `confirm()` **yasak**
- **Loading:** Skeleton ekran (spinner değil)
- **Tarih:** `DD.MM.YYYY` — native `<input type="date">`
- **Para girişi:** `MoneyInput.svelte` — detay aşağıda
- **Arama:** debounce 300ms + ✕ temizle butonu
- **Dosya yükleme:** `FileDropzone.svelte` — drag-drop + "Göz at" butonu
- **Form label:** üstte, zorunlu alanda kırmızı `*` · hata → inline kırmızı, field altında
- **Uzun formlar:** Tab'lara bölünür (3+ alan grubu için)
- **Satır aksiyonu:** hover'da beliren (sağda ikon butonlar ✏ 🗑)
- **Kolon sort:** tıklanır başlık + ↑↓ ikon (`SortableHeader.svelte`)
- **Toplu işlem:** checkbox + başlık barı dönüşümü (`BulkActionsBar.svelte`)
- **Pagination:** klasik sayfa numaraları + page_size (25/50/100/200)
- **Boş durum:** `EmptyState.svelte` — ikon + mesaj + CTA
- **Mobil:** `<md` breakpoint'te tablo → kart görünümü
- **Breadcrumb:** sadece iç sayfalarda (`Breadcrumb.svelte`)
- **Toast:** sağ üst, 3 sn (`$lib/stores/toast.ts`)
- **Durum rozeti:** `StatusBadge.svelte` — semantik sabit renk (yeşil=başarılı, kırmızı=hata, sarı=bekliyor, mavi=bilgi, gri=pasif)
- **Klavye:** Esc → modal kapat · Enter → primary action
- **Export:** başlık barında indirme ikon butonu → Excel/PDF menüsü

- **Para girişi:** `MoneyInput.svelte` bileşeni kullanılır — tüm formlarda para tutarı için **zorunludur**
  - Türkçe format: binlik ayırıcı `.` (nokta), ondalık ayırıcı `,` (virgül), varsayılan 2 ondalık
  - **Canlı binlik format:** Yazarken gerçek zamanlı formatlama ("1234567" → "1.234.567")
  - **İmleç konumu korunur:** Format değişse bile imleç sağdan aynı mesafede kalır — kullanıcı istediği yerden yazmaya devam edebilir
  - **Kalıcı highlight:** `onmousedown` + `preventDefault` ile tarayıcının normal click→caret yerleşimi engellenir; focus anında `select()` çağrısı tüm metni seçili bırakır → yeni rakam yazınca önceki değer tek seferde silinir
  - Blur'da min/max clamp + decimals yuvarlama
  - `value` tipi `number | null` (boş input → null), form state'i buna göre tanımlanmalı
  - Opsiyonel para birimi rozeti: `currency="TRY" | "EUR" | "USD" | "GBP"` veya custom string
  - `<MoneyInput bind:value={form.amount} currency="TRY" min={0} placeholder="0,00" />`
  - Test: `src/lib/components/MoneyInput.test.ts` (33 test — formatTR/parseTR/formatLiveTR/round-trip)
  - **`<input type="number">` para için kullanılmaz** — UX detayları (canlı binlik, TR format, highlight kalıcılığı) MoneyInput'ta çözülür
  - **İç mimari:** `bind:value` kullanılmaz; `bind:this` ile DOM referansı alınır, `oninput` handler'ı manuel format+caret yönetir. `$effect` focus dışında input.value'yu senkronlar, focus içinde skip eder (kullanıcı "1,5" yazarken "1,50" zorlanmasın).
- **Form doğrulama:** `validation.ts` helper'ları + field-level hata gösterimi
