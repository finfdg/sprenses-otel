# Muhasebe ve İnsan Kaynakları Modülleri

## Genel Bilgi

| Alan | Muhasebe | İnsan Kaynakları |
|---|---|---|
| **Modül kodu** | `accounting` | `hr` |
| **Alt modüller** | `accounting.taxes`, `accounting.recurring`, `accounting.rent_income`, `accounting.rent_expense`, `accounting.dividend` | `hr.salary`, `hr.withholding`, `hr.sgk` |
| **Frontend rota** | `/dashboard/muhasebe/...` | `/dashboard/ik/...` |
| **Backend prefix** | `/api/accounting/...` | `/api/hr/...` |

## Mimari Karar: Ortak Tablo Yaklaşımı

Tüm alt modüller (muhasebe: vergi/düzenli ödeme/alınan kira/verilen kira/temettü + İK: maaş/stopaj/SGK) aynı CRUD pattern'ını kullandığı için:
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
| vendor_id | FK vendors (SET NULL) | **Cari (satıcı) bağlantısı** — yalnız `recurring` için anlamlı. Bağlıysa girişler cari gerçek faturayla senkronlanır (ör. Elektrik→CK, Su→ASAT) |
| billing_offset_months | INTEGER (0) | **Fatura gecikmesi (ay)** — fatura tüketim ayından sonra kesiliyorsa kaç ay geri kaydırılır. Su (ASAT) ay başı = önceki ay → **1**; elektrik (CK) ay sonu = aynı ay → **0** |
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
| synced_from_cari | BOOLEAN | **True → tutar/ödeme cari gerçek faturadan senkronlandı** (tahmini değil). Bu aylarda recurring FE silinir (çift sayım önleme) |

**Dönem vs Ödeme Tarihi ayrımı:**
- `period_month/period_year` = "hangi ayın kaydı" (ör. Nisan 2026 maaşı)
- `entry_date` = gerçek ödeme tarihi (nakit akımda ne zaman görünecek)
- `salary`, `sgk`, `withholding` için otomatik kural: dönemin ödemesi **bir sonraki ayın** `payment_day`'inde yapılır (ör. Nisan maaşı 5 Mayıs'ta ödenir) — `entry_generator.SHIFT_NEXT_MONTH_SOURCES`.
- Diğer kaynak tipler (`tax`, `recurring`, `rent_*`, `dividend`) için `entry_date` **varsayılan** aynı aydadır.
- **Tanım-bazlı `pay_next_month` (2026-07-04):** Bu türlerde de tanımda **"Ödeme bir sonraki ay yapılır"** işaretlenirse dönemin ödemesi bir sonraki ayın `payment_day`'inde yapılır (ör. Elektrik Ocak dönemi → 10 Şubat; faturalar tüketimden sonraki ay ödenir). `ScheduledDefinition.pay_next_month` (migration `b4f7e2a9c1d3`) → `_payment_date(..., pay_next_month)`; `_REGEN_FIELDS`'te olduğundan **değişince girişler yeniden üretilir** (yeni tarihler). UI: ScheduledModule tanım formunda checkbox (salary/sgk/withholding'de gösterilmez — zaten kaynak-bazlı kayar). **Canlı:** "2026 Elektrik" (id 8, `payment_day=10`) `pay_next_month=True` yapıldı; 12 girişi (ödenmişler dahil) +1 ay kaydırıldı. Test: `test_scheduled_base.py::TestPayNextMonth`.

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

## Cari Senkronu (Düzenli Ödemeler ↔ Cari) — 2026-06-06

**Sorun:** Düzenli Ödemeler'deki bazı kalemler (elektrik faturaları → **CK AKDENİZ ELEKTRİK**,
su → **ASAT**) **tahmini** tutarlarla planlanır. Oysa gerçek fatura geldiğinde tutar carinin
(320 satıcı) o ayki hareketine yazılır ve ödeme oradan yapılınca düşer. İki yer **divergedu**;
ayrıca aynı borç hem `recurring` hem `vendor_payment` olarak nakit akımda **çift sayılıyordu**.

