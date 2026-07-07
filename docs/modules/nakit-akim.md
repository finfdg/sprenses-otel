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
| `backend/app/routers/finance/cash_flow/eur_balances.py` | EUR bakiye endpoint'i + `compute_eur_balances(db)` ortak çekirdeği |
| `backend/app/routers/finance/cash_flow/report.py` | Nakit akım PDF raporu endpoint'i (ay/gün bazlı EUR tablosu) |
| `backend/app/routers/finance/cash_flow/runway.py` | Runway / nakit koruma projeksiyonu endpoint'i (ay-içi planlı hareketler EUR) |
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
| `GET` | `/api/finance/cash-flow/report/pdf` | `view` | Ay/gün bazlı nakit akım PDF raporu (`start_date`/`end_date` opsiyonel) |
| `GET` | `/api/finance/cash-flow/t-account` | `view` | T hesap cetveli — `period=daily\|weekly\|monthly\|yearly` + `offset<=0`; giriş/çıkış grupları EUR (transfer hariç, `skipped_no_rate` sayaçlı) |
| `GET` | `/api/finance/cash-flow/runway` | `view` | Runway / nakit koruma projeksiyonu — içinde bulunulan ay; `start_eur` bugünkü banka nakdi + ay-içi planlı hareketler (`inflows`/`outs`, EUR; transfer hariç, `skipped_no_rate` sayaçlı). `overdue` = vadesi geçen ödenmemiş kalemler (orijinal tarih); her out/overdue/inflow kaleminde `deferred: bool` + `original_date` |
| `POST` | `/api/finance/cash-flow/defer` | `use` | Bir ödeme kalemini KALICI öteler / öteleme kaldırır (onaysız+audit+WS; body `{source_type, source_id, deferred_to: "YYYY-MM-DD"\|null}`; null→siler; bank HARİÇ) |
| `GET` | `/api/finance/cash-flow/credit-payments-unpaid` | `view` | Ödenmemiş kredi taksitleri listesi |
| `GET` | `/api/finance/cash-flow/cc-statements-unpaid` | `view` | Ödenmemiş kredi kartı ekstreleri listesi |
| `POST` | `/api/finance/cash-flow/match-vendor-tx` | `use` | Cari işlem eşleştirme |
| `POST` | `/api/finance/cash-flow/match-cc-payment` | `use` | Kredi kartı ödeme eşleştirme |
| `POST` | `/api/finance/cash-flow/match-credit-payment` | `use` | Kredi taksit ödeme eşleştirme |
| `POST` | `/api/finance/cash-flow/unmatch-cc-payment` | `use` | Kredi kartı eşleştirme iptali |

### Query Parametreleri (GET list)
- `page` (int, default: 1)
- `page_size` (int, default: 100, max: 2000) — 2000+ kayıtta frontend truncation uyarısı gösterir (sessiz kayıp yok); varsayılan yıl filtresiyle ilk yükleme hafif
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
- **`cashFlowCache` (lib/stores/cashflow.svelte.ts) — oturum-içi cache + WS geçersizlemesi (2026-07-07):**
  `items`/`categories`/`eurBalances` navigasyonlar arasında yaşar (5 dk TTL). `finance_updated` WS
  event'i **store seviyesinde** (sayfa bağımsız, modül-scope `onWsEvent`) tazelik damgalarını
  (`lastFetchedAt` + `eurBalancesFetchedAt`) sıfırlar — **fetch yapmaz**; bir sonraki mount
  `isStale()`/`isEurBalancesStale()` üzerinden veriyi kendisi çeker. Sebep: event yalnız mount'lu
  sayfa handler'larında tüketiliyordu; kullanıcı Bankalar'da ekstre yüklerken event kayboluyor,
  Panel'e dönüşte `CashFlowTAccount` mount guard'ı ("yalnız boşsa çek") dolu-ama-eski `eurBalances`
  ile RunwayChart'ı bayat çiziyordu (F5'e kadar). Mount guard artık `isEurBalancesStale()` kullanır.
  Test: `src/lib/stores/cashflow.test.ts` (7 test — TTL/geçersizleme/emitLocal kablolaması).

