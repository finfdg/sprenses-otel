# Satış Modülü — Geliştirici Rehberi

> **2026-07-09 BİRLEŞTİRME:** Satış'ın RBAC modülü artık TEK: **`sales.acente_mahsup`**
> (Acente Mahsup & Nakit Akım). Eski `sales.hotel_reservation`, `sales.daily_reservations`
> ve `sales.room_types` modülleri kaldırıldı (migration `b3c9d5e7f1a2`); bu paketteki TÜM
> router'lar `require_permission("sales.acente_mahsup", "view"|"use")` kullanır ve
> `room_types` onayı executor'da `sales.acente_mahsup` anahtarıyla çalışır. Router/endpoint
> path'leri DEĞİŞMEDİ. Ana operasyon UI'ı `/dashboard/satis/acente-mahsup`; salt-okuma
> aylık finans raporu aynı izni kullanan `/dashboard/satis/acente-finans` sayfasındadır.
>
> **2026-07-19 BASİT TASARIM (kullanıcı yüklemesi — repo'daki "Acente Mahsup ve Nakit
> Akım.zip"):** Sayfa 4 tasarım sekmesi (Doluluk · Acenteler · Günlük Hareketler · Nakit
> Akım — `lib/components/sales/{Occupancy,AgencyDistribution,DailyMoves,SalesCashFlow}Panel.svelte`)
> + 3 işlevsel sekme (Rezervasyonlar · Oda Tipleri · Kontratlar) olarak yeniden kuruldu.
> Eski projeksiyon sekmeleri (Genel Bakış/Ciro/Avanslar/Faturalar) ve senaryo barı UI'dan
> kalktı; `DailyActivityPanel`+`MonthlyOccupancyChart` silindi. Backend eklemeleri:
> `occupancy-overview` endpoint'i (occupancy.py) + `compute_settlement`'ta
> `cashflow.calendar`/`overdue` blokları. Detay: `docs/modules/acente-mahsup.md`.

Router paketleri: `reservations/` (otel rezervasyon + günlük hareketler), `room_types`,
`agency_groups`, `acente_mahsup` (projeksiyon panosu), `agency_finance` (aylık finans raporu).
Bu dosya satış
modülüne katkı kurallarını içerir.

## Acente Finansal Takip (`agency_finance.py`, `sales.acente_mahsup`) — 2026-08-05

- Yeni bağımsız UI sayfası: `/dashboard/satis/acente-finans`; endpoint:
  `GET /api/sales/acente-finans/?year=YYYY`. Ayrı RBAC kodu açılmaz; satış konsolidasyonu
  korunur ve `sales.acente_mahsup view` kullanılır. Modül GET-only olduğundan onay executor'ı yoktur.
- Motor: `services/agency_finance_service.compute_agency_finance()`; tek payload'da 12 ay ×
  acente grubu matrisi üretir. Para birimi EUR'dur. Kaynaklar:
  - alınan/mahsup edilen avans: Sedna 340 hareket snapshot'ı (`sales_advance_transactions`),
  - haricen tahsilat: `sales_collections` (açıklamasında `VİRMAN` olan 120↔340 mahsup bacağı hariç),
  - rezervasyon ciro/adet: PMS aynası `reservations` (çıkış ayında),
  - açık/vadesi geçen gerçek hak ediş: `sales_invoices` FIFO kalan + `receivable_terms`,
  - ileri ay sonu hak ediş tahmini: ileri rezervasyonun çıkış tarihi + acente grup vadesi;
    mevcut 340 avans bakiyesi grup içinde FIFO mahsup edilir. Eşleşmeyen 340 hesapları ilgisiz
    `Diğer` rezervasyonlarına mahsup EDİLMEZ.
- `month_end_receivable = open_due + projected_due`; `overdue`, gerçek açık faturaların bu
  toplam içindeki vadesi geçmiş alt kümesidir. Önceki yıldan devreden açık/gecikmiş faturalar
  cari yıl görünümünde Ocak'a taşınır. Bu tanımlar çift sayımı önler ve UI tooltip/metinlerinde
  açıkça gösterilir.
