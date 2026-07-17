# Acente Mahsup & Nakit Akım (sales.acente_mahsup) — BİRLEŞİK SATIŞ MODÜLÜ

> **2026-07-09 birleştirme (kullanıcı kararı):** Satış'ın eski üç alt modülü —
> **Otel Rezervasyon** (`sales.hotel_reservation`), **Günlük Hareketler**
> (`sales.daily_reservations`) ve **Oda Tipleri** (`sales.room_types`) — RBAC'tan
> kaldırıldı; TÜM kabiliyetleri bu modülün sekmeleri olarak buraya taşındı.
> Migration `b3c9d5e7f1a2`: rol izinleri OR ile birleştirildi, approval_workflows/
> approval_requests module_code'ları yeni koda taşındı, eski modül satırları silindi.
> Backend endpoint path'leri DEĞİŞMEDİ (yalnız izin kodu değişti); veri tabloları aynen durur.

## 1. Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `sales.acente_mahsup` (Satış'ın TEK alt modülü) |
| **Üst modül** | Satış (`sales`) |
| **Frontend rota** | `/dashboard/satis/acente-mahsup` (`?tab=` deep-link destekli) |
| **Backend prefix** | `/api/sales/*` (acente-mahsup, reservations, daily-activity, room-types, agency-groups) |
| **İzin** | `sales.acente_mahsup` — `view` (tüm GET'ler) + `use` (XLS yükleme, Sedna senkron, oda tipi/acente grubu CRUD, toplu silme) |
| **Onay akışı** | Oda tipi CRUD `check_approval` üzerinden (executor handler anahtarı `sales.acente_mahsup`); projeksiyon/GET'ler muaf |
| **Para birimi** | EUR |

**Amaç:** Satışın tamamı tek sayfada. **8 sekme:**

| Sekme (`?tab=`) | İçerik | Kaynak bileşen / doküman |
|---|---|---|
| Genel Bakış (`ozet`) | Projeksiyon funnel + hedef ilerleme + acente tablosu | bu doküman |
| Rezervasyonlar (`rezervasyon`) | Eski Otel Rezervasyon sayfasının TAMAMI (XLS yükleme, KPI, doluluk, dağılımlar, acente gruplama) | `ReservationsPanel.svelte` · `otel-rezervasyon.md` |
| Günlük Hareketler (`hareket`) | Eski Günlük Hareketler sayfası (Sedna canlı gelen/iptal) | `DailyActivityPanel.svelte` · `gunluk-hareketler.md` |
| Rezervasyon & Ciro (`ciro`) | Acente × Durum kırılımı (drill-down) | bu doküman §5b |
| Alınan Avanslar (`avans`) | Avans mahsup durumu | bu doküman |
| Satış Faturaları (`fatura`) | Projeksiyon faturaları | bu doküman |
| Nakit Akım (`nakit`) | Vadeli tahsilat projeksiyonu + runway | bu doküman |
| Oda Tipleri (`oda`) | Eski Oda Tipleri CRUD'u | `RoomTypesPanel.svelte` · `oda-tipleri.md` |

Panel sekmeleri (rezervasyon/hareket/oda) **tembel mount** edilir ve ziyaret edilince
mount **kalır** (`visitedTabs` + `hidden` sınıfı) — sekme değişiminde state/veri korunur,
tekrar fetch yapılmaz. Projeksiyon gövdesi (senaryo barı + KPI) yalnız projeksiyon
sekmelerinde görünür.

**Hak Ediş'ten (finance.hakedis) farkı:** Hak Ediş **gerçek** muhasebe faturalarının
(120, TL) yaşlandırmasıdır — bugüne kadar kesilmiş fatura + tahsilat. Bu modül ise
rezervasyon cirosundan üretilen **ileri projeksiyondur** (EUR) ve hedef + kickback
senaryo katmanı ekler. İki modül farklı sorulara cevap verir; birbirinin yerine geçmez.

## 2. Dosya Haritası

**Backend:**
- `app/models/agency_group.py` — `AgencyGroup` modeline `term_days` + `kickback_percent`
  kolonları eklendi (projeksiyon konfigü).
- `app/services/agency_settlement_service.py` — `compute_settlement()` projeksiyon motoru
  (HTTP'siz, salt-okuma). Rezervasyon cirosu + konfig + avans + hedef → 5 sekmelik payload.
- `app/routers/sales/acente_mahsup.py` — GET endpoint (require_permission view, 60sn TTL cache).
- `app/routers/sales/__init__.py` — `/acente-mahsup` prefix ile bağlanır.
- `app/routers/sales/agency_groups.py` — CRUD şeması + PATCH/POST `term_days`/`kickback_percent`
  taşıyacak şekilde genişletildi (konfig düzenleme yüzeyi).
- `alembic/versions/e1a2c3d4f5b6_acente_mahsup_module.py` — kolonlar + modül + Admin RBAC.

**Frontend:**
- `src/routes/dashboard/satis/acente-mahsup/+page.svelte` — 8 sekmeli birleşik sayfa +
  senaryo girdileri + Acente Ayarları modalı.
- `src/lib/components/sales/ReservationsPanel.svelte` — Rezervasyonlar sekmesi (eski otel-rezervasyon sayfası).
- `src/lib/components/sales/DailyActivityPanel.svelte` — Günlük Hareketler sekmesi.
- `src/lib/components/sales/RoomTypesPanel.svelte` — Oda Tipleri sekmesi.
- `src/lib/config/navigation.ts` — Satış grubunda TEK NavItem (`I.scale` ikon).

**Test:** `backend/tests/test_acente_mahsup.py` (RBAC + shape + projeksiyon matematiği).

## 3. Veri Kaynakları (gerçek veri + senaryo)

| Girdi | Kaynak | Not |
|---|---|---|
| **Ciro (revenue)** | `reservations.eur_total` | Çıkış (checkout) ayında tanınır. Geçmiş ay = gerçekleşen, gelecek ay = mevcut ileri rezervasyon. |
| **Acenteler** | `agency_groups` (PMS üye adları, exact-strip eşleşme) | Grup dışı acenteler → **"Diğer"**. |
| **Vade** | `agency_groups.term_days` (konfig) | Nakit akımda ciro `round(vade/30)` ay ileri kaydırılır. Hak Ediş'in `receivable_terms`'inden **bağımsızdır**. |
| **Kickback** | `agency_groups.kickback_percent` (konfig) | Tutar = grup cirosu × oran. Sistemde daha önce yoktu — bu modülle geldi. |
| **Avanslar** | `receivable_service.compute_receivables` grup satırları (340) | `advance_received_tl`/`advance_consumed_tl` güncel TCMB kuruyla EUR'ya çevrilir. |
| **Yıl sonu hedefi + açılış nakit** | Endpoint query param (frontend'de localStorage) | Senaryo girdisi. Hedef boşsa gerçek ciro (forecast = 0). |

## 4. İş Kuralları (projeksiyon matematiği)

- **Ciro tanıma:** eur_total, rezervasyonun **çıkış ayına** yazılır ("fatura check-out'ta kesilir").
- **Gerçekleşen/İleri:** ay `(year, month) < (today.year, today.month)` ise gerçekleşen.
- **Hedef dağıtımı:** `additional = max(0, target − gerçek_toplam)`. Ek tahmin, İLERİ aylara
  **mevcut ileri rezervasyon ağırlığıyla** dağıtılır (ileri booking'i olmayan acente ek almaz;
  ileri booking yoksa ileri aylara eşit). → Forecast, gelecekte iş getirecek acentelere atfedilir.
- **Avans mahsubu (matris, grup × ay):** GERÇEKLEŞEN aylar gerçek `consumed` ile, İLERİ aylar
  `remaining = received − consumed` ile FIFO (erken ay önce) mahsup edilir. Mahsup edilen kısım
  vadede **tekrar tahsil edilmez** (avans zaten nakde alınmış, açılışa dahil).
- **Nakit akım:** her ay cirosu (mahsup düşülmüş) vadesine göre `m + round(vade/30)` ayına
  tahsilat olarak yazılır. Yıl dışına taşan tahsilat "ertesi yıla devreden". Kickback **Aralık**'ta düşülür.
- **Reconciliation:** `fatura toplamı = net + mahsup`; `funnel.net_collection = invoiced − advance_offset`.

## 5. API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/sales/acente-mahsup/` | `sales.acente_mahsup` view | Projeksiyon payload'ı. Query: `year`, `year_target` (EUR, boş=gerçek), `opening_cash` (EUR). 60sn TTL cache. |
| GET | `/api/sales/acente-mahsup/agency-status` | `sales.acente_mahsup` view | **Acente × Durum × Dönem** kırılımı (EUR tutar + rezervasyon adedi). Query: `granularity` (`day`/`month`/`year`, varsayılan `month`), `year` (month/day dönem yılı), `month` (yalnız `day`), **`group_id`** (acente grubu filtresi → üyeleri bireysel gösterir; **`0`=Diğer** = top-N dışı acenteler), **`agency`** (tek ham acente filtresi), **`top_n`** (kök tabloda tek tek gösterilecek en büyük grup sayısı, varsayılan **7**; kalanı "Diğer"). 60sn TTL cache. `compute_agency_status()`. |

Konfig düzenleme (vade/kickback) mevcut acente-grup endpoint'iyle yapılır:
`PATCH /api/sales/agency-groups/{id}` (izin: `sales.acente_mahsup` use) —
`term_days` (0-365) ve `kickback_percent` (0-100) alanları eklendi.

## 5b. Acente × Durum Kırılımı (2026-07-08)

"Rezervasyon & Ciro" sekmesine eklenen ikinci görünüm — projeksiyon **değil**, rezervasyonların
**anlık PMS durumuna** göre acente bazlı dağılımı. Motor: `agency_settlement_service.compute_agency_status()`.

- **Durum → doğal tarih eşlemesi** (kullanıcı kararı 2026-07-08): PMS `reservations.status` alanı üç
  değer taşır → **`Reservation`** = "Gelen rezervasyon" (giriş/`checkin_date`), **`InHouse`** =
  "İçeride" (giriş/`checkin_date`), **`CheckOut`** = "Çıkış yapan" (çıkış/`checkout_date`). Her durum
  KENDİ doğal tarihine göre dönemlere yazılır (gelen/içeride giriş, çıkış çıkış).
- **Granülerlik:** `day` (bir ayın günleri), `month` (bir yılın 12 ayı), `year` (bu yıl −2 … +1 = 4 yıl).
- **Ölçü:** her hücrede EUR tutarı (`eur_total` toplamı) **+** rezervasyon adedi (`count`).
- **Acente gruplama:** `compute_settlement` ile ORTAK `_agency_group_maps()` — `agency_groups` üyelik
  eşleşmesi, grup dışı → **"Diğer"**, aynı renk paleti. Tek kaynak → iki görünüm tutarlı.
- **Not — "içeride" snapshot'tır:** durum PMS'in o anki kaydı olduğundan geçmiş dönemlerde konuklar
  çıkış yapmıştır → "İçeride" pratikte yalnız güncel dönemde dolu görünür; geçmiş yıllar tamamen "Çıkış".
- **Filtre — tabloya tıklayarak drill-down (2026-07-08):** dropdown YERİNE tablo satırına tıklama.
  **Kök seviye — top-N rollup (`top_n`, varsayılan 7):** en yüksek 7 grup acente TEK TEK gösterilir;
  kalan gruplar + grup dışı acenteler tek **"Diğer"** satırında toplanır (**en altta**, tutara göre
  sıralanmaz). Bir **grup** satırına tıklama → o grubun **üye acentelerini bireysel** açar (`group_id`);
  **"Diğer"** satırı → **top-7 dışındaki** tüm acenteler bireysel (`group_id=0` = `_OTHER_ID`;
  küçük grupların üyeleri + grup dışı); bir **üye/acente** satırına tıklama → tek acente (`agency`,
  "Diğer"e düşmez, kendi adıyla). Üstteki **breadcrumb** (Tüm acenteler › Grup › Acente) ile geri
  dönülür. **Grand toplam top-N'den etkilenmez** (tümü dahil). Motor tek geçişte grup + ham-acente
  düzeyinde toplar (top-N sırası ve "Diğer" drill için gerekli). Payload `filter` aktif seçimi,
  `top_n`, `filter_options` (grup+acente tam evreni) taşır.

## 6. Frontend UI Yapısı

- **Tasarım kaynağı:** `scratchpad/tasarimlar/Sprenses Tasarımlar/Acente Mahsup & Nakit Akım.dc.html`.
- **Acente × Durum kırılımı (Rezervasyon & Ciro sekmesi):** granülerlik `SegmentedControl` (Günlük/
  Aylık/Yıllık) + `day` modunda ay `select`'i; dönem bazlı **yığılı çubuk** grafik (3 durum rengi) +
  acente × durum tablosu (tutar + adet). Yükleme yalnız sekme aktifken (`$effect` `activeTab==='ciro'`),
  granülerlik/ay/yıl/**filtre** değişince yeniden çekilir.
- **Drill-down etkileşimi:** tablo satırları tıklanabilir (`role=button`+`tabindex`+Enter/Space) —
  grup satırında `<ChevronRight>` göstergesi. `stTrail` breadcrumb yolunu tutar; `drillRow`/`gotoCrumb`
  ile ileri/geri. Grup/Diğer satırı yeni kök yol, üye satırı yola eklenir; `stFilter` (''/`g:<id>`/
  `a:<ad>`) fetch'i sürer. Filtreli görünümde tablo ham-acente bazında, aktif tek acente satırı tıklanamaz.
- **Bileşenler:** PageHeader, StatCard (KPI), SegmentedControl (5 sekme), MoneyInput (senaryo/kickback),
  Modal + Button (Acente Ayarları), EmptyState, TableSkeleton. Runway grafiği inline SVG (data-viz).
- **Tema:** lacivert/altın — `teal-700`=lacivert #1b2b45, `brass`=altın #bd9a45 (tema token eşlemesi).
  Tüm tutarlar `tabular-nums`.
- **Senaryo:** Yıl (select) + Yıl Sonu Hedefi + Açılış Nakit (MoneyInput EUR) → değişince debounce ile
  yeniden yüklenir, localStorage'a yazılır.

## 7. Audit Log Entegrasyonu

- Panonun kendisi salt-okuma → audit yok.
- Vade/kickback düzenleme `agency_groups` PATCH üzerinden → `entity_type=agency_group`, action `update`
  (mevcut audit ile kaydedilir).

## 8. Geliştirme Kuralları / Notlar

- **Salt-okuma:** yeni mutasyon endpoint'i eklenmedi → onay/executor handler gerekmez. Vade/kickback
  düzenleme bilinçli olarak mevcut (onaysız) `agency_groups` CRUD'una bağlandı.
- **"Diğer" oranı yüksekse** kullanıcı Acente Ayarları/Otel Rezervasyon gruplamasından acente ekleyerek
  düzeltir — pano grup dışı ciroyu şeffaf gösterir.
- **Avans yaklaşıklığı:** `advance_received` tüm-zamanlı 340 bakiyesidir (tek yıla değil); EUR'ya güncel
  kurla çevrilir. Projeksiyon için kabul edilebilir; kesin muhasebe için Satış Faturaları/Hak Ediş'e bakılır.

## Kontrat Gerçekleriyle Grup Konfigürasyonu (2026-07-17, Kontrat Faz 0)

16 tur operatörü kontrat analizi sonrası: 10 eksik grup açıldı (FUN & SUN, W2M, OTS, PEGAS,
NORDIC, DERTOUR, AKDEM, DIANA, IRELS, ROKET), bozuk BYEBYE grubu ALLTOURS'a birleştirildi
(aynı tüzel kişi/cari — kontrat kanıtı), `term_days`/`kickback_percent` kontrat değerlerine
çekildi (ör. ALLTOURS 21g/%3, ODEON 21g/%5, WEBRES 7g/%3, IRELS 0g/%1), `sedna_account_codes`
bilinen 340 hesaplarıyla dolduruldu → avans kod-öncelikli eşleşmesi deterministik.
`reservations.sedna_contrack_id` kolonu eklendi (migration `a1c4e7f9b2d5`) — Sedna Contrack
bağı, gelecek kontrat modülünün (fiyat doğrulama/allotment) anahtarı. Detay:
`backend/app/routers/finance/CLAUDE.md` "Kontrat Entegrasyonu Faz 0".
