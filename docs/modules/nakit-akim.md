# Nakit Akım Modülü

## Genel Bilgi

| Özellik | Değer |
|---|---|
| **Modül Kodu** | `finance.cash_flow` |
| **Üst Modül** | `finance` (Finans) |
| **Frontend Rota** | `/dashboard/finans/nakit-akim` |
| **Backend Prefix** | `/api/finance/cash-flow/` |
| **İzin** | `finance.cash_flow` → `can_view` / `can_use` |

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `backend/app/models/cash_flow.py` | `CashFlow` SQLAlchemy modeli |
| `backend/app/schemas/cash_flow.py` | `CashFlowCreate`, `CashFlowUpdate`, `CashFlowResponse` Pydantic şemaları |
| `backend/app/routers/finance/__init__.py` | Finance router grubu (alt router'ları birleştirir) |
| `backend/app/routers/finance/cash_flow/` | Nakit akım paketi (aşağıdaki alt modüller) |
| `backend/app/routers/finance/cash_flow/__init__.py` | Alt router'ları birleştiren paket girişi |
| `backend/app/routers/finance/cash_flow/listing.py` | Liste, özet, mobil dashboard endpoint'leri |
| `backend/app/routers/finance/cash_flow/matching.py` | Eşleştirme endpoint'leri (cari, kredi kartı, kredi) |
| `backend/app/routers/finance/cash_flow/eur_balances.py` | EUR bakiye endpoint'i |
| `backend/app/routers/finance/cash_flow/_helpers.py` | Ortak yardımcı fonksiyonlar |

### Frontend
| Dosya | Açıklama |
|---|---|
| `frontend/src/routes/dashboard/finans/+page.svelte` | Finans ana sayfa (nakit-akim'e yönlendirir) |
| `frontend/src/routes/dashboard/finans/nakit-akim/+page.svelte` | Nakit akım UI (liste, özet, form) |

### Veritabanı
| Dosya | Açıklama |
|---|---|
| `backend/alembic/versions/fc72105614de_add_finance_module.py` | Modül kaydı migration |
| `backend/alembic/versions/b6a51d72e1ce_add_april_may_sample_cash_flows.py` | Örnek veri migration |

## Veritabanı Şeması

### `cash_flows` Tablosu

| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | `INTEGER` PK | Otomatik artan ID |
| `title` | `VARCHAR(200)` | Kayıt başlığı (zorunlu) |
| `type` | `VARCHAR(20)` | `"income"` veya `"expense"` |
| `amount` | `NUMERIC(12,2)` | Tutar (> 0) |
| `description` | `TEXT` NULL | Opsiyonel açıklama |
| `date` | `DATE` | İşlem tarihi (varsayılan: bugün) |
| `created_by` | `INTEGER` FK → `users.id` | Oluşturan kullanıcı (SET NULL on delete) |
| `created_at` | `TIMESTAMPTZ` | Oluşturulma zamanı |

**İndeksler:**
- `ix_cash_flows_type` — type kolonu
- `ix_cash_flows_date` — date kolonu
- `ix_cash_flows_created_by` — created_by kolonu

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/api/finance/cash-flow/` | `view` | Kayıt listesi (paginated, type/source/start_date/end_date/search filtresi) |
| `GET` | `/api/finance/cash-flow/mobile-dashboard` | `view` | Mobil dashboard özeti (banka bakiyeleri dahil) |
| `GET` | `/api/finance/cash-flow/summary` | `view` | Toplam gelir, gider, bakiye |
| `GET` | `/api/finance/cash-flow/monthly-summary` | `view` | Aylık gelir/gider/bakiye özeti |
| `GET` | `/api/finance/cash-flow/eur-balances` | `view` | EUR bakiye özeti |
| `GET` | `/api/finance/cash-flow/credit-payments-unpaid` | `view` | Ödenmemiş kredi taksitleri listesi |
| `GET` | `/api/finance/cash-flow/cc-statements-unpaid` | `view` | Ödenmemiş kredi kartı ekstreleri listesi |
| `POST` | `/api/finance/cash-flow/match-vendor-tx` | `use` | Cari işlem eşleştirme |
| `POST` | `/api/finance/cash-flow/match-cc-payment` | `use` | Kredi kartı ödeme eşleştirme |
| `POST` | `/api/finance/cash-flow/match-credit-payment` | `use` | Kredi taksit ödeme eşleştirme |
| `POST` | `/api/finance/cash-flow/unmatch-cc-payment` | `use` | Kredi kartı eşleştirme iptali |

### Query Parametreleri (GET list)
- `page` (int, default: 1)
- `page_size` (int, default: 100, max: 500)
- `type` (string, opsiyonel: `"income"` veya `"expense"`)

### Response Formatı (list)
```json
{
  "items": [{ "id", "title", "type", "amount", "description", "date", "created_by", "creator_name", "created_at" }],
  "total": 42,
  "page": 1,
  "page_size": 100,
  "pages": 1
}
```

## Frontend UI Yapısı

### Sayfa Bileşenleri
1. **Başlık Bölümü** — Sayfa başlığı + "Gelir Ekle" / "Gider Ekle" butonları (canUse kontrolü)
2. **Özet Kartları** — 3 kart grid: Toplam Gelir (emerald), Toplam Gider (rose), Net Bakiye (blue/red)
3. **Aylık Akordiyon** — Her ay genişletilebilir; başlıkta ay adı + gelir/gider/bakiye badge'leri
4. **T Yapısı** — Akordiyon içinde sol: giderler (rose), sağ: gelirler (emerald), ortada dikey mavi çizgi
5. **Odak Modu** — Sütun başlığına tıklayarak genişletme/daraltma (`focusMode`: balanced/expense/income)

### Renk Şeması
- **Gelir:** emerald (emerald-50 bg, emerald-200 border, emerald-600 text)
- **Gider:** rose (rose-50 bg, rose-200 border, rose-600 text)
- **Bakiye (+):** blue-600
- **Bakiye (-):** red-600
- **T çizgisi:** blue-500

### State Yönetimi
- Svelte 5 Runes: `$state`, `$derived`, `$effect`
- `items`, `summary`, `loading`, `showModal`, `editingId`, form alanları
- `monthGroups` — `$derived.by()` ile items'den hesaplanan aylık gruplar
- `expandedYears`, `expandedMonths`, `expandedDays` — 3 seviyeli akordiyon açık/kapalı state'i
- `visibleDays` — `IntersectionObserver` ile işaretlenen viewport'a girmiş günler (lazy mount sinyali)
- `focusMode` — T yapısı odak modu

### Performans / Lazy Mount
- **3 seviyeli `{#if}` lazy render** — yıl/ay/gün başlıkları haricinde içerik (CashFlowItem) yalnızca kullanıcı bir günü açtığında render edilir.
- **Başlangıç açık günü:** Yalnızca bugüne (veya matchDate'e) en yakın gün otomatik açılır; geri kalan tüm günler kapalı kalır → 2000 item olsa bile initial paint hafif kalır.
- **Day-content lazy mount (`use:lazyMount`):** Bir gün açıldıktan sonra içeriği yalnızca viewport'a 300px yaklaşınca mount edilir. Kullanıcı doğrudan tıklarsa anında render edilir (UX kuralı: kullanıcı eylemi → bekleme yok); ama scroll edilirken karşılaşılan gizli açık günler için placeholder gösterilir. `frontend/src/lib/utils/lazy-mount.svelte.ts`.
- **EUR bakiye lookup O(log n):** Aktivitesi olmayan günler için önceki bakiyeyi binary search ile bulur (`sortedBalanceDays` $derived). Eski sürüm her açık gün için `Object.keys().sort()` çağırıyordu — 200+ gün açıldığında O(n²·log n) → scroll donması.

### Kullanılan Bileşenler
- `Modal.svelte` — Ekleme/düzenleme formu
- `ConfirmDialog.svelte` — Silme onayı
- `MonthAccordion.svelte` — 3 seviyeli yıl/ay/gün akordiyonu + lazy mount
- `CashFlowItem.svelte` — Tek satır (mobile/desktop varyant)
- `lazy-mount.svelte.ts` — `IntersectionObserver` tabanlı tek-seferlik Svelte action
- `api.ts` — HTTP istekleri
- `showToast` — Bildirim gösterimi

## Audit Log Entegrasyonu

Tüm CRUD işlemleri `audit_logs` tablosuna kaydedilir:
- **entity_type:** `"cash_flow"`
- **Kaydedilen eylemler:** `create`, `update`, `delete`
- **details:** `"{type}: {title} - {amount}"` (create/delete için)

## Geliştirme Kuralları

1. **Type alanı** yalnızca `"income"` veya `"expense"` olabilir — Pydantic şemasında regex ile kontrol edilir
2. **Amount** sıfırdan büyük olmalıdır (`gt=0`)
3. **Hard delete** uygulanır (soft delete yok) — silinen kayıtlar tamamen kaldırılır
4. **creator ilişkisi** `joinedload` ile yüklenir — N+1 sorgu önlenir
5. **`_build_response`** helper fonksiyonu ile tutarlı yanıt oluşturulur
6. **Para formatı:** `Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' })`
7. **Tarih formatı:** `toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })`