- Sedna ayrıntı senkronu: `fetch_advance_transactions()` 340 hareketlerinde tarih, native ve TL
  tutarını birlikte okur. `run_sales_invoice_import()` kaynak başarıyla geldikten sonra snapshot'ı
  truncate+reload yapar; Sedna/tünel hatası mevcut snapshot'ı boşaltmaz. İlk senkron öncesi
  `sales_advances` toplam bakiyesi fallback'tir, fakat aylık avans kırılımı bilinçli olarak boş kalır.
- Frontend WS yenilemesi `SALES_INVOICES`, `EXCHANGE_RATES`, `HAKEDIS`, `HOTEL_RESERVATION` ve
  `AGENCY_GROUPS` yayınlarını dinler; HTTP polling yoktur. Detay: `docs/modules/acente-finans.md`.
- **Grup içi üye kırılımı (2026-08-13):** her grup satırı `members: [{name, totals}]` taşır
  (yıllık toplam, aylık yok); UI'da satıra tıklayınca açılır. Üye etiketi kaynağa göre değişir:
  rezervasyon = PMS acente adı, fatura/tahsilat/açık hak ediş = 120 cari adı, avans = 340 hesap
  adı — aynı üyenin farklı yazımları bilerek ayrı satırdır. Üye toplamları grup satırıyla birebir
  tutar (regresyon: `test_agency_finance.py::test_member_breakdown_matches_group_totals`).

## Acente Mahsup & Nakit Akım (`acente_mahsup.py`, `sales.acente_mahsup`)

- **Salt-okuma projeksiyon** (GET-only, 60sn TTL cache, `require_permission view`) → onay/broadcast
  kapsam dışı (Yönetim Paneli deseni). Mutasyon YOK.
- Motor: `services/agency_settlement_service.compute_settlement()` — rezervasyon cirosu (EUR,
  **çıkış ayında** tanınır) + `agency_groups` konfigü (`term_days`/`kickback_percent`) + gerçek
  avanslar (`receivable_service.compute_receivables` grup satırları, güncel kurla EUR) + yıl sonu
  hedef senaryosu → payload. **2026-07-19 ekleri:** `cashflow.calendar` (12 ayın tamamı —
  collected/pending cari aya göre, `overdue` = compute_receivables `overdue_tl`+`monthly_due`
  gerçek gecikmesi güncel kurla EUR; kırmızı KIRPILMAZ ki ΣKırmızı = Vadesi Geçen KPI'sıyla
  mutabık kalsın) ve `overdue.{total,rows}` (grup bazlı, `max_days` + `oldest_due_month`;
  yalnız `year == bugünün yılı`). `year_target`/`opening_cash` paramları UI'dan artık
  gönderilmez ama API'de geri-uyumlu durur. **`advances.rows` genişletmesi (2026-07-19
  akşam):** satırlara `revenue`/`invoiced`/`collected`/`overdue` alanları + blok
  toplamlarına `total_invoiced`/`total_collected` eklendi (compute_receivables'ın
  `invoiced_tl`/`collected_external_tl` alanları güncel kurla EUR; kümülatif, yıl
  filtresiz; haricen tahsilat '120-340 VİRMAN' avans-mahsup bacaklarını İÇERMEZ);
  satır seçimi "avansı olan" → "6 kalemden herhangi biri olan" grup. UI karşılığı
  `SalesCashFlowPanel` "Acente Finansal Özet" bar grafiği (`docs/modules/acente-mahsup.md` §5d).
- **Vade/kickback konfigü `agency_groups`'tadır** (bu modül eklerken 2 kolon eklendi); düzenleme
  mevcut `PATCH /agency-groups/{id}` (`sales.acente_mahsup` use) ile. Yeni mutasyon endpoint'i
  eklenmedi → ayrı executor handler gerekmez.
- Hak Ediş'ten (finance.hakedis, TL gerçek fatura yaşlandırması) **bağımsız**: burası ileri
  projeksiyon + kickback/hedef senaryo. Detay: `docs/modules/acente-mahsup.md`.
