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
  - **Handler, router endpoint'inin davranışını BİREBİR yansıtmalı** (yalnız model alanları değil): payload anahtarları model kolonlarıyla aynı olmalı, zorunlu kolonlar set edilmeli, ve router'ın yan etkileri (finance_events upsert, eşleşme kaldırma, FIFO/sync, açıklama yeniden üretimi) handler'da da uygulanmalı. Handler yalnız onay onaylanınca çalıştığından sapmalar sessiz kalır.
  - **Test katmanları (2026-06-17 genişletildi):** `tests/test_approval_system.py::TestExecutorImportIntegrity` üç AST testi — (a) `from app...import` çözümü, (b) `Model(kwarg=...)` alan geçerliliği, (c) **`check_approval` çağıran HER modülün handler'ı var** (`test_all_approval_callers_have_executor_handler`). **AMA** AST testleri payload-anahtar uyuşmazlığını, eksik-zorunlu-kolonu, çift-serileştirmeyi ve eksik yan-etkiyi YAKALAYAMAZ → yeni handler için **modül-bazlı uçtan-uca onay regresyon testi** de eklenmeli (örnekler: `test_create_room_type_via_approval_regression`, `test_check_status_via_approval_regression`, `test_quality_template_via_approval_regression`). Bu hata sınıfı tarama denetiminde finance.checks/quality.templates/sales.room_types'ta bulundu (2026-06-17).
  - Tüm onay motoru (workflow + talep + executor) `tests/test_approval_system.py` ile test edilir (uçtan-uca onay→uygula + modül regresyonları dahil)
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
- **Dosya Yükleme Limitleri (`utils/file_validation.py`):** Tüm dosya yüklemeleri `validate_upload_file(file, allowed_types=[...])` ile doğrulanır — **uzantı whitelist'i + boyut limiti + magic-byte içerik eşleşmesi** (uzantı sahteciliği + boş dosya engellenir). Limitler: **genel 20 MB · Excel (`.xlsx`/`.xls`) 10 MB · PDF (`.pdf`) 25 MB**. Magic-byte: Excel = ZIP(`PK`)/OLE2, PDF = `%PDF`. İçerik uzantıyla uyuşmazsa 400 + uyarı log'u. Yeni yükleme endpoint'i (cari/çek/rezervasyon/banka ekstresi) bu helper'ı **kullanmak zorundadır**
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
- **Pagination:** List endpoint'leri **istek** `?page=1&page_size=50` (page_size UI seçenekleri 25/50/100/200; backend `le` üst sınırı endpoint'e göre) alır; **yanıt** `{ items, total, page, page_size, pages }` döner. Sayfalı listede **`limit`/`offset` query-param'ı kullanılmaz** (bunlar yalnız ORM içi `.offset()/.limit()`; top-N/son-N endpoint'leri sayfalama değildir → `limit` query-param'ı alabilir). Kullanıcı-kontrollü sıralama: **`?sort_by=field&sort_dir=asc|desc`** — `sort_by` **whitelist'li** (regex pattern ile sabit alan kümesi → keyfi kolon sıralaması engellenir), `sort_dir` default `asc`.
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
│   ├── tests/                   # pytest testleri (1170+ test, ~%60 satır kapsamı)
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

### Claude Code Ajan Akışları (`.claude/`)

Projeye özel, git'te takip edilen (ekiple paylaşılan) Claude Code otomasyonları. Yeni komut/agent eklendiğinde Claude Code oturumunun yeniden başlatılması (reload) gerekir.

- **Hook'lar — `.claude/settings.json`:**
  - `Stop`: her tur sonunda `git add -A` + commit `"Otomatik yedek: <tarih>"` + GitHub push (async). Repodaki tüm `Otomatik yedek:` commit'lerinin kaynağı budur.
  - `PreToolUse(Bash)`: `scripts/claude-guard-secrets.sh` — `git add -f/--force` ile `.env/.pem/.key/secret` dosyalarının `.gitignore`'u atlayıp GitHub yedeğine sızmasını engeller (exit 2). Komut o deseni içermiyorsa exit 0 (normal komutlar etkilenmez). Not: desen komut string'inde geçerse (echo içinde bile) eşleşir — bilinçli, güvenli tarafa düşer.