### Performans / Lazy Mount
- **3 seviyeli `{#if}` lazy render** — yıl/ay/gün başlıkları haricinde içerik (CashFlowItem) yalnızca kullanıcı bir günü açtığında render edilir.
- **Başlangıç açık günü:** Yalnızca bugüne (veya matchDate'e) en yakın gün otomatik açılır; geri kalan tüm günler kapalı kalır → 2000 item olsa bile initial paint hafif kalır.
- **Day-content lazy mount (`use:lazyMount`):** Bir gün açıldıktan sonra içeriği yalnızca viewport'a 300px yaklaşınca mount edilir. Kullanıcı doğrudan tıklarsa anında render edilir (UX kuralı: kullanıcı eylemi → bekleme yok); ama scroll edilirken karşılaşılan gizli açık günler için placeholder gösterilir. `frontend/src/lib/utils/lazy-mount.svelte.ts`.
- **EUR bakiye lookup O(log n):** Aktivitesi olmayan günler için önceki bakiyeyi binary search ile bulur (`sortedBalanceDays` $derived). Eski sürüm her açık gün için `Object.keys().sort()` çağırıyordu — 200+ gün açıldığında O(n²·log n) → scroll donması.

### Gün İçi Kaynak Gruplaması — Çek / Cari / Kredi / KK (2026-07-02)
- **Frontend (görsel):** Bir gün içinde aynı kaynaktan 2+ kayıt varsa, o kaynak tek
  **katlanabilir grup kartında** toplanır (varsayılan KAPALI, tıklayınca `CashFlowItem` satırları açılır):
  `check` → "Verilen Çekler" (turuncu) · `vendor_payment` → "Cari Ödemeleri" (mor) ·
  `credit` → **"Kredi / Leasing Taksitleri"** (indigo — leasing bir kredi ürün TİPİdir, taksitleri
  `source='credit'` gelir, ayrı kaynak değildir) · `cc_payment` → "KK Borç Ödemeleri" (pembe).
  Tek kayıt gruplanmaz; diğer kaynaklar (bank/advance/planlı) birebir listelenir. Grup, ilk
  üyesinin konumunda görünür (sıra korunur). Grup içindeki kredi/KK satırlarının tıkla-eşleştir
  etkileşimi (onCCMatchStart) korunur — kullanıcı grubu açıp satıra tıklar.
  Toplam: tüm üyeler aynı (TRY-dışı) para birimindeyse native (€), karışıksa TL (`amount_try`).
  Helper: `finance.ts::groupDaySourceItems` (birim testli) · Bileşen: `CashFlowGroupCard.svelte` ·
  Entegrasyon: `MonthAccordion` 4 `{#each}` bloğu. Gün/ay toplamları DEĞİŞMEZ (groupByMonth aynen).
- **Backend (veri) — mevcut istisna:** `listing.py::_aggregate_vendor_payments` aynı
  `(vendor_id, tarih)` cari ödeme satırlarını SQL sayfalamasından SONRA firma başına TEK satıra
  birleştirir (amount toplanır, `invoice_count` set edilir, >1 ise `tag_note="N fatura"`).
  Yani frontend'deki "Cari Ödemeleri" grubunun her satırı zaten firma-gün özetidir.
  Bilinen sınırlama: birleştirme sayfa-içi çalışır → aynı grup sayfa sınırına bölünürse iki ayrı
  satır görünebilir (page_size=2000 + yıl filtresi pratiğinde nadir).
- **`{#each}` key düzeltmesi:** Satır key'i `item.id` → `${item.source}-${item.id}` yapıldı —
  `id` kaynak tablonun ID'si olduğundan farklı kaynaklarda çakışabilir; dup-key yalnız client'ta
  crash/donma yaratır (bkz. Svelte dup-key bellek notu). Grup key'i: `g-${source}` (gün içinde tekil).

### Kullanılan Bileşenler
- `Modal.svelte` — Ekleme/düzenleme formu
- `ConfirmDialog.svelte` — Silme onayı
- `MonthAccordion.svelte` — 3 seviyeli yıl/ay/gün akordiyonu + lazy mount
- `CashFlowItem.svelte` — Tek satır (mobile/desktop varyant)
- `CashFlowGroupCard.svelte` — Gün içi çek/cari grup kartı (katlanabilir)
- `lazy-mount.svelte.ts` — `IntersectionObserver` tabanlı tek-seferlik Svelte action
- `api.ts` — HTTP istekleri
- `showToast` — Bildirim gösterimi

### PDF Rapor — "PDF Rapor" Butonu (2026-07-03)

Sayfa başlığındaki (PageHeader `actions`) **"PDF Rapor"** butonu, ekranda görüntülenen
ayların nakit akışını PDF olarak indirir.

- **Endpoint:** `GET /api/finance/cash-flow/report/pdf?start_date&end_date`
  (`finance.cash_flow` **view** — salt-okuma export, onaydan muaf, `heavy_limiter`'lı).
- **Kapsam ("ilgili ay") — 2026-07-03 netleştirildi:** Rapor, akordiyonda **açık
  (seçili) olan ayı** kapsar (Temmuz açıksa yalnız Temmuz). Kaynak:
  `MonthAccordion.getExpandedMonthKeys()` → `monthKeysToDateRange()` (`utils/finance.ts`,
  ilk ayın 1'i → son ayın son günü) → `start_date`/`end_date`. Birden çok ay açıksa
  hepsini kapsayan aralık; **hiçbir ay açık değilse** ekrandaki uygulanmış tarih
  filtresi (`cashFlowCache.filters`) kullanılır. Geçersiz tarih parametresi sessizce
  yok sayılır (`listing.py` toleransıyla aynı). Dosya adı tek ayda
  `nakit-akim-raporu-YYYY-MM.pdf`.
- **İçerik:** Her ay için başlık (Gider/Gelir/Ay Sonu Bakiye) + günlük satırlar
  (Tarih · Gider € · Gelir € · Bakiye €) + ay toplamı satırı; sonda genel toplam.
  Gün etiketi ekranla aynı biçimde ("1 Temmuz Çar" — locale bağımsız sabit listeler).
- **Sayı kaynağı — tek çekirdek:** Ekrandaki ay/gün başlıklarının EUR değerleri
  `eur-balances` endpoint'inden gelir; PDF de AYNI fonksiyonu
  (`eur_balances.compute_eur_balances(db)`) kullanır → rapor ile ekran birebir tutar.
  Ay toplamları rapora dahil edilen günlerden hesaplanır; ay bakiyesi = aralıktaki
  son günün bakiyesi.
- **Görsel dil:** Gider kırmızı, gelir yeşil, negatif bakiye kırmızı (ekranla tutarlı);
  başlık satırı teal (#0D9488); font `register_turkish_fonts()` (DejaVuSans — ₺/€ glyph).
- **Frontend gösterim (2026-07-03 düzeltildi):** `api.fetchRaw` → blob →
  **`PdfPreviewModal.svelte`** (paylaşılan bileşen — sayfa içi iframe önizleme +
  Yazdır/İndir/Kapat). İlk sürümdeki `<a download>` + `click()` deseni iPad
  Safari'de **"WebKitBlobResource hatası 1"** verdi (iOS, click handler'ı bittikten
  sonra blob'u yüklemeye çalışırken URL bağlamına erişemiyor) → talimatlar
  sayfasındaki kanıtlanmış modal-iframe çözümü ortak bileşene çıkarıldı; krediler
  PDF'i ve talimatlar da aynı bileşene geçirildi.
- **Test:** `tests/test_cash_flow_report.py` (8 test — geçerli PDF, tarih aralığı,
  boş aralık, geçersiz tarih toleransı, auth/izin, eur-balances refactor regresyonu).

## Audit Log Entegrasyonu

Tüm CRUD işlemleri `audit_logs` tablosuna kaydedilir:
- **entity_type:** `"cash_flow"`
- **Kaydedilen eylemler:** `create`, `update`, `delete`
- **details:** `"{type}: {title} - {amount}"` (create/delete için)

## Ödenen Çekler Listede Kalır — "Ödendi" Rozeti (2026-07-03)

Eskiden bankayla eşleşen (ödenen) çek, çift sayım gizlemesi (`is_matched=TRUE`) yüzünden
listeden tamamen KAYBOLUYORDU. Kullanıcı isteğiyle davranış değişti:

- **Görünürlük:** `GET /cash-flow/` eşleşmiş ÇEK kayıtlarını da döndürür
  (`OR (source_type='check' AND event_status='paid')`); yanıtta `is_matched: true` bayrağı.
  Çek DIŞI eşleşmiş kaynaklar (kredi, KK) eskisi gibi gizli.
- **Çift sayım korunur:** frontend `is_matched` kayıtları gün/ay toplamlarına ve gün içi
  çek grup kartının toplamına KATMAZ (`groupByMonth` + `groupDaySourceItems`); para
  hareketi banka bacağında sayılır. EUR başlık toplamları (`eur-balances`) değişmedi.
- **Görsel:** yeşil "Ödendi" rozeti (CashFlowItem'da zaten vardı) + kart `opacity-70`.
- **Gruplama (2026-07-04):** Bir günde 2+ ödenen çek varsa krediler gibi **katlanabilir
  "Ödenen Çekler · N kayıt" grubunda** toplanır (bekleyen "Verilen Çekler" grubundan AYRI;
  `groupDaySourceItems` grup anahtarı `check:matched`). Grup başlığında emerald "Ödendi"
  chip'i + tooltip ("tutarlar gün toplamına dahil değildir"); kart `opacity-75`.
  **DİKKAT:** MonthAccordion `{#each}` grup key'i `g-{source}{-matched}` — aynı günde
  bekleyen+ödenen çek grubu birlikteyken `g-check` çakışması Svelte dup-key donması
  yapar (bkz. bellek: svelte-each-dupkey-freeze); key'e matched eki ZORUNLU.
- **Tarih:** çek FE'si HER ZAMAN **vade tarihinde** gösterilir (`upsert_check`
  display_date=due_date; eskiden eşleşince banka tarihine taşınırdı). Mevcut 32 eşleşmiş
  FE 2026-07-03'te vadeye geri çekildi (tek seferlik UPDATE). Banka adı eşleşen hareketin
  bankası olmaya devam eder.
- Test: `test_finance.py::TestPaidChecksVisible` (liste + vade-tarihi) ve
  `finance.test.ts` ("is_matched toplam-dışı", grup kartı dışı).

## Geliştirme Kuralları

1. **Type alanı** yalnızca `"income"` veya `"expense"` olabilir — Pydantic şemasında regex ile kontrol edilir
2. **Amount** sıfırdan büyük olmalıdır (`gt=0`)
3. **Hard delete** uygulanır (soft delete yok) — silinen kayıtlar tamamen kaldırılır
4. **creator ilişkisi** `joinedload` ile yüklenir — N+1 sorgu önlenir
5. **`_build_response`** helper fonksiyonu ile tutarlı yanıt oluşturulur
6. **Para formatı:** `Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' })`
7. **Tarih formatı:** `toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })`

## Kredi Kartı Ekstresi Projeksiyonu (2026-07-04)

Yüklü ekstresi olmayan aylar için nakit akımda **tahmini** kredi kartı ekstre kalemleri gösterilir
(kartların kesim + son ödeme takvimi + worst-case borç). Böylece 5 kart her ay yüklenmese de nakit
planlaması eksik kalmaz.

- **Endpoint:** `GET /finance/cash-flow/cc-projections` (view; okuma-anında, kalıcı FE yazmaz).
  Servis: `app/services/cc_projection_service.py`.
- **Kural (kullanıcı kararı):**
  - **Cari ay**, gerçek ekstre yoksa → tutar = kart **limiti** (`total_amount`); worst-case rezerv,
    ay giderine **DAHİL** (nakit bakiye/projeksiyon bunu düşer).
  - **İleri aylar** (12 ay ufuk) → tutar = **0**; yalnız kesim + son ödeme tarih göstergesi.
  - Gerçek (yüklü) ekstresi olan due-ay atlanır — ekstre yüklenince projeksiyon otomatik kaybolur (WS).
- **"Ekstre yükleyin" günlük hatırlatıcısı (`projection_kind='cut'`):** YALNIZ **cari ayda**, kesim
  gününden (veya bugünden) son ödeme gününe kadar **her gün** amber "↑ Ekstre yükleyin" (tutar 0).
  Ekstre yüklenince o ay komple atlanır → hatırlatıcı kaybolur; ileri aylarda çıkmaz. Son ödeme
  kalemi ayrı (`'due'`).
- **Kesim/son-ödeme günü:** en son yüklü ekstreden türetilir (yoksa kart `details`); ay-uzunluğuna
  kırpılır; son ödeme günü kesimden küçükse ödeme sonraki aya taşar.
- **Kart limiti:** `CreditProduct.total_amount` (Garanti 100K, QNB 2M, VakıfBank 980K, YK 500K,
  **Halkbank 300K** — 2026-07-04 girildi). Limit yoksa cari ay tutarı 0.
- **EUR başlığı + Nakit Koruma (runway) + Panel T-Hesap:** cari-ay limit rezervi bu üç hesaba da
  eklenir (`due_reserve_projections`; `compute_eur_balances` EUR gidere, `runway.py` cari-ay OUT'a,
  `t_account.py` ÇIKIŞ "KK Borç Ödemeleri" grubuna) → tablo, EUR başlığı, runway ve Panel T-Hesap
  aynı rezervi gösterir.
- **Frontend:** `cashFlowCache.projectedItems` → `filteredItems`'a karışır (yalnız daraltıcı filtre
  yokken). `CashFlowItem` kesikli/soluk kart; `due`→"Tahmini · Ekstre yüklenmedi" + "Kesim · Son
  Ödeme" tarihleri, `cut`→"↑ Ekstre yükleyin"; tıklanamaz. Tahmini kalemler gün-içi KK grubuna
  katılmaz (ayrı satır).
- **Test:** `backend/tests/test_cc_projections.py` (16) + `finance.test.ts` projeksiyon testleri (3).

## Bekletme / Bekleme Listesi — Kalemi Toplam-Dışı Park Etme (2026-07-07)

Panel Nakit Akım (T-Hesap) kartındaki **"Beklet" option butonu** ile bir **bekleyen** kalem "beklemeye
alınır". **Kalem eski yerinde (giriş/çıkış listesinde) SARI kalır** ama **kolon toplamı / net /
projeksiyona etki etmez**. AYRICA ayrı **Bekleme Listesi**'nde (amber) da görünür. Yalnız
`finance.cash_flow` KULLANIM yetkisi olan görür/kullanır.

> **Kullanıcı düzeltmesi (2026-07-07):** Held kalem listeden **DÜŞMEZ** — yalnız toplamlara katılmaz
> ("eski yerinde sarı kalsın, sadece bakiyeye etkisi olmasın"). **Çek ödemeleri beklemeye alınamaz.**

- **Model/tablo:** `cash_flow_holds` (migration `a7d3f9b1e8c4`), doğal anahtar `(source_type, source_id)`.
  Servis `app/services/hold_service.py` (cache'li; `bank` + `check` HARİÇ → **14** holdable tür). **KK ekstre
  tahmini rezervi (`cc_projection`) de kart bazında bekletilebilir** (`source_id=CreditProduct.id`) — kırmızı
  "nakit yetmiyor" satırı projeksiyon olsa bile park edilebilsin (kullanıcı 2026-07-07).
- **Endpoint:** `POST /finance/cash-flow/hold-batch` `{items:[{source_type,source_id}], held}` — **onaysız**
  (operasyonel), `use` + audit (`cash_flow_hold`) + WS broadcast. Boş/`>5000` → 400.
- **Held kuralı:** `held ∧ not is_realized ∧ event_date ≥ bugün` → t_account item'da KALIR (`is_held=true`,
  sarı) ama `total_eur`/`totals`/`net`'e girmez (ayrı `held_eur`); eur_balances projeksiyonundan çıkar
  (bakiye düşmez); runway **`held`** dizisine girer (Bekleme Listesi).
- **Geçişler (doğal):** vade geçince → **Vadesi Geçenler** (held değil); ödenince (`is_realized`) →
  **Gerçekleşen** (normal sayılır). Ek kod yok.
- **Frontend:** `CashFlowTAccount.svelte` başlığında Beklet butonu → mod açıkken bekleyen satır tıklanınca
  toggle beklemeye al/geri al (`holdBatch`; toplu cari = tüm üyeler). Held satır **yerinde sarı** ("beklemede"
  rozeti); gün/kategori/kolon toplamları held'i hariç tutar. `HeldList.svelte` Bekleme Listesi'nde **her
  hareket tek tek "Geri al"**. Mod paylaşımlı `runway.svelte` (`holdMode`); WS ile T-Hesap canlı tazelenir.
- **Rate limit / 429 düzeltmesi (2026-07-07):** Hızlı ardışık Beklet/Geri al tıklamaları runway
  endpoint'inin eski `heavy_limiter`'ını (10/dk) tüketip "Nakit akım projeksiyonu yüklenemedi"
  toast'ları üretiyordu (her tıklama = doğrudan `loadRunway` + WS `finance_updated` yankısı = 2 istek).
  İki katmanlı çözüm: (1) `/cash-flow/runway` artık kendi **`runway_limiter`**'ını (30/dk) kullanır;
  (2) `runway.svelte.ts` **tekil-uçuş** korumalı — uçuş sırasındaki çağrılar tek trailing yenilemeye
  kuyruklanır, son yüklemeden `WS_ECHO_MS` (1500ms) içinde gelen WS event'i (kendi mutasyon yankısı) atlanır.
- **Test:** `backend/tests/test_cash_flow_hold.py` (26).
  Geliştirici detayı: `backend/app/routers/finance/CLAUDE.md` "Bekletme (Hold)".