- **Acente × Durum kırılımı (2026-07-08):** ikinci GET endpoint `GET /acente-mahsup/agency-status`
  (`compute_agency_status()`) — acente × dönem (day/month/year) × durum EUR tutar + adet dağılımı.
  **Tutar GECE BAZLI dağıtılır (2026-07-08 güncelleme):** her konaklama gecesi kendi ayına,
  `eur_total` gece sayısına bölünerek (`generate_series` LATERAL) — "Aylık Doluluk Dağılımı"
  (`reservations/summary`) ile BİREBİR aynı yöntem, iki grafik tutarlı olsun diye. Durum
  (`Reservation`=gelen/`InHouse`=içeride/`CheckOut`=çıkış) artık dağıtım AYINI değil yalnız
  kategori/rengi belirler (eski "gelen/içeride→giriş, çıkış→çıkış tarihi" tek-ay ataması KALDIRILDI).
  Aylara yayılan rezervasyon dokunduğu her dönemde adet +1 (dönem başına COUNT DISTINCT). Acente
  gruplama `compute_settlement` ile ORTAK `_agency_group_maps()`
  (grup dışı → "Diğer"). Projeksiyon DEĞİL — anlık durum. Frontend "Rezervasyon & Ciro" sekmesinde.
  **Kök = top-N rollup (2026-07-08 güncelleme):** sıralama ölçütü `rank_by` ile SEÇİLİR — "count"
  (toplam rezervasyon adedi, varsayılan) veya "amount" (toplam ciro/EUR); frontend'de "Sırala:
  Rezervasyon | Ciro" SegmentedControl. Birim = grup VEYA gruplanmamış tek acente → grupsuz büyük
  acente artık "Diğer"e gömülmez, kendi hakkıyla top-N'e girer (satır `id=None` → tek-acente drill'i).
  `top_n` (varsayılan 7) seçili ölçüte göre en yüksek birim TEK TEK, kalanların tümü tek "Diğer"
  (en altta); grand toplam etkilenmez.
  **Drill (satıra tıkla):** `group_id` (grup→üyeleri bireysel; `0`=Diğer→top-N dışı acenteler; top-N'e
  girmiş gruplanmamış acente Diğer'de GÖRÜNMEZ) veya `agency` (tek ham acente, "Diğer"e düşmez). Motor
  tek geçişte grup+ham-acente düzeyinde toplar (top-N + Diğer drill için). Payload `filter`/`top_n`/`filter_options`.
  **Günlük doluluk barları (2026-07-08):** her `periods[].statuses[k]` artık `rooms` (dolu oda-gece,
  `SUM(r.rooms)` gece bazlı) + `total_rooms` taşır; payload'da `room_capacity` = aktif
  `room_types.total_rooms` toplamı (otelin fiziksel oda sayısı, ör. 341). Frontend GÜNLÜK görünümde
  barı `rooms / room_capacity` (doluluk) ile çizer (aylık/yıllıkta tutar/statusMax korunur). Bazı
  günler kapasiteyi aşabilir (overbooking) → bar kırpılır, etiket gerçek `N/kapasite oda` gösterir.

## Yapı

- `reservations/` paketi: `uploads` (XLS yükleme + RecId upsert + `removal_candidates`),
  `listing`, `summary` (KPI + doluluk), `occupancy` (**`occupancy-overview`** — Doluluk
  sekmesinin yıllık gerçekleşen/ileri kırılımı + chip verileri, İstanbul-TZ "bugün";
  2026-07-21: ay başına `eur/past_eur/future_eur` + `year_eur` gece-bazlı orantılı ciro
  — bar etiketleri + OccupancyPanel yıl karşılaştırması bu alanları kullanır;
  `daily-occupancy` günlük drill-down),
  `daily_activity` (**Günlük Hareketler** — `sales/__init__.py`'de AYRI prefix
  `/daily-activity` ile bağlanır (izin: `sales.acente_mahsup` view);
  Sedna CANLI gelen/iptal akışı, yerel tablo yok — iptal tarihçesi senkronda silindiğinden
  yerel veriyle cevaplanamaz. EUR çevrimi `sedna_import._currency_to_eur_factors` ile ORTAK.
  Salt-okunur → onay/broadcast kapsam dışı. Detay: `docs/modules/gunluk-hareketler.md`).
- `room_types`, `agency_groups`: oda tipi ve acente gruplama CRUD.

## Gerçek Zamanlılık — Broadcast

- Satış değişikliklerinde `broadcast_sales_update(background_tasks, BroadcastModule.X, action)`.
- **Sabit kullan, literal değil (2026-06-04):** modül adı `app/constants.py` →
  `BroadcastModule.HOTEL_RESERVATION` / `ROOM_TYPES` / `AGENCY_GROUPS`. Frontend karşılığı
  `realtime.ts` → `BROADCAST_MODULE`; WS event tipi `WSEvent.SALES_UPDATED`.
- Frontend `onWsEvent('sales_updated', ...)` ile dinler ve `.module` alanına göre tazeler
  (ör. otel-rezervasyon sayfası `data.module === 'hotel_reservation'` kontrolü yapar).

## Toplu Silme — `removal_candidates`

- `POST /reservations/upload` yanıtında, yükleme kapsamında (check-in + record-date)
  olup dosyada bulunmayan kayıtlar `removal_candidates` olarak döner (olası iptaller).
- Frontend bunları işaretletir; **silme `POST /reservations/bulk-delete` ile ID listesi
  gönderilerek** yapılır. İşaretlemek tek başına silmez — kullanıcı "Seçilenleri Sil" →
  onay akışını tamamlamalıdır (max 5000 ID, audit loglu).

## Onay (Approval) Entegrasyonu

- `room_types` CRUD onay kontrolünden geçer; handler `approval_executor.py` içindedir.
- Yükleme/toplu-silme gibi özel endpoint'ler onay akışından **hariç** tutulabilir.

Detay: `docs/modules/otel-rezervasyon.md`, `docs/modules/oda-tipleri.md`,

## Kontratlar (`contracts.py`, `sales.kontratlar`) — 2026-07-17

16 tur operatörünün kontrat arşivi + metadata (Faz 1). **AYRI RBAC modülü** (id 925) —
`sales.acente_mahsup` DEĞİL, çünkü executor `_HANDLERS` modül koduna tek handler bağlar
ve o kod RoomType CRUD'una tahsisli; ayrıca kontratlara özel onay workflow'u kurulabilsin.

- Mutasyon mantığı `services/contract_service.py`'de ORTAK (D1-2) — router +
  `_handle_sales_kontratlar` aynı fonksiyonları çağırır. Alt varlıklar tek `kind` ucu
  (`KIND_MODELS` sözlüğü); onay payload'ı `_kind` (+create'te `_contract_id`) taşır,
  tarihler `_coerce_date` ile normalize edilir.