**Çözüm — cari bağlantısı + tek-yönlü senkron (`utils/recurring_vendor_sync.py`):**
- `scheduled_definitions.vendor_id` ile bir düzenli ödeme bir cariye bağlanır (yalnız `recurring`;
  `enable_vendor_sync=True` fabrikada). Canlı: "2026 Elektrik"→CK (v707), "2026 Su"→ASAT (v697).
- **Fatura gecikmesi (`billing_offset_months`) — tüketim ayı ≠ fatura tarihi:** Bazı abonelikler
  tüketim ayından SONRA faturalanır. **Su (ASAT)** faturası ay başında gelir = **önceki ay** tüketimi
  (3 Haz faturası = Mayıs su) → offset **1**. **Elektrik (CK)** ay sonunda faturalanır = aynı ay
  (31 May = Mayıs) → offset **0**. Sync, faturayı `tarih − offset` ay'a (tüketim dönemine) atar
  (`_shift_period`). Tanım/edit modalinde "Fatura gecikmesi (ay)" alanından ayarlanır.
- `sync_recurring_from_vendors(db)` her bağlı tanımın aylık girişini cari verisiyle eşler
  (tüketim dönemi = carinin alacak hareketinin tarihi − `billing_offset_months`):
  - **Faturası gelen ay** → `entry.amount` = carinin o ay **toplam faturası** (tahminin yerine GERÇEK);
    `is_paid` = cari **net-borç FIFO**'ya (`calculate_fifo_amounts`) göre o ayın faturaları tamamen
    kapandıysa True; `synced_from_cari=True`; **recurring finance_event'i `invalidate` edilir** →
    cari `vendor_payment` zaten nakit akımı temsil ettiğinden çift sayım kalkar.
  - **Faturası gelmemiş (gelecek) ay** → **tahmini** kalır (FE korunur → nakit akım projeksiyonu).
  - Daha önce senkronlanmış ay faturasını kaybederse (cari silme) → tahmine geri döner + FE yeniden.
- **Tetikleme (iki yol):** (a) Topbar'daki merkezi **Sedna** butonu — cari içe aktarımdan SONRA
  `recurring_sync` adımı otomatik çalışır (`sedna_sync.py:_STEPS`); (b) Düzenli Ödemeler sayfasındaki
  **"Cari ile Senkronize"** butonu (`POST /accounting/recurring/sync-vendors`). İkisi de idempotent.
  **Onaydan muaf** (operasyonel; cari verisi zaten muhasebede onaylı — Sedna içe aktarmaları gibi),
  audit'li (`recurring_vendor_sync`); izin `accounting.recurring` use.
- **Neden cari görünür kalır, recurring gizlenir:** cari net-borç FIFO'su haftalık **ödeme planını**
  besler (gerçek vadeler, kısmi ödemeler, roll-over). Recurring yalnız tahmin → senkron ayda gizlenir.
- **Frontend:** Düzenli Ödemeler'de cari-bağlı kalemde cari adı rozeti (🔗) + senkron girişte
  "gerçek" rozeti; tanım başlığındaki "… / dönem" tahmin referansı olarak kalır.
