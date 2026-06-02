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
- **Güvenlik Header'ları:** `SecurityHeadersMiddleware` ile X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy eklenir
- **Global Exception Handler:** Beklenmeyen hatalar loglanır, kullanıcıya generic mesaj döner
- **Audit Logging:** Tüm CRUD işlemleri ve giriş/çıkış olayları `audit_logs` tablosuna kaydedilir

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
│   ├── tests/                   # pytest testleri (700+ test, %55 satır kapsamı)
│   │   ├── conftest.py          # Test fixture'ları (SAVEPOINT rollback)
│   │   ├── test_health.py
│   │   ├── test_auth.py
│   │   ├── test_system.py, test_system_users.py, test_system_roles.py, test_system_modules.py
│   │   ├── test_messages.py, test_messages_extended.py
│   │   ├── test_finance.py, test_finance_performance.py
│   │   ├── test_scheduled_base.py   # Muhasebe + İK (8 modül)
│   │   ├── test_credits.py, test_checks.py, test_budget.py, test_onay.py
│   │   ├── test_advances.py, test_quality_module.py
│   │   ├── test_notifications.py    # Bildirim testleri
│   │   ├── test_permissions.py      # İzin kontrolleri
│   │   └── test_ws_push_audit.py
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

### Finans — Cariler
- `POST /api/finance/cariler/upload` — Excel dosya yükleme (response içinde `removal_candidates` döner: kapsamda olup Excel'de bulunmayan kayıtlar)
- `GET /api/finance/cariler/uploads` — Yükleme geçmişi
- `DELETE /api/finance/cariler/uploads/{id}` — Yükleme sil
- `POST /api/finance/cariler/transactions/bulk-delete` — Toplu işlem silme (kaynakta olmayan kayıtlar için; korumalı kayıtlar atlanır)
- `GET /api/finance/cariler/vendors` — Cari listesi (paginated, arama)
- `GET /api/finance/cariler/vendors/{id}` — Cari detay + işlemler
- `GET /api/finance/cariler/payment-schedule` — Haftalık ödeme planı
- Detaylı bilgi: `docs/modules/cariler.md`

### Finans — Ödeme Talimat Listeleri
- `GET/POST /api/finance/payment-instructions/` — Talimat listesi listele/oluştur
- `GET/PATCH/DELETE /api/finance/payment-instructions/{id}` — Liste detay/güncelle/sil
- `POST /api/finance/payment-instructions/{id}/items` — Cari kalem(ler) ekle (tutar bakiyeden gelir, mükerrer vendor atlanır)
- `PATCH/DELETE /api/finance/payment-instructions/{id}/items/{item_id}` — Kalem tutarı güncelle / çıkar
- `GET /api/finance/payment-instructions/{id}/export/excel` — Excel dökümü
- `GET /api/finance/payment-instructions/{id}/export/pdf` — PDF dökümü
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
- `GET/POST/PATCH/DELETE /api/accounting/recurring/` — Düzenli ödeme CRUD
- `PATCH /api/accounting/recurring/entries/{id}` — Düzenli ödeme girişi güncelle
- `GET /api/accounting/recurring/summary/totals` — Düzenli ödeme özeti
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

### Finans — Bankalar
- `GET /api/finance/banks/accounts/` — Banka hesap listesi
- `POST /api/finance/banks/accounts/` — Banka hesabı oluştur
- `PATCH /api/finance/banks/accounts/{id}` — Banka hesabı güncelle
- `DELETE /api/finance/banks/accounts/{id}` — Banka hesabı sil
- `POST /api/finance/banks/upload` — Ekstre yükleme (otomatik tanıma)
- `POST /api/finance/banks/accounts/{id}/upload` — Hesaba özel ekstre yükleme
- `GET /api/finance/banks/accounts/{id}/transactions` — Hesap işlemleri
- `GET /api/finance/banks/accounts/{id}/statements` — Ekstre listesi
- Detaylı bilgi: `docs/modules/bankalar.md`

### Finans — Çekler
- `GET /api/finance/checks/` — Çek listesi (paginated, filtrelenebilir)
- `POST /api/finance/checks/upload` — Çek Excel yükleme
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
- Detaylı bilgi: `docs/modules/krediler.md`

### Finans — Avanslar
- `GET/POST/PATCH/DELETE /api/finance/avanslar/` — Avans CRUD
- `GET /api/finance/avanslar/summary` — Avans özeti
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

### Satış — Otel Rezervasyon
- `POST /api/sales/reservations/upload` — Crystal Reports XLS/XLSX yükleme (RecId bazlı upsert). Response'a `removal_candidates: RemovalCandidate[]` eklenir — yüklemenin check-in + record-date kapsamı içinde olup dosyada bulunmayan kayıtlar (olası iptaller)
- `GET /api/sales/reservations/uploads` — Yükleme geçmişi
- `DELETE /api/sales/reservations/uploads/{id}` — Yüklemeyi sil (rezervasyon satırları korunur, FK SET NULL)
- `POST /api/sales/reservations/bulk-delete` — `removal_candidates` listesinden seçilen ID'leri toplu sil (max 5000, audit loglu)
- `GET /api/sales/reservations/` — Paginated liste (start_date, end_date, agency, nation, room_type, rez_status, search)
- `GET /api/sales/reservations/summary` — Dashboard KPI + dağılımlar + **doluluk metrikleri** (total_capacity, occupancy_pct, aylık/tip başına doluluk)
- `GET /api/sales/reservations/daily-occupancy?month=YYYY-MM` — Aylık drill-down: günlük doluluk + check-in/out sayıları (takvim heatmap için)
- Detaylı bilgi: `docs/modules/otel-rezervasyon.md`

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
- **Tablolar (51):** users, roles, modules, role_module_permissions, conversations, conversation_members, messages, audit_logs, push_subscriptions, notifications, error_logs, vendors, vendor_uploads, vendor_transactions, transaction_categories, bank_accounts, bank_statements, bank_transactions, checks, check_uploads, credit_products, credit_payments, credit_card_statements, credit_card_transactions, advances, departments, budgets, budget_categories, finance_events, scheduled_definitions, scheduled_entries, exchange_rates, cash_flows, quality_templates, quality_template_sections, quality_template_fields, quality_template_assignees, quality_forms, quality_form_values, reservations, reservation_uploads, room_types, agency_groups, approval_workflows, approval_workflow_requestor_roles, approval_workflow_approver_roles, approval_workflow_steps, approval_requests, approval_request_logs, payment_instruction_lists, payment_instruction_items
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
- Finans (finance) → Nakit Akım (finance.cash_flow), Cariler (finance.cariler), Bankalar (finance.banks), Çekler (finance.checks), Krediler (finance.krediler), Avanslar (finance.avanslar), Döviz (finance.doviz), Bütçe (finance.butce), Onay (finance.onay)
- Muhasebe (accounting) → Vergiler (accounting.taxes), Düzenli Ödemeler (accounting.recurring), Alınan Kiralar (accounting.rent_income), Verilen Kiralar (accounting.rent_expense), Temettü (accounting.dividend)
- İnsan Kaynakları (hr) → Maaş (hr.salary), Stopaj (hr.withholding), SGK (hr.sgk)
- Kalite (quality) → Şablonlar (quality.templates), Formlar (quality.forms)
- Sistem (system) → Kullanıcılar (system.users), Roller (system.roles), Modüller (system.modules), Audit Loglar (system.audit_logs), Hata Logları (system.error_logs), Onay Akışı (system.approval), Sunucu (system.server)
- Satış (sales) → Uçak Rezervasyon (sales.flight), Otel Rezervasyon (sales.hotel_reservation), Oda Tipleri (sales.room_types)

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

### Modül Dokümantasyon Şablonu
Her modül dosyası şu bölümleri içermelidir:
1. **Genel Bilgi** — Modül kodu, üst modül, frontend rota, backend prefix, izin kodu
2. **Dosya Haritası** — Backend (model, schema, router) ve Frontend (sayfa, bileşen) dosyaları
3. **Veritabanı Şeması** — Tablo yapısı, kolonlar, indeksler
4. **API Endpoint'leri** — Method, path, izin seviyesi, açıklama
5. **Frontend UI Yapısı** — Bileşenler, state yönetimi, renk şeması
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
| Oda Tipleri | `docs/modules/oda-tipleri.md` |

## UI Tasarım Kuralları

**Tüm UI tutarlılık spec'i → [`docs/ui-kurallari.md`](docs/ui-kurallari.md)** (sayfa iskeleti, paylaşılan bileşen API'leri, renk kodları, faz planı)

Hızlı özet:
- **Renk paleti:** Cyan/Teal (ana), Gray (nötr), Red (tehlike), Amber (uyarı), Green (başarı), Blue (bilgi)
- **Layout:** Sidebar (sol, açılır/kapanır) + Topbar (üst, kullanıcı dropdown + geri butonu)
- **Kart stili:** `bg-white border border-gray-200 rounded-xl shadow-sm`
- **İkon kütüphanesi:** **Lucide** (`lucide-svelte`) — emoji/inline SVG yeni kodda kullanılmaz
- **Sayfa iskeleti:** Başlık → Stat Cards → Filtre barı (sol arama + filtre chip + sağ export/Yeni) → Tablo/liste → Pagination
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