- Belge yükleme onay DIŞI (dosya istisnası) ama `validate_upload_file` + audit +
  broadcast'li; dosyalar `uploads/contract_files/` altında UUID adla.
- Broadcast: `BroadcastModule.KONTRATLAR` (frontend `BROADCAST_MODULE.KONTRATLAR` —
  iki taraf senkron tutulur). Panel: `lib/components/sales/KontratlarPanel.svelte`
  (acente-mahsup sekmesi, görünürlük `hasPermission('sales.kontratlar','view')`).
- `data_confidence` disiplini: taranmış belgeden gelen değerler `scanned_approx`,
  elle düzeltilmiş/çelişkili değerler `needs_confirmation` — Faz 2-4 tüketicileri
  bu bayrağı dikkate almalı. Detay + faz yol haritası: `docs/modules/kontratlar.md`.

## Acente Grupları — `payment_alignment` API/UI + Onay Entegrasyonu (2026-09-01, denetim Y2)

**Bulgu:** `agency_groups.payment_alignment` (migration `f3c7a9b5d2e8`, 2026-08-13) yalnız SQL ile
set edilebiliyordu — şema, PATCH ve UI'da alan yoktu; canlıda NORDIC=`day_27`,
MUNFERIT/EXPEDIA=`checkin` elle girilmişti. Ayrıca `agency_groups` mutasyonları `check_approval`
çağırmıyordu (CLAUDE.md zorunlu kuralı).

