# Muhasebe ve İnsan Kaynakları Modülleri

## Genel Bilgi

| Alan | Muhasebe | İnsan Kaynakları |
|---|---|---|
| **Modül kodu** | `accounting` | `hr` |
| **Alt modüller** | `accounting.taxes`, `accounting.recurring`, `accounting.rent_income`, `accounting.rent_expense`, `accounting.dividend` | `hr.salary`, `hr.withholding`, `hr.sgk` |
| **Frontend rota** | `/dashboard/muhasebe/...` | `/dashboard/ik/...` |
| **Backend prefix** | `/api/accounting/...` | `/api/hr/...` |

## Mimari Karar: Ortak Tablo Yaklaşımı

Tüm 4 alt modül aynı CRUD pattern'ını kullandığı için:
- **1 tanım tablosu** (`scheduled_definitions`) — `source_type` ile ayrışır
- **1 giriş tablosu** (`scheduled_entries`) — `source_type` + `definition_id`
- **1 ortak router fabrikası** (`scheduled_base.py`) — `create_scheduled_router()`
- **1 ortak UI bileşeni** (`ScheduledModule.svelte`) — props ile özelleşir

Neden? Ayrı model + schema + router + page yerine tekrar kullanılabilir yapı.
Yeni bir planlı gider/gelir türü eklemek 5 dakika sürer.

### Direction Parametresi
`create_scheduled_router()` ve `generate_entries()` fonksiyonlarına `direction` parametresi eklendi.
- `direction=-1` (varsayılan): Gider — vergi, düzenli ödeme, maaş, stopaj, verilen kira
- `direction=+1`: Gelir — alınan kira
Bu değer `finance_events.direction` kolonuna yazılır ve nakit akımda doğru yönde gösterilir.

## Veritabanı Şeması

### scheduled_definitions
| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| source_type | VARCHAR(30) | `tax`, `recurring`, `salary`, `withholding` |
| name | VARCHAR(200) | Tanım adı |
| category | VARCHAR(100) | Vergi türü / Kategori (nullable) |
| amount | NUMERIC(15,2) | Dönemsel tutar |
| currency | VARCHAR(3) | Para birimi (TRY) |
| frequency | VARCHAR(20) | `monthly`, `quarterly`, `yearly` |
| payment_day | INTEGER | Ödeme günü (1-28) |
| start_month | INTEGER | Başlangıç ayı (1-12) |
| year | INTEGER | Yıl |
| notes | TEXT | Notlar |
| is_active | BOOLEAN | Aktif mi? |
| created_by | FK users | Oluşturan |
| created_at, updated_at | TIMESTAMPTZ | |

### scheduled_entries
| Kolon | Tip | Açıklama |
|---|---|---|
| id | BIGSERIAL PK | |
| definition_id | FK scheduled_definitions | CASCADE silme |
| source_type | VARCHAR(30) | Denormalize (tanımdan kopyalanır) |
| entry_date | DATE | Planlanan ödeme tarihi (nakit akımda görünen tarih) |
| period_month | INTEGER | Girişin dönem ayı (1-12) — UI'da "Dönem" kolonu |
| period_year | INTEGER | Girişin dönem yılı |
| amount | NUMERIC(15,2) | Tutar (tanımdan kopyalanır, düzenlenebilir) |
| currency | VARCHAR(3) | |
| description | TEXT | Nakit akımda görünen açıklama |
| is_paid | BOOLEAN | Ödendi mi? |
| paid_date | DATE | Gerçekleşen ödeme tarihi (varsa nakit akım `event_date` olur) |
| notes | TEXT | |

**Dönem vs Ödeme Tarihi ayrımı:**
- `period_month/period_year` = "hangi ayın kaydı" (ör. Nisan 2026 maaşı)
- `entry_date` = gerçek ödeme tarihi (nakit akımda ne zaman görünecek)
- `salary`, `sgk`, `withholding` için otomatik kural: dönemin ödemesi **bir sonraki ayın** `payment_day`'inde yapılır (ör. Nisan maaşı 5 Mayıs'ta ödenir).
- Diğer kaynak tipler (`tax`, `recurring`, `rent_*`, `dividend`) için `entry_date` aynı ayın içindedir, `period_month` = `entry_date` ayı.

**Açıklama formatı (nakit akımda görünür):**
- `[Maaş] Nisan 2026 — 2026 Maaş` — prefix + dönem + definition adı
- `_build_description(source_type, defn_name, category, period_month, period_year)` helper'ı üretir
- Dönem güncellendiğinde (`PATCH /entries/{id}` ile `period_month` değişirse) açıklama otomatik yeniden oluşturulur ve `finance_events.description` senkronize edilir

## FinanceEvent Entegrasyonu

| source_type | Açıklama | Direction |
|---|---|---|
| `tax` | Vergi girişi | EXPENSE (-1) |
| `recurring` | Düzenli ödeme girişi | EXPENSE (-1) |
| `salary` | Maaş girişi | EXPENSE (-1) |
| `withholding` | Stopaj girişi | EXPENSE (-1) |
| `rent_income` | Alınan kira girişi | INCOME (+1) |
| `rent_expense` | Verilen kira girişi | EXPENSE (-1) |
| `sgk` | SGK prim girişi | EXPENSE (-1) |
| `dividend` | Temettü girişi | EXPENSE (-1) |

- `is_realized = is_paid` → Ödenmişler gerçekleşmiş olarak görünür
- `is_matched = False` → Nakit akımda her zaman görünür
- Tanım silindiğinde tüm girişlerin finance_event'leri `invalidate()` ile kaldırılır

## API Endpoint'leri

