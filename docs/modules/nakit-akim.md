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
| `backend/app/routers/finance/cash_flow/matching.py` | Eşleştirme endpoint'leri (cari, kredi kartı, kredi) + eşleşme önerileri (accept/reject) + geri alma (unmatch-check/credit) + 1-N çek batch |
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
| `GET` | `/api/finance/cash-flow/t-account` | `view` | T hesap cetveli — `period=daily\|weekly\|monthly\|yearly` + `offset<=0`; giriş/çıkış grupları EUR (transfer hariç, `skipped_no_rate` sayaçlı). USD kalemler USD/EUR çaprazıyla çevrilir (`amount × USD alış / EUR alış`, `to_eur` hizası — 2026-07-19; runway `_event_eur` da aynı; öncesinde amount_try NULL olduğundan atlanıyorlardı, backend `finance/CLAUDE.md` "USD Kalemler" bölümü) |
| `GET` | `/api/finance/cash-flow/runway` | `view` | Runway / nakit koruma projeksiyonu — içinde bulunulan ay; `start_eur` bugünkü banka nakdi + ay-içi planlı hareketler (`inflows`/`outs`, EUR; transfer hariç, `skipped_no_rate` sayaçlı). `overdue`/`overdue_income` = vadesi geçen **VEYA bugün vadeli** ödenmemiş kalemler (`event_date <= today`, orijinal tarih; kullanıcı isteği 2026-07-16 — bugün vadeli ama ödenmemiş kalem bekleyen `outs`/`inflows`'ta değil, hemen Vadesi Geçenler'de). `t_account` da aynı sınırı kullanır (çift gösterim yok). Her out/overdue/inflow kaleminde `deferred: bool` + `original_date` |
| `POST` | `/api/finance/cash-flow/defer` | `use` | Bir ödeme kalemini KALICI öteler / öteleme kaldırır (onaysız+audit+WS; body `{source_type, source_id, deferred_to: "YYYY-MM-DD"\|null}`; null→siler; bank HARİÇ) |
| `GET` | `/api/finance/cash-flow/credit-payments-unpaid` | `view` | Ödenmemiş kredi taksitleri listesi |
| `GET` | `/api/finance/cash-flow/cc-statements-unpaid` | `view` | Ödenmemiş kredi kartı ekstreleri listesi |
| `POST` | `/api/finance/cash-flow/match-vendor-tx` | `use` | Cari işlem eşleştirme |
| `POST` | `/api/finance/cash-flow/match-cc-payment` | `use` | Kredi kartı ödeme eşleştirme |
| `POST` | `/api/finance/cash-flow/match-credit-payment` | `use` | Kredi taksit ödeme eşleştirme |
| `POST` | `/api/finance/cash-flow/unmatch-cc-payment` | `use` | Kredi kartı eşleştirme iptali |
| `POST` | `/api/finance/cash-flow/rematch` | `use` | Otomatik etiketleme + 5 eşleştiriciyi elle tetikler (ekstre yüklemesiyle aynı orkestratör; onaydan muaf — operasyonel; audit + WS) |
| `GET` | `/api/finance/cash-flow/match-suggestions` | `view` | Eşleşme önerileri listesi — otomatik eşik altındaki en iyi adaylar (skor sıralı, paginated) |
| `POST` | `/api/finance/cash-flow/match-suggestions/{id}/accept` | `use` | Öneriyi onayla → türe uygun `apply_*` / `close_entry_via_bank` ile gerçek eşleşme (hedef kapanmışsa 409 + öneri düşer) |
| `POST` | `/api/finance/cash-flow/match-suggestions/{id}/reject` | `use` | Öneriyi reddet (silinir; sonraki koşuda aynı çift yeniden önerilebilir) |
| `POST` | `/api/finance/cash-flow/unmatch-check` | `use` | Banka↔çek eşleşmesini geri al (çek `pending`'e döner, banka hareketi serbest kalır) |
| `POST` | `/api/finance/cash-flow/unmatch-credit-payment` | `use` | Banka↔kredi taksit eşleşmesini geri al (N-1 grup: bağlı TÜM banka satırları çözülür + anapara iadesi) |
| `POST` | `/api/finance/cash-flow/match-checks-batch` | `use` | Tek banka gideriyle birden çok çeki kapat (≤20 çek, toplam ±0.02 doğrulamalı) |

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

### "Yeniden Eşleştir" Butonu (R1, 2026-07-11)

Sayfa başlığındaki (PageHeader `actions`, PDF Rapor'un solunda; yalnız
`finance.cash_flow` **use** yetkisiyle görünür) **"Yeniden Eşleştir"** butonu
(RefreshCw ikonlu, `Button variant="secondary"`) `POST /api/finance/cash-flow/rematch`
çağırır — otomatik etiketleme + 4 eşleştirici (çek/kredi/KK/avans), ekstre
yüklemesiyle aynı orkestratör (`run_post_ingest_processing`).

- **Sonuç toast'ı:** dönen sayaçlardan sıfır olmayanlar kısa Türkçe özetle birleştirilir
  ("Yeniden eşleştirme: 3 etiket · 2 cari · 1 çek" gibi; alanlar: etiket, ödeme yöntemi,
  cari, çek, kredi, KK, avans). Hiç eşleşme yoksa "Yeni eşleşme bulunamadı" (info).
- **Yenileme deseni:** `runAutoTag` ile aynı — `markSkipWsReload()` (kendi WS yankısını
  atla) + başarıda `loadCashFlowItems(true)` + `loadCashFlowUntaggedCount()` +
  `loadCashFlowEurBalances()`. Backend BANKS yayını yaptığından diğer açık sekmeler
  WS ile tazelenir.
- Hata: `console.error` + backend `detail` mesajlı hata toast'ı; buton `loading` state'li.

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
  **Kategori başlığından TOPLU beklet (2026-07-07 akşam, kullanıcı isteği):** tarih görünümünde beklet modu
  açıkken kategori başlığının (ör. "Cari Ödemeleri") yanında beklet ikonu — tıklanınca başlık altındaki TÜM
  bekletilebilir ödemeler beklemeye alınır; hepsi zaten beklemedeyse tümünün bekletmesi kaldırılır (toggle).
  **Bekletilebilirlik filtresi:** `HOLDABLE_SOURCE_TYPES` frontend sabiti (`lib/constants/finance.ts`,
  backend `hold_service.HOLDABLE_SOURCE_TYPES`'ın birebir aynası — elle senkron) hem satır hem başlık
  affordance'ını sınırlar → çek satırında/başlığında beklet gösterilmez (backend zaten sessizce atlıyordu;
  yalancı "Beklemeye alındı" toast'ı da bitti).
- **Rate limit / 429 düzeltmesi (2026-07-07):** Hızlı ardışık Beklet/Geri al tıklamaları runway
  endpoint'inin eski `heavy_limiter`'ını (10/dk) tüketip "Nakit akım projeksiyonu yüklenemedi"
  toast'ları üretiyordu (her tıklama = doğrudan `loadRunway` + WS `finance_updated` yankısı = 2 istek).
  İki katmanlı çözüm: (1) `/cash-flow/runway` artık kendi **`runway_limiter`**'ını (30/dk) kullanır;
  (2) `runway.svelte.ts` **tekil-uçuş** korumalı — uçuş sırasındaki çağrılar tek trailing yenilemeye
  kuyruklanır, son yüklemeden `WS_ECHO_MS` (1500ms) içinde gelen WS event'i (kendi mutasyon yankısı) atlanır.
  **Aynı düzeltme T-Hesap/grafik yoluna da uygulandı (2026-07-07 akşam):** `/cash-flow/eur-balances`
  `heavy_limiter`'dan (10/dk) kendi **`eur_balances_limiter`**'ına (30/dk) alındı — art arda ~15 bekletmede
  10/dk dolup RunwayChart sessizce bayat kalıyordu (nginx: 47×429); `CashFlowTAccount.refreshData`
  aynı tekil-uçuş + WS-yankı-atlama desenine alındı (tıklama başına 2 istek → seri başına ~2);
  `loadCashFlowEurBalances` hatası artık toast gösterir (sessiz bayat grafik kalmaz).
- **Test:** `backend/tests/test_cash_flow_hold.py` (26).
  Geliştirici detayı: `backend/app/routers/finance/CLAUDE.md` "Bekletme (Hold)".

## EUR Çevrim Kuru — TCMB ALIŞ'a Geçiş (2026-07-11)

2026-07-11: EUR çevrimi TCMB satış→**ALIŞ** kuruna geçirildi (Sedna defter hizası;
`eur_balances`/`t_account`/`runway`/`_helpers` + çek/cari/kredi özetleri +
rezervasyon/stok/hakediş servisleri). Test fixture'ları `forex_buying` seed'ler.
Gerekçe + Sedna kur tarihi semantiği (Sedna G = bizim G−1): `docs/modules/sedna-mutabakat.md`
"Kur Kararları" bölümü.

## Revize Faz 0 (2026-07-11)

Eşleştirme denetiminin (`docs/denetim/2026-07-11-nakit-akim-eslestirme-denetimi.md`)
Revize Faz 0 paketi (R1–R7) uygulandı. Nakit Akım'a dokunan parçalar:

- **Eşleştirme orkestratörü tek yol (R1):** `utils/matching_service.py`'ye
  `run_all_matchers` (4 matcher: KK ekstre / çek / kredi / avans — her adım
  SAVEPOINT izolasyonlu, biri patlarsa diğerleri sürer) ve
  `run_post_ingest_processing` (önce otomatik etiketleme, sonra 4 matcher) eklendi.
  Ekstre yüklemesi (`bank_statement_import._post_upload_processing`), VakıfBank API
  senkronu (`run_vakifbank_import`) ve yeni elle tetik **hepsi aynı orkestratörü**
  çağırır — API-senkronunda matcher koşmaması (denetim bulgusu #1) kapandı.
- **"Yeniden Eşleştir" butonu (R1):** Nakit Akım sayfasına elle tetik eklendi →
  `POST /api/finance/cash-flow/rematch` (`finance.cash_flow` use; onaydan muaf —
  kapsam listesi `docs/modules/onay-akisi.md`; audit kaydı + BANKS/ADVANCES WS yayını).
  Sonuç sayaçları (`..._matched`) yanıt gövdesinde döner.
- **Auto-tag → finance_events senkronu (R1 devamı):** `utils/auto_tagger.py` artık
  otomatik kategori / ödeme yöntemi / cari atamalarını `_sync_finance_events` ile
  `finance_event_svc.sync_tag`'e yansıtır — manuel etiketleme yoluyla tutarlı;
  `is_matched`'a dokunmaz (cari eşleştirmesi banka hareketini gizlemez kuralı korunur).
- **match-vendor-tx düzeltmesi (R2):** `match_number` artık `match_number_seq`
  sequence'ından (yarış/kopya riski bitti); banka bacağı `sync_tag` ile FE'ye yansır;
  `event_matches`'e `method='manual'` kalıcı iz yazılır; commit sonrası
  `sync_vendor_finance_events` koşar.
- **Deferral ↔ EUR bakiye hizası (R5):** `eur_balances.py` çek/kredi/KK tarihlerinde
  artık `get_deferral_map` ile **ötelenmiş** tarihi kullanır — RunwayChart/PDF ile
  T-Hesap/runway arasındaki öteleme drift'i kapandı.
- **Test kapsamı (R6):** eşleştirme çekirdeği test ağı — 4 manuel eşleştirme
  endpoint'i, kredi N-1 eşleştirme, rematch orkestratörü, auto-tag FE senkronu ve
  deferral-EUR regresyonu (`tests/test_cash_flow_matching.py`).

Onay muafiyeti kapsam listesi (R7) ve sıradaki Faz 1 planı için denetim raporuna bakın.

## Faz 1 (2026-07-11)

Eşleştirme denetiminin (`docs/denetim/2026-07-11-nakit-akim-eslestirme-denetimi.md` §6)
Faz 1 paketi uygulandı — **#14 öğrenen kurallar (P3) bilinçli ERTELENDİ** (aşağıya bkz.).
Orkestratör artık **5 matcher** koşar (çek / kredi / KK ekstre / avans / **cari**) + her koşu
sonunda bayat öneri temizliği (`cleanup_stale_suggestions`).

### Cari↔banka otomatik matcher (#8 — 5. matcher)

`matching_service._match_vendors_to_bank`: açık cari ödeme tahminleri (`vendor_payment` FE,
`is_matched=False ∧ is_realized=False` — tutar FIFO kalanı) banka gider hareketleriyle eşlenir.
**En temkinli matcher** (cari kapatma FIFO'yu değiştirir):

- **Otomatik** yalnız üçlü koşulla: tutar **birebir** (kuruş düzeyinde, FIFO kalanı) +
  **isim/vendor sinyali ZORUNLU** (cari adı token'ı banka açıklamasında geçiyor VEYA
  auto_tagger'ın btx'e atadığı `vendor_id` aynı; sinyalsiz azami skor 70 < eşik) +
  **vade ±7 gün ZORUNLU** (`VENDOR_AUTO_WINDOW_DAYS` — açık koşul; yakınlık puanı: aynı gün
  +20 · ≤3 gün +15 · ≤7 gün +10) → skor ≥ 80 (`VENDOR_AUTO_MIN`).
- **Öneri:** 50–79 bandı VE 8–14 gün bandındaki isimli adaylar (skor 80'e ulaşsa bile geniş
  pencerede otomatik KAPANMAZ) öneri kuyruğuna düşer; aday penceresi ≤14 gün
  (`VENDOR_SUGGEST_WINDOW_DAYS`).
- Eşleşince ortak uygulayıcı `apply_vendor_bank_match` + koşu sonunda
  `sync_vendor_finance_events` (FIFO yeniden yazımı). **`is_matched`'a DOKUNMAZ** (cari kuralı —
  banka bacağı nakit akımda görünür kalır).

### İki-eşikli sistem + "Eşleşme Önerileri" paneli (#9)

Her matcher'da otomatik eşiğin ALTINDA ama öneri tabanının ÜSTÜNDE kalan **en iyi aday**
otomatik UYGULANMAZ; `event_matches`'e `method='suggestion'` kaydı düşer (idempotent
`_upsert_suggestion`; finance_events'e DOKUNULMAZ — öneri bir eşleşme DEĞİLDİR). Mevcut
otomatik davranış DEĞİŞMEDİ (geçmiş yanlış-pozitif vakalarının panzehiri: KK 13→2, avans
yanlış-taksit).

| Matcher | Otomatik eşik (`*_AUTO_MIN`) | Öneri bandı (`*_SUGGEST_MIN` .. eşik-1) |
|---|---|---|
| Çek (`CHECK`) | ≥ 20 | 8 – 19 |
| Kredi (`CREDIT`) | ≥ 40 | 20 – 39 |
| Avans (`ADVANCE`) | ≥ 20 | 8 – 19 |
| Cari (`VENDOR`) | ≥ 80 | 50 – 79 |
| Çapraz-para çek (`FX_SUGGEST_*`) | — (otomatik yok) | sabit skor 40 |
| Planlı gider köprüsü (çok aday) | — (tek aday doğrudan kapanır) | sabit skor 50 |

- **Endpoint'ler:** `GET /cash-flow/match-suggestions` (view; skor sıralı, paginated) ·
  `POST .../{id}/accept` (use; türe uygun `apply_*` / planlıda `close_entry_via_bank` ile
  gerçek eşleşme kurulur; hedef bu arada eşleşmiş/kapanmışsa 409 + öneri düşer) ·
  `POST .../{id}/reject` (use; öneri silinir — sonraki koşuda aynı çift yeniden önerilebilir).
  Hepsi onaydan muaf (kapsam listesi `docs/modules/onay-akisi.md`), audit'li, `CASH_FLOW`
  WS yayınlı.
- **Bayat temizlik:** `cleanup_stale_suggestions` her orkestratör koşusu sonunda hedefi artık
  açık olmayan (eşleşmiş/ödenmiş/silinmiş — banka bacağı silinenler dahil) önerileri süpürür →
  panel gürültü üretmez.
- **Panel (frontend, 2026-07-11 uygulandı):** Nakit Akım sayfası (`nakit-akim/+page.svelte`)
  PageHeader'da "Yeniden Eşleştir"in yanında **rozetli "Eşleşme Önerileri" butonu** (N = toplam;
  0 ise pasif/disabled; rozet sayısı sayfa açılışında `page_size=1` hafif GET ile, rematch ve WS
  `finance_updated` sonrası tazelenir). Tıklayınca **Modal (max-w-4xl)**: sayfalı liste
  (`Pagination`, varsayılan 25) — her satır iki yön: SOL banka hareketi (tarih · tutar ·
  kısaltılmış açıklama), SAĞ hedef (`target_description` · tarih · tutar+PB) + **skor rozeti**
  (`StatusBadge` warning, "skor N") + **tür etiketi** (`SUG_TYPE_LABELS`: Çek/Kredi/Avans/Cari/
  Vergi/SGK/Stopaj/Maaş/Kira). **Onayla** (primary) / **Reddet** (ghost + kırmızı X) yalnız `use`
  yetkisiyle görünür; ikisi de `ConfirmDialog`'dan geçer. Onay/ret sonrası liste + rozet
  tazelenir; **409/404** ("öneri kaldırıldı"/"bulunamadı" detayı) bilgi toast'ı + liste
  tazeleme olarak işlenir. Boş liste → `EmptyState` ("Bekleyen öneri yok — otomatik eşleşmeyen
  adaylar burada birikir"). Panel açıkken dışarıdan WS `finance_updated` gelirse liste yeniden
  yüklenir; kendi işlemlerimizin yankısı sayfanın mevcut `markSkipWsReload` echo-guard'ıyla
  atlanır (öneriler zaten elle tazelendiği için). Onay/ret sonrası sayfa aralık dışına düşerse
  son sayfaya geri çekilir.

### Çapraz-para aday üretimi (#13)

Döviz çek TL hesaptan işlem günü kuruyla ödenmiş olabilir — birebir tutar anahtarı bunu asla
yakalayamaz. Birebir eşleşme/öneri bulunamayan döviz çeki için: vade ±10 gün
(`FX_SUGGEST_WINDOW_DAYS`) içindeki TL banka gideri, `ledger_rate`(işlem günü) ile hesaplanan
beklenen TL'nin ±%1 (`FX_SUGGEST_TOLERANCE`) bandındaysa **YALNIZ öneri** (skor 40) üretilir —
otomatik uygulanmaz.

### Yarış koruması (hafif — #28'in Faz 1 dilimi)

Tetikler çoğaldı (ekstre + banka API senkronu + rematch + öneri onayı) →
`apply_check/credit/advance/vendor_bank_match` hedefi **`FOR UPDATE SKIP LOCKED`** ile yeniden
doğrular; koşul bozulmuşsa eşleşme kurulmaz (`False`/`None` döner; manuel uçlar 409 verir).
KK matcher'ında kilitli re-check, kredi N-1 grup uygulamasında taksit kilidi.

### Uygulayıcılar ORTAK (D1-2 deseni)

`apply_check_bank_match` / `apply_credit_bank_match` / `apply_advance_bank_match` /
`apply_vendor_bank_match` (`utils/matching_service.py`) — otomatik matcher + manuel endpoint +
öneri-Onayla ÜÇÜ DE aynı fonksiyonu çağırır (`match_vendor_tx` uygulamayı
`apply_vendor_bank_match`'e devretti). **Yeni eşleştirme yolu yazarken `apply_*` kullan — elle
alan set etme** (sequence, sync_tag, `event_matches` izi ve yarış koruması tek yerde).

### Geri alma uçları (#10)

- `POST /cash-flow/unmatch-check` — çek `pending`'e döner, banka hareketi serbest kalır;
  `finance_event_svc.unmatch` çek FE'sini açar + `event_matches` izini siler.
- `POST /cash-flow/unmatch-credit-payment` — taksit açılır + **anapara iadesi**
  (`remaining_amount`'a geri eklenir); **N-1 grupta** `event_matches` izinden bu taksite bağlı
  **TÜM banka satırları** çözülür (`match_number` temizlenir). Banka FE'sine dokunulmaz
  (hareket bankada gerçekleşmiştir — realized kalır).
- Kredi N-1 grup eşleşmesi artık grubun TÜM banka satırlarına **ortak `match_number`** + satır
  başına `event_matches` izi yazar (eskiden yalnız ilk satır iz alıyordu → mutabakatta kanıtsız
  satır + yarım geri alma).
- **Frontend (2026-07-11):** Çekler sayfasında (`cekler/+page.svelte`) banka-eşleşmiş
  (`bank_transaction_id` dolu + `status='paid'`) çekin eşleşme rozetinin yanında ikon-only
  **Geri Al** (Lucide `Undo2`, `ConfirmDialog`'lu, `canUse` guard) → `unmatch-check`; Krediler
  sayfasında (`krediler/+page.svelte`) ödeme planındaki ödenmiş+banka-eşleşmiş taksit satırında
  aynı desen (`Undo2` ikon, yoğun-tablo ikon-only istisnası) → `unmatch-credit-payment`. İkisi
  de başarıda toast + tam veri tazeleme yapar.

### 1-N çek (#12)

- **Otomatik:** aynı cariye (`vendor_code`) ait, vadesi ±2 gün kümelenen **TL** bekleyen
  çeklerin toplamı bir banka giderine kuruş düzeyinde denk ve tarih ±5 gün içindeyse hepsi
  topluca kapanır (skor 90 — kredi faiz+vergi N-1 grup deseninin çeke uyarlanması).
- **Manuel:** `POST /cash-flow/match-checks-batch` — tek banka gideriyle ≤20 çek, toplam ±0.02
  doğrulamalı; çeklerden biri bu arada eşleşirse 409 + rollback.
- **Avans kısmi eşleşmesi BİLİNÇLİ ERTELENDİ:** `Advance.received_amount` elle güncellenebilir;
  otomatik kısmi eşleşme Faz 2+.

### Planlı gider köprüsü (#11)

Vergi/SGK · Personel · Kira **etiketi** banka bacağına numara verirken `scheduled_entry` açık
kalıyordu → aynı dönemde tahmin + gerçekleşen ÇİFT sayılıyordu.
`_SCHEDULED_CATEGORY_MAP` (`transaction_tags.py`): Vergi/SGK → tax/sgk/withholding ·
Personel → salary · Kira → rent_expense. Banka işleminin ayına denk (`period_year/month`) +
tutar ±%2 uyan **TEK açık giriş** varsa `scheduled_service.close_entry_via_bank` ile banka
kanıtıyla kapatılır (**sıra ÖNEMLİ: önce `upsert_scheduled_entry`, SONRA `match`** — upsert
`is_matched=False` yazar, match en son gelmeli); birden çok aday → öneri kuyruğu (ilk 5,
skor 50). `close_entry_via_bank` yarış-korumalı; öneri-Onayla planlı türlerde de aynı
fonksiyonu çağırır.

### Ertelenen — #14 öğrenen kurallar (P3)

accept/reject sinyalinden kural öğrenme (learned_match_rules) uygulanmadı;
`event_matches.method/score` alanları eğitim verisi olarak birikmeye devam ediyor.

## Faz 3 (2026-07-12)

Eşleştirme denetiminin (`docs/denetim/2026-07-11-nakit-akim-eslestirme-denetimi.md` §6)
Faz 3 paketi uygulandı — **#26 ve #27 bilinçli ERTELENDİ** (aşağıya bkz.). Bu dosya nakit-akım
uçlarını (#21 yaşlananlar + #25 tahmin doğruluğu) anlatır; banka tarafı (#22 kopya tamlığı +
#24 hesap silme temizliği + silme uçları) `docs/modules/bankalar.md`'de, bakiye-zinciri
kontrolü `docs/modules/sedna-mutabakat.md`'de.

### Yaşlanan eşleşmemişler — `GET /cash-flow/reconciliation/aging` (#21)

Tahmin→gerçekleşme geçişinin iki **sessiz kopma sınıfını** görünür kılar (bugüne dek yalnız
satır satır taranarak fark ediliyordu). Çekirdek: `cash_flow/aging.py::compute_aging(db, days,
item_limit)` — endpoint + cron bildirimi AYNI fonksiyonu çağırır (ortak-çekirdek deseni).

- **(a) `stale_forecasts`** — vadesi `bugün − days`'ten eski, hâlâ **açık** tahminler
  (FE `is_matched=False ∧ is_realized=False`, `source_type != 'bank'`): kaynak-türü bazında
  grup (`by_source`: Türkçe etiket + adet + TL toplam [`amount_try` yoksa `amount`] + en eski
  tarih) + tarih-sıralı ilk `item_limit` kalem (`days_overdue` ile).
- **(b) `unmatched_bank`** — cutoff'tan eski ve `match_number`/`category_id`/`vendor_id`
  ÜÇÜ DE boş (etiketsiz + eşleşmesiz) banka hareketleri: adet + Σ|tutar| + ilk kalemler
  (`days_old`).
- Sorgu parametresi `days` 1–180 (varsayılan **7**). `finance.cash_flow` **view**, salt-okuma
  GET → onaydan muaf.
- **Günlük bildirim:** `cron_sedna_sync._maybe_notify_aging` — 2 saatlik timer'ın **günün İLK
  koşusunda** (09:15 turu; `now.hour == 9` guard'ı — her turda bildirmek gürültü olur)
  `compute_aging(days=7)` özetini "Yaşlanan eşleşmemişler" başlığıyla `_notify_viewers` ile
  gönderir (yalnız sayaçlar > 0 ise); hata cron'u düşürmez.
- **Frontend (2026-07-12 uygulandı):** Nakit Akım başlığında rozetli **"Yaşlananlar"** butonu
  (Hourglass; rozet sayısı = `stale_forecasts.total_count + unmatched_bank.count`, sayfa
  açılışında days=7 ile hafif çekilir; 0 ise buton soluk/disabled — Eşleşme Önerileri deseni).
  Modal (`max-w-4xl`): üstte gün seçici (SegmentedControl **7/15/30**) + kaynak-bazlı amber
  özet çipleri (etiket · adet · ₺toplam, title'da en eski tarih); altta iki bölüm listesi —
  **Açık Tahminler** (tür rozeti + tarih + açıklama + tutar + `days_overdue` amber rozeti) ve
  **Etiketsiz Banka Hareketleri** (`days_old` rozeti; gider kırmızı / gelir yeşil). Listeler
  backend `item_limit`=50 ile kırpık → "En eski N kayıt gösteriliyor" notu. WS
  `finance_updated`'da modal açıksa rapor, kapalıysa rozet tazelenir (polling yok). Rozet her
  zaman 7 günlük eşiği gösterir (modalda başka gün seçilse bile).

### Tahmin doğruluğu — `GET /cash-flow/forecast-accuracy` (#25)

Faz B'nin `event_matches` izlerinden (method ≠ `suggestion`, banka bacaklı) **tahmin-tarih ↔
gerçekleşme-tarih** sapmasını çıkarır — sistematik geç ödeyen cari/tür için vade önerisi
(tahminler zamanla iyileşir, geri-besleme döngüsü).

- **Planlı tarih kaynağı türe göre** (`_PLANNED_DATE_SOURCES`): çek/kredi `due_date` · avans
  `advance_date` · cari `payment_due_date` · planlı türler (tax/sgk/withholding/salary/
  rent_expense/recurring) `entry_date`. **Gerçekleşme** = eşleşen banka işleminin tarihi.
- `months` 1–24 (varsayılan **6**; hem iz `created_at`'i hem gerçekleşme tarihi pencerede).
  `finance.cash_flow` view, onaydan muaf GET.
- **Yanıt:** `by_type` (tür başına adet + **medyan** + ortalama gecikme günü; pozitif medyan =
  sistematik GEÇ gerçekleşme → tahminler iyimser) + `by_vendor` (yalnız `vendor_payment`;
  en çok izli 50 cari — medyan gecikme + `current_payment_days` +
  **`suggested_payment_days` = mevcut vade + medyan gecikme**, yalnız |medyan| ≥ 3 günse,
  0 tabanlı).
- **YALNIZ ÖNERİ — otomatik ayar YOK (bilinçli):** vade değişikliği kullanıcı kararıyla mevcut
  cari-vade PATCH'i (`PATCH /vendors/{id}/payment-days` — onaya TABİ) üzerinden elle yapılır.
  Rapor endpoint'i hiçbir kaydı değiştirmez.
- **Frontend (2026-07-12 uygulandı):** başlıkta **"Tahmin Doğruluğu"** butonu (Target) →
  modal (`max-w-4xl`): ay seçici (SegmentedControl **3/6/12**) + sabit açıklama satırı
  ("Pozitif = tahminden geç gerçekleşme. Önerilen vade uygulaması Cariler sayfasından elle
  yapılır.") + **Tür Bazında** tablo (etiket · adet · medyan gecikme gün · ortalama) +
  **Cari Bazında** tablo (cari · adet · medyan gecikme · mevcut vade · önerilen vade —
  `null` ise "—", doluysa **amber rozet**). Gecikme işaretli gösterilir (`fmtDelay`:
  pozitif `+`/kırmızı = geç, negatif `−`/yeşil = erken); `total_matches=0` → EmptyState.

### Panel banka KPI'sı = runway `start_eur` (C2, 2026-07-12 uygulandı)

Panel'deki "Bankalar" KPI'sı artık hesap listesinden elle toplanan tutar yerine runway'in
`start_eur` kaynağından beslenir → **Panel KPI / Nakit Akım bakiyesi / runway "Bankadaki
Nakit" üç görünüm TEK sayı** (blocked_amount düşülmüş, aynı kur mantığı). Uygulama
(`dashboard/+page.svelte`): `subscribeRunway()` (ref-count'lu — T-Hesap içindeki
OverdueList/HeldList aboneleriyle paylaşılır, çift istek yok) + `$effect` ile
`runwayStore.data.start_eur` karta yazılır; kart alt metni **"Nakit Akım ile aynı kaynak"**.
Eski client-side toplam (yalnız TRY/EUR/USD hesaplarını kapsıyordu — diğer para birimleri
atlanıyordu) ve BANKS `useLiveRefetch` satırı KALDIRILDI (tazelik runway store'un kendi
`finance_updated` aboneliğinden gelir). Runway `finance.cash_flow` view istediğinden kart
yalnız o izin de varsa dolar (banks-izinli ama cash_flow-izinsiz kullanıcıda kart gizli —
bilinçli, aksi 403 toast'ı üretirdi).

**C2 genişletildi — RunwayChart başlığı + tipping de `start_eur` (2026-07-16, çift-sayım düzeltmesi):**
`RunwayChart`'ın **"BANKADAKİ NAKİT" başlığı** ve **"nakit yetmiyor" (`tippingCikis`) yürüyüşünün
başlangıç nakdi** eskiden `eur_balances.total_balance_eur` kullanıyordu — o değer
`daily[bugün].balance_eur`'dur ve bugün son banka ekstresinden SONRAYSA bugünün **ödenmemiş**
planlı ödemelerini zaten düşer. Sonuç: (a) başlık gerçek banka nakdinin altında görünüyordu
("para hâlâ bankada" 2026-07-06 ilkesine aykırı, Bankalar KPI'sıyla da tutarsız); (b) tipping
yürüyüşü bu net değerden başlayıp **aynı bugünkü ödemeyi tekrar düşünce** ödeme henüz ödenmemişken
erken "yetmiyor" damgası basıyordu (ÇİFT SAYIM — kullanıcı bulgusu: "bugünkü ödeme ödenmedi, neden
hem nakitten düşülüyor hem de yetmiyor deniyor"). İkisi de artık **`runwayStore.data.start_eur`**
(saf banka nakdi) kullanır → başlık = Bankalar KPI = tipping başlangıcı TEK sayı; tipping her ödemeyi
tam bir kez düşer. **EĞRİ** (`RunwayChart` çizgisi) o gün DEĞİŞMEMİŞTİ — 2026-07-18'de o da
hizalandı (aşağıdaki bölüm). Tipping yürüyüşü saf `cashflow.ts::firstTippingRow`'a çıkarıldı (çift-sayım
regresyon testi: `cashflow.test.ts`). Değişen dosyalar: `CashFlowTAccount.svelte` (startCash +
RunwayChart `startEur` prop'u), `RunwayChart.svelte` (`startEur` prop), `cashflow.ts`.

### Bakiye Eğrisinin Bugün Noktası = Saf Banka Nakdi (2026-07-18, kullanıcı kararı)

**Kullanıcı isteği:** "Henüz ödeme yapılmadı, ödenip ödenmeyeceği de belli değil — grafikteki bugün
nokta bakiyesini de bankalara eşitle." (Canlı belirti: başlık €95.664 iken eğrinin bugün noktası
€91.070 — fark, bugün vadeli ödenmemiş ₺247.199 sigorta ödemesinin projeksiyondan düşülmesiydi.)

**Değişiklik (`eur_balances.py` kümülatif bakiye bloğu):** Son banka ekstresi tarihinden sonraki
günlerde projeksiyona **yalnız bugünden SONRAKİ (`dt > bugün`) planlı kalemler** girer. Bugün (ve
son ekstre ile bugün arası) vadeli ödenmemiş gider/gelir kalemleri bakiyeden düşülmez/eklenmez —
2026-07-06 "vadesi geçeni bakiyeden düşemezsin, para hâlâ bankada" ilkesinin bugüne genişletilmesi
(2026-07-16'da listeler [runway/T-Hesap] zaten `<= bugün` sınırına alınmıştı; eğri artık aynı hizada).
Sonuç: **eğrinin bugün noktası = `start_eur` başlığı = Bankalar KPI** (yalnız gün-bazlı kur çevrimi
kaynaklı kuruş farkı kalabilir). Kalem ödenince gerçek banka hareketiyle bakiye düşer; o ana kadar
Vadesi Geçenler'de izlenir. `total_balance_eur` (Nakit Akım sayfa başlığı) aynı kaynaktan geldiğinden
o da saf banka nakdine eşitlendi. Günlük/aylık **gider-gelir toplamları DEĞİŞMEDİ** (yalnız bakiye
eğrisi; ay NAKİT GİRİŞ/ÇIKIŞ kalemleri bugünkü kalemleri göstermeye devam eder).

**Test:** `test_payment_deferral.py::TestEurBalanceOverdueVendor::test_today_due_unpaid_not_subtracted_from_today_point`
(bugün vadeli kalem bugün noktasını değiştirmez; +2 gün vadeli kalem yalnız gelecek günden düşer).

### Panel Runway Grafiği — 0-bölmeli renk + devreden bakiye (2026-07-13)

`RunwayChart.svelte` iki kullanıcı isteğiyle güncellendi:

- **Renk 0 çizgisinde bölünür (KESKİN geçiş):** Çizgi tek renk değildi — dönem içinde
  herhangi bir gün negatife düşerse TÜM çizgi turuncu oluyordu (Ağustos ay başında
  pozitifken bile). Çözüm: çizgi **0-kesişim noktalarında ayrı polyline segmentlerine**
  bölünür (doğrusal enterpolasyonla kesişim noktası bulunur) — pozitif segment yeşil
  (`#8fd0a8`), negatif turuncu (`#e8a06a`); renk TAM kesişimde değişir. İlk deneme dikey
  `linearGradient` idi (iki stop aynı offset'te) ama 0'a yakın seyreden çizgide stroke
  genişliği renk sınırını kestiğinden iki renk harmanlanıp geçiş bulanık görünüyordu →
  kullanıcı isteğiyle segment bölmeye geçildi (aynı gün). Tümü-pozitif dönem tamamen
  yeşil kalır.
- **Devreden bakiye ("Devir" noktası):** Grafik yalnız `daily`'de kaydı olan (hareketli)
  günleri çizdiğinden, dönem başında hareket yoksa çizgi ay ortasından başlıyordu (canlı:
  Ağustos 7 Ağu'dan başlıyordu). Artık dönemden ÖNCEKİ son bilinen bakiye (önceki dönemin
  kapanışı) 1'inci güne sentetik nokta olarak eklenir → çizgi her zaman dönem başından
  başlar; tooltip'te "· Devir" etiketi taşır. Simetrik olarak son hareket dönem sonundan
  önce bitiyorsa bakiye dönem sonuna düz uzatılır (hareketsiz günlerde bakiye değişmez);
  dönemde hiç hareket yoksa düz devir çizgisi çizilir (eskiden grafik hiç çizilmiyordu).
  Veri zaten kümülatif (`compute_eur_balances` — aylar arası süreklilik backend'de var);
  bu değişiklik SALT görsel dilimleme katmanında.
- **"Bugün" işareti:** Bugün seçili dönemin içindeyse grafikte dikey altın kesikli çizgi +
  eğriyle kesişimde koyu-dolgulu altın-halkalı nokta + eksen satırında altın "Bugün"
  etiketi (kenar 1/31 etiketleriyle çakışmasın diye %6–94 clamp) gösterilir. Bugün dönem
  dışındaysa (ör. Ağustos görünümü) işaret çizilmez. Karşılaştırma yerel gece yarısıyla
  (`setHours(0,0,0,0)`) yapılır — nokta t'leri de yerel gece yarısı.

### Ertelenenler (bilinçli)

- **#26 rezervasyon gelirinin FE'ye taşınması:** Karar-3 **çift-sayım matrisi** kullanıcıyla
  netleştirilecek — iki varyant masada: temkinli "yalnız hakediş alacakları FE'ye" vs tam
  "ciro projeksiyonu FE'ye". Netleşmeden kod yazılmaz (çift sayım riski).
- **#27 eur_balances'ın FE'den okuması:** çift motorun (C3) kökten çözümü ama
  **davranış-eşitliği doğrulaması** gerektiren ayrı büyük iş.
- **#14 öğrenen kurallar + #20 WS izin filtresi:** P3 — önceki fazlardan ertelenmiş durumda.

## T-Hesap: "Kredi/Leasing" Birleşik Başlığı (2026-07-18)

Kullanıcı isteği: "Cari" altında görünen leasing ödemeleri, "Kredi" başlığı **"Kredi/Leasing"**
olarak yeniden adlandırılarak oraya taşındı. Banka "Kredi" kategorisi DB'de "Kredi/Leasing"e
RENAME edildi; leasing açıklamaları (`leasing|finansal kiralama`) için en-önde auto-tag kuralı
eklendi; cari eşleşmesi leasing bacağını artık "Cari" yerine "Kredi/Leasing" etiketler (eşleşme
bağı korunur); `t_account.SOURCE_LABELS["credit"]` da aynı string'e çekildi → **planlı kredi
taksitleri + banka kredi/leasing hareketleri tek grupta** (ödenen taksit realized, ödenmemişi
pending — Personel birleştirmesi deseni; karma grubun `section`'ı deterministik "finansman").
24 canlı kayıt geriye dönük taşındı. Detay: `docs/modules/transaction-tags.md` "Leasing →
Kredi/Leasing"; test: `TestLeasingRule` + `test_credit_and_bank_leasing_merged_under_kredi_leasing`.

## T-Hesap: "Pos Bloke Çözme" — Toplam-Dışı Bilgi Grubu (2026-07-18)

Kullanıcı isteği: "POS bloke çözme aslında bir para çıkışı değil — karşılığı başka banka
hesabına virman yapılıyor. Pos Bloke Çözme başlığı altında göster ama toplama dahil etme."

- **Yeni kavram — toplam-dışı bilgi kategorisi (`t_account.INFO_CATEGORIES`):** grup
  T-Hesap'ta kendi başlığıyla GÖRÜNÜR (her iki kolonda; kalemler + kendi toplamı) ama
  **kolon toplamı / net / gerçekleşen sayaçlarına ve faaliyet-finansman netlerine GİRMEZ**.
  Virman'dan farkı: Virman (`TRANSFER_CATEGORIES`) sorgudan tamamen dışlanır ve hiç
  görünmez; bilgi grubu listelenir. Yanıtta grup `in_total: false` taşır; frontend
  (`CashFlowTAccount.svelte`) başlık yanında gri **"toplam dışı"** rozeti çizer, tarih
  görünümünde gün toplamına ve tipping girişlerine katmaz.
- **Etiketleme:** çift-bacak tespiti `auto_tagger._tag_pos_bloke_transfers` — yalnız
  karşı bacağı (aynı gün, zıt işaretli aynı tutar, farklı hesap) bulunan "POS BLOKE"
  kayıtları; eşsiz ücret/aidat bacakları gerçek gider olarak eski kurallarında kalır.
  Detay: `docs/modules/transaction-tags.md` "POS Bloke Çözümü".
- **Tutarlılık:** Nakit Akım sayfası `groupByMonth` (`NO_TOTAL_CATEGORIES`) kalemleri
  gösterir ama ay/gün toplamına katmaz (ödenen çek `is_matched` deseniyle aynı);
  `compute_eur_balances` günlük banka gelir/gider toplamları da hariç tutar (bakiye zaten
  ekstreden gelir, etkilenmez); PDF rapor notu güncellendi; eşleştiriciler bu kategoriyi
  aday almaz (`_TRANSFER_CATEGORY_NAMES`).
- **Canlı doğrulama (Haziran):** "Pos Aidat Gideri" €11.308 → **€98** (yalnız gerçek
  ücretler); "Pos Bloke Çözme" GİRİŞ=ÇIKIŞ=€19.527 simetrik, toplamlara dahil değil.

Test: `TestTAccountInfoCategory` + `TestPosBlokeTransfers` + `finance.test.ts`.

## T-Hesap: Acenta / Döviz Satışı Grupları + Banka Amblemi (2026-07-13)

Kullanıcı isteği üç parça (Panel T-Hesap cetveli):

1. **Acenta tahsilatları "Acenta" başlığı altında** — acente ödemeleri banka açıklaması kırpık
   geldiğinden ("TRAVE/020726/278982", "SEYAHAT ACENT/…") "Etiketsiz"te kalıyordu. Veri-temelli
   otomatik etiketleme eklendi (`auto_tagger._tag_agency_collections`): Sedna `sales_collections`
   tutar+para birimi+tarih(±4 gün) eşleşmesi · acente adı token'ları (agency_groups + rezervasyon
   acenteleri + tahsilat müşteri adları) · açıklama ipuçları ("seyahat acent", "travel"…). Yalnız
   GELİR işlemleri; virman/hesaplar-arası ve bireysel misafir ön ödemeleri (120.26.*) hariç.
2. **Döviz satışları "Döviz Satışı" başlığında** — "YapiKrediFX+ Dvz Satis" açıklaması `kredi`
   desenini içerdiğinden yanlışlıkla **Kredi** etiketleniyordu (gelir sütununda sahte "Kredi"
   grubu). `AUTO_TAG_RULES`'a Kredi'den ÖNCE "Döviz Satışı" kuralı eklendi; canlıdaki 28 yanlış
   etiket geriye dönük düzeltildi. ("Döviz Satım" = iç transfer, T-Hesap'tan hariç — o ayrı kalır.)
3. **Satır başında banka amblemi** — `t-account` item'larına `bank_name` eklendi (banka hareketi /
   çekin ödeme bankası / kredi taksit bankası / KK projeksiyon kart bankası). Frontend
   `lib/utils/bankBadge.ts` banka adını marka renkli kısaltma rozetine çevirir (YK lacivert,
   VB sarı, HB mavi…; bilinmeyen banka baş harfleri + gri; bankasız kalem rozetsiz).
   `CashFlowTAccount.svelte` her satırın başında rozeti gösterir; toplu cari satırında üyelerin
   bankası tekse taşınır, karışıksa gösterilmez (`cashflow.ts aggregateRows`).

Detay: `docs/modules/transaction-tags.md` "Döviz Satışı Kuralı" + "Acenta Tahsilatı Tespiti".
Test: `tests/test_auto_tagger.py` (15) + `test_cash_flow_taccount.py::TestTAccountBankName` +
frontend `bankBadge.test.ts` / `cashflow.test.ts`.

4. **(Aynı gün, ikinci istek) Banka ücretleri "Havale Komisyonları" başlığında** — banka
   ücret/komisyon kalemleri (YK'nin transfer başına ayrı yazdığı ₺15,96+₺0,80 ücret+BSMV
   bacakları, "Diğer Diğer KOM", POS bakım ücretleri, BSMV kesintileri) Etiketsiz'te
   birikiyordu. `auto_tagger._tag_bank_fees`: ücret anahtar kelimesi (tavan TRY ≤2.500) veya
   "Diğer Internet - Mobil" ücret-bacağı öneki (tavan TRY ≤250 — aynı önekli ₺10K+ tutarlar
   maskeli-PAN kart ödemesi, etiketlenmez). İlk canlı koşu: 198 kalem (~₺10.317).
   Detay: `docs/modules/transaction-tags.md` "Banka Havale/EFT Komisyon Tespiti".

5. **(Aynı gün, üçüncü istek) Acenta kaleminde ad = acente adı** — "Açıklamalar çok karışık,
   sadece acente isimlerini yazsa" isteği üzerine Acenta etiketlenen işleme çözülen acentenin
   kısa adı `tag_note` olarak yazılır ve T-Hesap satırında açıklama yerine o gösterilir
   (ör. "Diğer Diğer TRAVE/020726/278982" → "NORDİC LEİSURE TRAVEL", "Swift şubeden para
   yatırma Ref: …" → "ALLTOURS FLUGREİSEN"). Ad çözülemezse açıklama görünmeye devam eder.
   Detay: `docs/modules/transaction-tags.md` "Görünen ad = acente adı".

## #26 KARARI KAPANDI — TAM CİRO Projeksiyonu (2026-07-17, kullanıcı kararı: varyant iii)

Beklenen acente tahsilatı ana projeksiyona girdi. Uygulama **okuma-anında servis**
(`services/contract_projection_service.py`, cc_projection deseni) — finance_events'e
YAZILMAZ: bayat kayıt riski sıfır, #27 çift-motor drift'i yok. Üç tüketici:

- **eur_balances:** `contract_income_by_date` — gelecek güne taksit (net) + aylık ciro kalemi.
- **runway:** vadesi geçmiş taksitler "Vadesi Geçen Tahsilatlar"a KALEM KALEM
  (`contract_installment:{id}`, KOŞULLU etiketi ile); cari ay vadeliler girişlere;
  cari ay ciro pseudo-kalemi ay sonu. SOURCE_LABELS: "Kontrat Taksiti".
- **t_account:** GİRİŞ tarafına iki projeksiyon grubu — "Kontrat Taksitleri (Projeksiyon)"
  (finansman) + "Beklenen Ciro Tahsilatı (Projeksiyon)" (faaliyet); hold kimliği yok.

**Çift-sayım kural seti (4 vektör, kontrat analizi raporundan — UYGULANDI):**
1. `advances` tablosu BİRİNCİL (kullanıcı elle işletiyor; FE'leri zaten projeksiyonda) —
   kontrat taksitleri grup bazında kronolojik FIFO ile pending-advance havuzuna NETLENİR;
   yalnız havuzu aşan kısım projeksiyona girer (canlı: Alltours 940k advances ↔ 1M taksit
   → net 60k).
2. `guarantee_check` planları (otelin VERDİĞİ teminat — Odeon 2×24M TL) hiçbir gelir
   görünümüne girmez.
3. TAM CİRO serisi `compute_settlement`'tan (340-mahsuplu); CARİ YIL vadeli sözleşmesel
   girişler (pending advances + net taksitler) serinin başından FIFO kırpılır — aynı para
   iki kez sayılmaz. 2027+ taksitleri kırpmaya girmez (2027 cirosundan mahsup edilecek).
   Ertesi yıla taşan tahsilat (tail) Ocak sonu tek kalem.
4. Banka gerçekleşmesi: `_match_contract_installments_to_bank` (matching_service, avans
   eşleştiricisinden SONRA koşar; avansa bağlı işlemler aday olamaz) → taksit paid +
   `bank_transaction_id`; projeksiyon cache'i invalidate edilir.

Koşullu taksitler (W2M %70 ciro şartı) `KOŞULLU` etiketiyle ayrışır. Canlı ilk bulgu:
W2M Şubat–Nisan 800k € vadesi geçmiş/koşullu → "Vadesi Geçen Tahsilatlar"da.
Test: `tests/test_contract_projection.py`. SPO takvimi: `GET /sales/kontratlar/actions-calendar`
+ KontratlarPanel 90-günlük bant görünümü (grafik overlay'leri ileriki iterasyon).

## Personel Birleştirmesi — Tek Başlık + Otomatik Maaş Güncelleme + Dedup (2026-07-18)

**Kullanıcı isteği:** Personel ödemeleri farklı başlıklar altında dağınıktı ("Maaş", "SGK",
"Stopaj", "Personel", maaş toplu transferleri "Etiketsiz") → hepsi tek **"Personel"** başlığında;
maaş tahmini Sedna'daki gerçek bordroyla otomatik güncellensin; planlı + gerçekleşen çift
görünmesin.

### Ne değişti (kullanıcı gözünden)

1. **Panel T-Hesap'ta tek "Personel" grubu:** planlı maaş/SGK/stopaj kalemleri + banka
   "Personel" kategorisi aynı başlıkta. (SGK/stopaj **banka ödemeleri** KDV vb. ile birlikte
   "Vergi/SGK"da kalır — devlete giden ödemeler başlığı; eşleşme kurulunca planlı bacak
   düştüğünden toplam şişmez.)
2. **Maaş tahmini kendini günceller:** muhasebe bordroyu Sedna'ya işleyince (335 hesabı aylık
   tahakkuk), o dönemin ödenmemiş maaş girişi otomatik gerçek tutara çekilir (Sedna senkronu
   her koşusunda — 2 saatte bir; Topbar "Sedna" butonu da tetikler). Gelecek ayların elle
   girilmiş mevsimsel tahminlerine dokunulmaz.
3. **Çift görünüm bitti:** maaş/SGK/stopaj banka ödemeleri planlı girişlerle otomatik
   eşleştirilir (yeni "Planlı personel-banka" eşleştiricisi). Kesin durumlar otomatik kapanır;
   emin olunamayanlar **Eşleşme Önerileri** paneline düşer (tek tık Onayla). Elle "ödendi"
   işaretlenmiş ama bankayla eşleşmemiş eski girişler de kapsanır (geriye dönük temizlik).
   Eşleşen banka hareketi otomatik "Personel"/"Vergi/SGK" etiketi alır.
4. **Banka kanıtı tahmini ezer:** bir giriş banka hareketiyle kapanınca girişin tutarı ve
   ödeme tarihi bankadaki gerçeğe çekilir (yalnız aynı para birimi; döviz hesabında tahmin
   korunur).

### Teknik özet

| Parça | Dosya |
|---|---|
| Başlık birleştirme | `cash_flow/t_account.py` `SOURCE_LABELS` — **aynı gün revize (kullanıcı):** salary → "Personel"; withholding/sgk/**dividend_stopaj** → **"Vergi/SGK"** (vergisel yükümlülük; banka "Vergi/SGK" kategorisiyle birleşir — ayrı "Temettü Stopajı" başlığı kalktı) |
| Sedna bordro sorgusu | `utils/sedna_client.py::fetch_personnel_payroll` (335 aylık tahakkuk/ödeme) |
| Maaş senkron servisi | `services/salary_sync_service.py` (yalnız ödenmemiş + ayı bitmiş dönem; tahakkuk < mevcut tahminin %40'ı → "bordro işlenmemiş", atla) |
| Senkron adımı | `sedna_sync._STEPS` `salary_sync` (izin `hr.salary` use) + cron `_CRON_STEP_KEYS` |
| Dedup eşleştirici | `utils/matching_service.py::_match_scheduled_to_bank` (7. matcher; kural tablosu docstring'de) |
| Ortak bağlama yolu | `services/scheduled_service.py::link_entry_to_bank` (`close_entry_via_bank` + yeni `attach_bank_to_paid_entry`) |
| Öneri kalıcılık düzeltmesi | `run_all_matchers` artık `suggested>0` koşularını da commit eder (eskiden SAVEPOINT rollback önerileri siliyordu) |

**Test:** `tests/test_personel_birlestirme.py` (13). Geliştirici detayı:
`backend/app/routers/finance/CLAUDE.md` "Personel Birleştirmesi" bölümü.

## Ocak Açılış Artefaktı Kapatıldı — Pencere-Öncesi Tohum Bakiyeleri (2026-07-19)

Ay-ay mutabakat denetiminde Ocak 2026 farkı +€167K çıktı: bakiye eğrisi `MIN_DATE=2026-01-01`
kesimi yüzünden 2026-öncesi 579 ekstre satırını okumuyor, hesaplar 2026'daki İLK satırlarına
kadar "yok" sayılıyordu (1 Ocak açılışı ~€30,5K görünüyordu; gerçek ~€289K — 13 hesabın
yıl-sınırı bakiye zinciri 0,00 farkla doğrulandı, Aralık ekstresi yüklemeye gerek kalmadı).

- **Tohumlama:** `compute_eur_balances` her hesabı pencere başında 2026-öncesi son bilinen
  ekstre bakiyesiyle başlatır. Tohum akım üretmez (Devir gelir değildir — ay gelir/gider
  toplamları değişmez), yalnız bakiye SEVİYESİNİ düzeltir; hesabın 2026'daki ilk satırı
  geldiğinde kendi ekstre bakiyesi devralır.
- **"Son bakiye" sıralama düzeltmesi:** Bankadaki Nakit KPI'sı (`_compute_start_eur`) ve mobil
  dashboard artık son bakiyeyi `(tarih, id)` sırasına göre seçer — `max(id)` sonradan eklenen
  eski-tarihli satırı "güncel" sanabiliyordu (canlıda +16,77 TL kalıcı sapma vardı, kapandı).
- **Sentetik devir satırları:** 2025 verisi hiç olmayan ama önceden var olan 4 hesaba (Ziraat
  TRY/EUR, Halkbank POS ×2) kanıt-bazlı `[DEVİR]` satırı eklendi (`source='manual'`, tutar 0,
  yalnız bakiye; FE üretilmez). Gerçek Aralık ekstresi yüklenirse manuel-purge bunları siler.

Test: `tests/test_eur_balances_seed.py` (8). Geliştirici detayı:
`backend/app/routers/finance/CLAUDE.md` "Pencere-Öncesi Tohum Bakiyeleri" bölümü.