- **Slash komutları — `.claude/commands/`:**
  - `/test [backend|frontend|all] [pytest filtre]` — testleri **doğru test DB** ile çalıştırır (şifre `.env`'den runtime'da, `_test` DB zorunlu).
  - `/deploy [backend|frontend|all]` — zorunlu deploy akışı (backend=restart, frontend=`deploy-frontend.sh` build+restart) + health doğrulama.
  - `/durum` — servisler + sağlık + Sedna tüneli (11433) + dinlenen portlar + git yedek durumu.
  - `/sedna-sync` — Sedna ters tünel + bağlantı teşhisi (içe-aktarma neden 503; gerçek sync UI'dan).
  - `/migration "<açıklama>"` — alembic revize üret → **gözden geçir** (autogenerate yanlış DROP üretebilir) → uygula.
  - `/yeni-modul "<code> <Ad>"` — CLAUDE.md kontrol-listesiyle yeni modül iskeleti (model→schema→router[izin+onay+audit]→executor handler→migration→RBAC→frontend→test→doküman).
- **Subagent — `.claude/agents/`:**
  - `modul-denetci` — yeni/değişen modülü CLAUDE.md kurallarına göre salt-okunur denetler (izin, onay akışı + executor handler, audit, Türkçe karakter, Python 3.9, merkezi sabitler, finance_events, UI tasarım sistemi, doküman, test). Kanıtlı (`dosya:satır`) bulgu döner; kod yazmaz. (İlk testte `sales.room_types`'ın eksik executor handler'ını yakaladı — aşağıya bakın.)
- **İzinler — `.claude/settings.local.json`** (gitignore'da, paylaşılmaz): izin-sorma azaltan komut allowlist'i.
- **Reload:** yeni komut/agent dosyaları Claude Code oturumu **yeniden başlatılınca** görünür; `settings.json` hook'ları dinamik yüklenir.

## API Endpoints

Tüm endpoint kataloğu (method · path · izin · iş-kuralı notları) **[`docs/api-haritasi.md`](docs/api-haritasi.md)**'ye taşındı — ana dosyayı yaşayan-kural odaklı + küçük tutmak için. Yeni/değişen endpoint'te o kataloğu güncelle.

**Endpoint tasarım kuralları (CLAUDE.md'de kalır):**

- **İsimlendirme:** REST + çoğul kaynak hiyerarşisi (`/api/finance/cariler/vendors/{id}/bank-accounts`); path **ASCII** (Türkçe segmentte bile: `/dashboard/sistem/kullanicilar`); çok-kelimeli segment **kebab-case** (`cash-flow`, `sedna-import`, `room-types`, `daily-activity`).
- **Liste istek/yanıtı:** istek `?page=1&page_size=50` (sıralama varsa `?sort_by=field&sort_dir=asc|desc`, `sort_by` whitelist'li; sayfalı listede `limit`/`offset` query-param'ı **yok**); yanıt `{ items, total, page, page_size, pages }` (Pagination kuralı).
- **Mutasyon (POST/PATCH/DELETE):** `require_permission()` + `check_approval()` + audit **zorunlu** (yukarıdaki ilgili bölümler). Salt-okuma GET'ler onaydan muaf.
- **Dosya/yükleme:** `validate_upload_file()` (uzantı + boyut + magic-byte; yukarı bkz).

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
- Sistem (system) → Kullanıcılar (system.users), Roller (system.roles), Modüller (system.modules), Audit Loglar (system.audit_logs), Hata Logları (system.error_logs), Onay Akışı (system.approval), Sunucu (system.server), Yedekleme (system.backup), Dokümanlar (system.docs)
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

**Test dosyaları (274 test, 22 dosya — toplam birebir doğrulandı):**

*API & utils:*
- `src/lib/api.test.ts` — API wrapper (GET/POST/PATCH/DELETE, upload, hata yönetimi, 401/403, signal, fetchRaw) (22 test)
- `src/lib/utils/finance.test.ts` — formatCurrency, formatCompact, groupByMonth, getTodayKeys, transfer hariç tutma (23 test)
- `src/lib/utils/paymentMethods.test.ts` — PAYMENT_METHODS, SELECTABLE, CATEGORIES, getPaymentMethod fallback (16 test)
- `src/lib/utils/colorMap.test.ts` — categoryColorMap, filterColorMap, availableColors, getColor fallback (16 test)
- `src/lib/utils/validation.test.ts` — validateEmail, validatePassword, validateRequired, validateModuleCode (12 test)
- `src/lib/utils/push.test.ts` — isPushSupported, getPushPermissionState (6 test)
- `src/lib/utils/lazy-mount.test.ts` — tembel mount görünürlük gözlemcisi (7 test)
- `src/lib/constants/finance.test.ts` — Kaynak tipleri, ödeme yöntemleri, kredi tipleri, para birimleri, sabit tutarlılığı (15 test)

*Store'lar:*
- `src/lib/stores/auth.test.ts` — setAuth, loadAuth, hasPermission (izin matrisi) (15 test)
- `src/lib/stores/toast.test.ts` — showToast, removeToast, otomatik kaldırma (12 test)
- `src/lib/stores/notification.test.ts` — setMutedConversations, updateMutedConversation, isConversationMuted, toggleSound (11 test)
- `src/lib/stores/ui.test.ts` — sidebar state, toggleSidebar, closeSidebar (6 test)

*Bileşenler:*
- `src/lib/components/MoneyInput.test.ts` — formatTR/parseTR/formatLiveTR/round-trip + imleç/highlight (33 test)
- `src/lib/components/Pagination.test.ts` — getPageNumbers (windowed), sayfa boyutu (16 test)
- `src/lib/components/FileDropzone.test.ts` — drag-drop, MIME/boyut doğrulama, çoklu dosya (14 test)
- `src/lib/components/SortableHeader.test.ts` — sıralama yönü/ikon (11 test)
- `src/lib/components/EmptyState.test.ts` — ikon/başlık/açıklama/CTA (9 test)
- `src/lib/components/StatusBadge.test.ts` — semantik durum renkleri (8 test)
- `src/lib/components/Breadcrumb.test.ts` — kırılım üretimi (6 test)
- `src/lib/components/TableSkeleton.test.ts` — satır/kolon iskeleti (6 test)
- `src/lib/components/FormSkeleton.test.ts` — form iskeleti (5 test)
- `src/lib/components/BulkActionsBar.test.ts` — toplu seçim/aksiyon barı (5 test)

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
| Nakit Akım İş Akışı | `docs/modules/nakit-akim-is-akisi.md` |
| Bankalar | `docs/modules/bankalar.md` |
| Cariler | `docs/modules/cariler.md` |
| Çekler | `docs/modules/cekler.md` |
| Krediler | `docs/modules/krediler.md` |
| Avanslar | `docs/modules/avanslar.md` |
| Döviz | `docs/modules/doviz.md` |
| Bütçe | `docs/modules/butce.md` |
| Onay (Departman İş Akışı) | `docs/modules/onay.md` |
| Onay Akışı (Sistem/Rol Bazlı) | `docs/modules/onay-akisi.md` |
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
| Sistem — Dokümanlar | `docs/modules/sistem-dokumanlar.md` |
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

**Sapma takibi:** Geçmiş denetimlerin (2026-06-09 → 2026-06-20) sapma envanteri ve kapatma kayıtları **[`docs/ui-degisiklik-gunlugu.md`](docs/ui-degisiklik-gunlugu.md)**'ne taşındı. Yukarıdaki tabloya yeni madde eklenmez; yeni sapma bulunursa günlükte tarihli izlenir, kapatılınca düşülür.

### Tasarımcı İnceleme Standardı — 10 Boyut (her modül + YENİ MODÜL için ZORUNLU)

Her yeni/değişen sayfa, kanıtlı (dosya:satır) olarak şu 10 boyutta denetlenir. Her boyutun
**GEÇER** (kabul) kriteri ve **KALIR** (sapma — düzeltilmeli) örnekleri vardır. Referans
sayfalar: **`finans/avanslar`** ve **`sistem/kullanicilar`** (kanonik). Bu standart, modüllerin
**birbiriyle tutarlı** olmasını sağlamak içindir — her sayfa aynı iskeleti, aynı bileşeni, aynı
sırada kullanır.

1. **Kullanılabilirlik** — GEÇER: arama (debounce 300ms + ✕) + filtre + birincil CTA keşfedilebilir, birincil eylem ≤1 tık. KALIR: gizli/keşfedilemeyen aksiyon, çok-adımlı temel akış.
2. **Tutarlılık** — GEÇER: kanonik iskelet (PageHeader→StatCard→filtre→içerik→Pagination→Modal) + paylaşılan bileşenler; sayfa diğer modüllerle **aynı görünür**. KALIR: bespoke özet kartı (StatCard yerine), elle tab/segment, sayfaya özel buton stili, kanonik sıradan sapma.
3. **Görsel hiyerarşi** — GEÇER: başlık→özet→filtre→içerik akışı; en önemli sayı en belirgin. KALIR: gömülü/dağınık birincil aksiyon, eşit ağırlıkta her şey.
4. **Hız** — GEÇER: `TableSkeleton`/`FormSkeleton` (spinner DEĞİL), WS event-driven (polling yasak), 2000+ kayıtta truncation uyarısı. KALIR: `animate-spin`/"Yükleniyor…" metni, veri için `setInterval` polling.
5. **Mobil** — GEÇER: `<md`'de tablo→kart (`sm:hidden`/`hidden sm:block`), butonlar `w-full sm:w-auto`, **tüm dokunma hedefleri ≥44px** (`Button` otomatik; ham `<button>`'a `touch-target`), taşma yok. KALIR: yalnız `overflow-x-auto` tablo, `p-1.5` ham satır-aksiyonu (<44px), yatay sıkışma.
6. **Erişilebilirlik** — GEÇER: AA kontrast (teal **700**, en açık gövde metni gray-**500**), `StatusBadge` semantik renk, **ikon-only buton + `Select`'e `aria-label`**, form `Field`+`fieldErrors`+`aria-invalid`/`aria-describedby`, `focus:ring-teal-500`, Esc/Enter klavye, `prefers-reduced-motion`. KALIR: teal-600/gray-400 gövde, tek `formError` string'i, blue/cyan/teal-100 focus ring, placeholder-gray-300.
7. **Hata yönetimi** — GEÇER: her `catch`→`console.error`+`showToast`, `EmptyState` (düz metin değil), `ConfirmDialog` (native `confirm()` YASAK). KALIR: sessiz `catch`, yalnız-console, bespoke silme onayı.
8. **Tasarım** — GEÇER: kart `rounded-2xl border-gray-200 shadow-sm` (paylaşılan bileşenle aynı), teal tema, **yalnız Lucide ikon**, tutarlı padding. KALIR: inline `<svg>`, emoji-as-icon (😊🔔✅⚠️), `bg-teal-600` dolu buton, gradyan/marka-dışı renk.
9. **Bir bakışta anlaşılma** — GEÇER: StatCard + semantik renk kodu durumu anında okutur; sayfa "ne durumdayım"ı tek bakışta cevaplar. KALIR: ham sayı yığını, renk kodu yok.
10. **Başarı ölçütü** — GEÇER: kullanıcı hedefine net ve hızlı ulaşır; birincil eylem ≤1 tık, geri bildirim (toast) net. KALIR: belirsiz sonuç, sessiz başarı/başarısızlık.

**Tek-kaynak bileşen kuralı (modüller-arası tutarlılığın temeli):** Özet kart=`StatCard` · buton=`Button`
(elle `bg-*` YASAK; `touch-target` Button'da gömülü) · başlık=`PageHeader` · liste iskeleti=`ListPage` ·
form alanı=`Input`/`Select`/`Textarea`/`Field` · para=`MoneyInput` · dosya=`FileDropzone` · sayfalama=`Pagination` ·
modal=`Modal` · onay=`ConfirmDialog` · boş=`EmptyState` · yükleme=`TableSkeleton`/`FormSkeleton` · durum=`StatusBadge` ·
ikon=Lucide. **Paylaşılan bileşeni atlayıp elle yazmak = sapma.** Bir sayfaya özel "ada" stil bırakma; düzeltme
varsa paylaşılan bileşende yap → tüm modüllere yayılsın.

### Bilinçli İstisnalar (sapma DEĞİL)

- **Kanonik iskelete uymayan sayfalar:** Mesajlaşma (iki-panel sohbet + MessageInput autogrow), Uçak Rezervasyon (gömülü widget), Döviz (salt-okunur kur paneli — StatCard/EmptyState beklenmez, ama Pagination/Skeleton uygulanır), Panel/Dashboard (karşılama, kendi başlığı), Login (bespoke auth — yine de AA), Nakit Akım iç accordion'u, public `/devam` kiosk (WS'siz sınırlı polling + tam-ekran), ve mizan/fis-icmali/roller-matrisi/vardiya-çizelgesi/KMH yoğun-matris tabloları (yatay-scroll doğru kalıp). Hepsi yine **Button/Lucide/AA/hata-yönetimi** ilkelerine uyar.
- **Dekoratif/anlamlı küçük sapmalar:** döviz grafik lejantındaki teal-600 çizgi (grafik rengiyle eşleşir) ve stok/depolar `bg-amber-400` bar (üzerinde metin yok) salt dekoratiftir; yoğun tablo satır-aksiyonları ikon-only kalabilir; kalite şablon eşiği ve cariler vade günü `type="number"` (yüzde puanı/gün sayısı — para değil, MoneyInput gerekmez).

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