- **Kanıt (canlı):** "2026 Elektrik" ve "2026 Su" `start_month=1` (Ocak başlangıç) yapıldı → 12 ay.
  Elektrik **Oca–May gerçek** (Oca 457K + Şub 320K cari FIFO'ya göre **ödendi**; Mar–May açık),
  Haz–Ara tahmini 1,5M. Su **Oca–Haz gerçek** (Oca–Mar ödendi), Tem–Ara tahmini. Senkron ayların
  recurring FE'si silindi (çift sayım giderildi); gelecek ayların tahmini FE'si korundu.
  Su (offset=1): Oca 222K · Şub 167K · Mar 1,27M · Nis 932K · **May 1,20M** (3 Haz faturası) — kayma
  düzeltildi (eskiden tarih ayına göre eşlenince 1 ay kayıktı).
- **start_month düzenlenebilir:** Tanımın başlangıç ayı (`start_month`) PATCH ile değiştirilince
  girişler yeniden üretilir; cari-bağlıysa otomatik yeniden senkronlanır (fabrika + onay executor).
- Test: `tests/test_recurring_vendor_sync.py` (tutar/ödeme/FE-silme/gelecek-tahmini/revert/endpoint/start_month/**fatura-gecikmesi**).

## API Endpoint'leri

Her alt modül aynı endpoint setini sunar (prefix değişir):

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/{prefix}/` | view | Tanım listesi (yıl filtreli, girişler dahil) |
| GET | `/{prefix}/{id}` | view | Tanım detayı + girişler |
| POST | `/{prefix}/` | use | Yeni tanım + otomatik giriş üretimi |
| PATCH | `/{prefix}/{id}` | use | Tanım güncelle (`amount`/`frequency`/`payment_day`/**`start_month`** değişirse girişler yeniden üretilir — ödenmemişler silinip yeniden; ödenmişler korunur. Cari-bağlı `recurring` ise regenerate sonrası **otomatik yeniden senkronlanır**) |
| DELETE | `/{prefix}/{id}` | use | Tanım + tüm girişler sil |
| PATCH | `/{prefix}/entries/{id}` | use | Tek giriş düzenle (tutar, `period_month`, `period_year`, `entry_date` ödeme tarihi, `paid_date` ödendi tarihi, `is_paid`, not) — nakit akım `event_date` = `paid_date` varsa, yoksa `entry_date` (her değişiklikte otomatik senkronize olur) |
| GET | `/{prefix}/summary/totals` | view | Özet (toplam, ödenen, bekleyen) |
| POST | `/recurring/sync-vendors` | use | **Yalnız Düzenli Ödemeler** — cari-bağlı kalemleri cari gerçek fatura + ödeme durumuyla senkronla (idempotent). Bk. *Cari Senkronu* bölümü |

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

## Çok Yıllı Yapılandırma / Değişken Tutarlı Ödeme Planı Modellemesi (2026-07-06)

Vergi/SGK **yapılandırma (tecil) ödeme planları** modülün "tek yıl + sabit aylık tutar"
varsayımına uymaz: taksitler **birden çok yıla yayılır** ve **her taksit farklı tutardadır**
(tecil faizi her ay arttığından "Toplam Tutar" büyür). Bu tür planlar şöyle modellenir:

- **Yıl başına bir `ScheduledDefinition`** (liste/özet endpoint'leri `ScheduledDefinition.year`
  ile filtreler → her yıl kendi tanımını görmeli). Örn. SGK 2026-2030 = 5 tanım, vergi 2026-2029 = 4 tanım.
  Tanımlar **aynı `name`** taşır (yalnız `year` farklı) → modülde tek plan gibi görünür.
- **Her taksit için elle `ScheduledEntry`** — `entry_date` = resmi ödeme günü, `amount` = belgedeki
  **Toplam Tutar** sütunu (taksit tutarı + tecil faizi), `period_month/year` = ödeme ayının
  takvim ay/yılı. `generate_entries` KULLANILMAZ (o sabit `defn.amount`'u tek `payment_day`'e yazar;
  değişken tutar/tarihleri bozar). Her giriş sonrası `finance_event_svc.upsert_scheduled_entry(..., direction=-1)`.
- **DİKKAT — düzenleme regen riski:** Bu tanımların `amount`/`frequency`/`payment_day`/`start_month`/
  `pay_next_month` alanı UI'dan **düzenlenmemelidir** — `scheduled_service.apply_definition_update`
  bu alanlar değişince `regenerate_entries` çağırır → **ödenmemiş elle girişleri silip sabit tutarla
  yeniden üretir** (yapılandırma tablosu bozulur). Yalnız tek taksitin düzenlenmesi (`PATCH /entries/{id}`,
  ör. "Ödendi" işaretleme) güvenlidir. Tutar değişecekse ilgili girişi tek tek düzenle.
- Uygulamalar (`MURAT-A TURİZM A.Ş.`, tümü `pending`, taranmış resmi ödeme planlarından):
  - **SGK** (KART 00000441, 48 taksit, ₺7.799.133,30) — yıl-bazlı 5 tanım (2026-2030).
  - **Vergi — İKİ AYRI plan** (SERİ:B No:20, Manavgat V.D., aynı vade takvimi 30.09.2026→31.08.2029,
    her biri yıl-bazlı 4 tanım 2026-2029): **Plan A** (Dosya …Ldh0000001, borç ₺3.313.038,93,
    36×₺92.028, genel Toplam ₺5.015.163,41) + **Plan B** (Dosya …Ldh0000002, borç ₺98.375,72,
    36×₺2.732, genel Toplam ₺148.917,61). **Ders:** İlk taranan vergi belgesi iki planın sayfalarını
    karıştırmıştı (Plan A sayfa 1 + Plan B sayfa 2) → tek-plan sanılıp oluşturulmuş, sonra geri alınıp
    tam belgelerle iki ayrı plan olarak yeniden yapıldı. Farklı **Tecil Dosya Numarası** ayırt edicidir;
    sayfa-2 "Toplam" satırı (36×taksit) tek-sayfanın kendi planına ait olduğunun kanıtıdır.
  - **Otel Sigortası (Allianz Modüler Kurumsal, Poliçe 0001-1110-01151205)** — yapılandırma değil
    ama aynı desende (değişken tutar → elle giriş): 1 yıllık poliçe (16.03.2026–16.03.2027), **tek yıl
    (2026)** olduğundan **tek `ScheduledDefinition`** ("2026 Otel Sigortası", id 751, `source_type=recurring`).
    9 giriş: **Peşinat ₺659.201,22 (18.03)** + **8×₺247.199,00 (18.04→18.11)** = brüt prim **₺2.636.793,22**
    (tutar-doğrulama: peşinat + 8 taksit = brüt prim ✓). Peşinat/taksit ayrımı `notes`'ta; `vendor_id=NULL`
    (cari senkronu yok — Sedna 320 carisiyle ilgisiz). `payment_day=18`/`start_month=3` gerçeğe uygun set
    edildi ama **girişler elle** (regen etmeyin — peşinat ayrı tutar + Aralık girişi olmadığından
    `generate_entries` bozardı).
    - **Ödeme mutabakatı (Yapı Kredi TL, hesap 3):** Peşinat + 1. Taksit **20.04.2026 toplu**
      ₺906.400,22 (banka tx 4779, açıklama "…01151205 ALLIANZ SİGORTA") · 2. Taksit 18.05 (tx 5146) ·
      3. Taksit 18.06 (tx 5590). Bu 4 giriş "Ödendi" işaretlendi ve **banka hareketleriyle `match()`
      edildi → recurring FE'leri `is_matched=True` (GİZLİ), banka bacağı görünür** (çift-sayım yok,
      ödenen-çek deseni). Toplu ödemede iki giriş (peşinat+1.taksit) TEK banka tx'ine (4779) eşlendi
      (2→1). 4.–8. Taksit (18.07→18.11) `pending`, nakit-akım projeksiyonunda görünür.

### Yıl seçici — dinamik (2026-07-06 hata düzeltmesi)

`ScheduledModule.svelte` yıl açılır menüsü **`[2025, 2026, 2027]` olarak sabit yazılıydı** → çok yıllı
verinin (ör. SGK yapılandırması 2028-2030) yılları menüde görünmüyor, o yıllardaki taksitlere
erişilemiyordu (veri var ama seçici gizliyor — 8 planlı modülün tümü için latent hata).

**Çözüm:** Yıl listesi artık **veriden türetilir** (single source of truth):
- Backend: `create_scheduled_router` fabrikasına `GET /years` eklendi → o `source_type` için distinct
  `ScheduledDefinition.year` döner. **`/{defn_id}` path-param rotasından ÖNCE tanımlı** (yoksa FastAPI
  "years"i int defn_id sanar). Tüm 8 modül (taxes/recurring/rent×2/salary/withholding/sgk; dividend ayrı
  router → 404'te frontend zarifçe fallback yapar) otomatik alır.
- Frontend: `loadYears()` `${apiPrefix}/years`'i çeker, cari yıl ±1 penceresiyle birleştirip (`availableYears`)
  dropdown'u doldurur; `onMount` + `finance_updated` WS event'inde yenilenir. Fetch hata verirse base
  pencereye düşer (boş/erişimsiz modülde de kullanılabilir kalır).