**Yapılan:**
- `models/agency_group.py`: `PAYMENT_ALIGNMENT_PATTERN` + `is_valid_payment_alignment()` — tek yazım
  (`friday | month_end | checkin | day_1..day_31`, öncü sıfır yok). Şema (`pattern=`) ve service aynı
  deseni kullanır; `contract_projection_service` / `agency_settlement_service` / `auto_tagger` literal
  yerine `PAYMENT_ALIGN_*` sabitlerini kullanır.
- `services/agency_group_service.py` (YENİ, D1-2): `create_group` / `apply_group_update` /
  `delete_group` / `assign_agency` — router ve executor ORTAK çağırır; flush/commit çağıran yapar.
  Service `payment_alignment`'ı kendisi de doğrular (executor yolu pydantic'ten geçmez).
- `routers/sales/agency_groups.py`: `AgencyGroupCreate/Update/Response`'a `payment_alignment`;
  POST/PATCH/DELETE/`/assign` → `check_approval("sales.acente_mahsup", ...)`; payload `_kind`
  (`agency_group` | `agency_assign`) taşır çünkü modül kodu oda tipleriyle ortak. Sıra: 404/409 doğrulama
  → onay → service → commit → audit → broadcast.
- `approval/approval_executor.py`: `_make_acente_mahsup_handler` oda tipi factory handler'ını sarar;
  `_kind` yoksa oda tipi (birebir eski davranış), varsa acente grubu/atama.
- Frontend `satis/acente-mahsup/+page.svelte` Acente Ayarları modalı: "Ödeme günü" `Select`
  (Cuma / ay sonu / ayın N'i [+ gün alanı] / girişte) — `day_N` UI'da `alignMode`+`alignDay` olarak
  ayrılır, kaydederken birleştirilir; 202 yanıtı "onay sürecine alındı" toast'ı.
- **Bilinen sınır:** bekleyen-onay kontrolü `(module_code, entity_id)` ile → aynı id'li oda tipi ve grup
  talepleri birbirini geçici olarak 409 ile bloklar (talep kapanınca açılır).
- Test: `test_agency_groups.py` (+7: varsayılan friday, day_27, 7 geçersiz değer ×2 uç, tüm modlar,
  exclude_unset koruması, liste, service doğrulaması) + `test_approval_system.py::TestApprovalExecutor::
  test_agency_group_update_via_approval_regression` / `test_agency_assign_via_approval_regression`.

## Acente Finans — Kur Tarihi Kuralı (2026-09-01, denetim O1)

`agency_finance_service` artık AKIŞ kalemlerini (avans alındı/mahsup, haricen tahsilat, kesilen
fatura) hareketin **kendi tarihindeki** TCMB kuruyla çevirir (`_to_eur_on` + `utils/fx_rates.RateBook`;
USD/GBP çapraz) — T-Hesap/runway/grafik `_event_eur` ile aynı sayı. STOK kalemleri (açık alacak
kalanı, kalan 340 avans havuzu) **bugünkü** kurla (`_to_eur_today`; havuz native biriktirilir).
Kur yoksa 0 + `source_counts.skipped_no_rate` (1:1 varsayımı yok). `CROSS_EUR_CURRENCIES` tanımı
`services/fx_rates.py`'ye taşındı (`cash_flow/_helpers` re-export eder — services/ router import edemez).

## Acente Bazında Kişi Başı Fiyat (`reservations/pricing.py`, 2026-09-02)

`GET /reservations/agency-pp-prices?year=` — ay × acente **kişi-gece fiyatı** (aya düşen ciro ÷
ödeyen kişi-gece; `adult + child_paid`), pahalıdan ucuza. Ay dağıtımı doluluk kartıyla AYNI
stay-night SQL deseni (`generate_series`, `eur_total/nights`) — kopya değil, aynı kural; ödeyen
kişisiz/`nights=0` satırlar pay+payda birlikte atlanır. Satır anahtarı `g:<gid>` (grup,
`_agency_group_maps`) / `a:<PMS adı>` (grupsuz). Önceki yıl aynı ay `prev_pp_night`. GET-only →
onay dışı. UI: `ReservationsPanel.svelte` "Acente Bazında Kişi Başı Fiyat" kartı. Detay:
`docs/modules/otel-rezervasyon.md`.