Her alt modül aynı endpoint setini sunar (prefix değişir):

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/{prefix}/` | view | Tanım listesi (yıl filtreli, girişler dahil) |
| GET | `/{prefix}/{id}` | view | Tanım detayı + girişler |
| POST | `/{prefix}/` | use | Yeni tanım + otomatik giriş üretimi |
| PATCH | `/{prefix}/{id}` | use | Tanım güncelle (tutar değişirse girişler yenilenir) |
| DELETE | `/{prefix}/{id}` | use | Tanım + tüm girişler sil |
| PATCH | `/{prefix}/entries/{id}` | use | Tek giriş düzenle (tutar, `period_month`, `period_year`, `entry_date` ödeme tarihi, `paid_date` ödendi tarihi, `is_paid`, not) — nakit akım `event_date` = `paid_date` varsa, yoksa `entry_date` (her değişiklikte otomatik senkronize olur) |
| GET | `/{prefix}/summary/totals` | view | Özet (toplam, ödenen, bekleyen) |

### Prefix'ler
- Vergiler: `/api/accounting/taxes`
- Düzenli Ödemeler: `/api/accounting/recurring`
- Alınan Kiralar: `/api/accounting/rent-income`
- Verilen Kiralar: `/api/accounting/rent-expense`
- Temettü: `/api/accounting/dividend`
- Maaş: `/api/hr/salary`
- Stopaj: `/api/hr/withholding`
- SGK: `/api/hr/sgk`

## Giriş Üretme Mantığı

1. Tanım oluşturulduğunda `generate_entries()` çağrılır
2. `start_month`'dan yıl sonuna kadar girişler üretilir:
   - **monthly**: Her ay bir giriş
   - **quarterly**: 3 ayda bir giriş  
   - **yearly**: Tek giriş
3. Tanım tutarı değiştiğinde `regenerate_entries()`:
   - Ödenmemiş girişleri siler
   - Yeni tutarla yeniden üretir
   - Ödenmişlere dokunmaz

## Frontend Bileşeni

`ScheduledModule.svelte` — Ortak UI bileşeni:
- Yıl seçici
- Özet kartları (toplam, ödenen, bekleyen)
- Tanım listesi (accordion görünüm)
- Her tanımda aylık giriş tablosu (dönem, tutar, durum, ödeme tarihi, not)
- Giriş başına inline düzenleme (kalem ikonu ile tutar, ödeme tarihi, not düzenlenebilir)
- Giriş başına ödendi/ödenmedi toggle
- Ödeme tarihi girildiğinde otomatik olarak "ödendi" olarak işaretlenir
- Tanım ekleme/düzenleme modal
- Silme onay modal

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/models/scheduled.py` | ScheduledDefinition + ScheduledEntry modelleri |
| `app/schemas/scheduled.py` | Pydantic şemaları |
| `app/routers/scheduled_base.py` | Generic CRUD router fabrikası |
| `app/routers/accounting/__init__.py` | Muhasebe router (taxes + recurring) |
| `app/routers/hr/__init__.py` | İK router (salary + withholding) |
| `app/utils/entry_generator.py` | Giriş üretme/yenileme mantığı |
| `app/utils/finance_event_service.py` | `upsert_scheduled_entry()` metodu |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/lib/components/ScheduledModule.svelte` | Ortak UI bileşeni |
| `src/routes/dashboard/muhasebe/vergiler/+page.svelte` | Vergiler sayfası |
| `src/routes/dashboard/muhasebe/duzenli-odemeler/+page.svelte` | Düzenli ödemeler sayfası |
| `src/routes/dashboard/muhasebe/alinan-kiralar/+page.svelte` | Alınan kiralar sayfası |
| `src/routes/dashboard/muhasebe/verilen-kiralar/+page.svelte` | Verilen kiralar sayfası |
| `src/routes/dashboard/muhasebe/temettu/+page.svelte` | Temettü sayfası |
| `src/routes/dashboard/ik/maas/+page.svelte` | Maaş sayfası |
| `src/routes/dashboard/ik/stopaj/+page.svelte` | Stopaj sayfası |
| `src/routes/dashboard/ik/sgk/+page.svelte` | SGK sayfası |

## Onay Akışı — Pasif Kayıt Oluşturma

### Sorun
Yeni kayıt oluşturulduğunda onay gerekliyse kayıt veritabanına yazılmıyordu. Kullanıcı ekranda hiçbir şey göremiyordu, dolayısıyla aynı kaydı tekrar girip girmediğini anlayamıyordu.

### Çözüm
Onay gereken "create" işlemlerinde kayıt `is_active=False` olarak veritabanına yazılır. Listede turuncu "Onayda" etiketi ile görünür. Onay verildiğinde `is_active=True` yapılır ve girişler üretilir.

### Akış
1. `POST /` → `check_approval()` çağrılır
2. Onay gerekiyorsa:
   - `ScheduledDefinition` `is_active=False` olarak oluşturulur (girişler üretilmez)
   - `ApprovalRequest.entity_id` yeni kaydın ID'si ile güncellenir
   - 202 Accepted döner
3. Frontend listede turuncu arka plan + "Onayda" badge gösterir
4. Onaylandığında: `approval_executor` pasif kaydı aktifleştirir + `generate_entries()` çağırır
5. Reddedildiğinde / iptal edildiğinde: `cleanup_rejected_or_cancelled()` pasif kaydı siler

### Etkilenen Dosyalar
- `backend/app/routers/scheduled_base.py` — POST endpoint'inde pasif kayıt oluşturma
- `backend/app/utils/approval_executor.py` — `_handle_scheduled` create handler + `cleanup_rejected_or_cancelled()`
- `backend/app/routers/approval/requests.py` — reject/cancel endpoint'lerinde cleanup çağrısı
- `frontend/src/lib/components/ScheduledModule.svelte` — Pasif kayıt gösterimi (turuncu tema, expand engeli)
