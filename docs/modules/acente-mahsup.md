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

**Amaç:** Satışın tamamı tek sayfada.

> **2026-07-19 BASİT TASARIM (kullanıcı kararı — finfdg GitHub yüklemesi):** Sayfa,
> repo yedeğine yüklenen "Acente Mahsup ve Nakit Akım.zip" tasarımına göre yeniden
> kuruldu. Eski 5 projeksiyon sekmesi (Genel Bakış / Rezervasyon & Ciro / Alınan
> Avanslar / Satış Faturaları / eski Nakit Akım) ve senaryo barı (hedef + açılış nakit)
> KALDIRILDI; içerikleri 4 yeni tasarım sekmesinde toplandı. Backend endpoint'leri
> ve `compute_settlement` senaryo parametreleri (year_target/opening_cash) API'de
> DURUYOR (geri uyumlu) — yalnız UI'dan çağrılmıyor. Alt-çizgili sekme barı + Doluluk
> chip kartları (mobilde yatay kaydırma + nokta göstergesi) tasarımdan geldi.

| Sekme (`?tab=`) | İçerik | Kaynak bileşen / doküman |
|---|---|---|
| Doluluk (`doluluk`, varsayılan) | Yıllık aylık doluluk barları (gerçekleşen lacivert + ileri çizgili pirinç), ay satırına tıkla → günlük görünüm (masaüstü sütun / mobil satır), bugün kırmızı işaretli; üstte 3 chip (bugün / cari ay / yıl ort.) | `OccupancyPanel.svelte` · bu doküman §5c |
| Acenteler (`acente`) | Acente Dağılımı — Bireysel / Gruplu (grup satırı → üyeler açılır), pay bazlı bar + toplam | `AgencyDistributionPanel.svelte` |
| Günlük Hareketler (`hareket`) | Son 14 günün gün kartları (gelen/iptal/net) → tıklayınca Aylık Doluluk Etkisi + hareket listesi (Sedna canlı) | `DailyMovesPanel.svelte` · `gunluk-hareketler.md` |
| Nakit Akım (`nakit`) | Avans/fatura/mahsup/vadesi-geçen KPI'ları + Tahsilat Takvimi (12 ay + devreden) + Acente Finansal Özet (grup başına 6 kalem bar grafiği) + Vadesi Geçen Alacaklar | `SalesCashFlowPanel.svelte` · bu doküman §5d |
| Rezervasyonlar (`rezervasyon`) | Eski Otel Rezervasyon sayfasının TAMAMI (XLS yükleme, KPI, dağılımlar, acente gruplama) | `ReservationsPanel.svelte` · `otel-rezervasyon.md` |
| Oda Tipleri (`oda`) | Eski Oda Tipleri CRUD'u | `RoomTypesPanel.svelte` · `oda-tipleri.md` |
| Kontratlar (`kontrat`) | Kontrat arşivi — AYRI izin (`sales.kontratlar` view ile görünür) | `KontratlarPanel.svelte` · `kontratlar.md` |

Tüm sekmeler **tembel mount** edilir ve ziyaret edilince mount **kalır** (`visitedTabs` +
`hidden` sınıfı) — sekme değişiminde state/veri korunur, tekrar fetch yapılmaz. `year`
state'i sayfa düzeyinde TEKtir (tasarım kararı): Doluluk / Acenteler / Nakit Akım
sekmelerindeki yıl seçicileri aynı değeri paylaşır. "Acente Ayarları" (vade + kickback)
modalının açma butonu **Acente Dağılımı kartının başlık satırındadır** (2026-07-19 —
PageHeader'dan taşındı; `AgencyDistributionPanel`'e `canConfig` + `onSettings` prop'larıyla
geçirilir, modal state'i sayfada kalır) — Tahsilat Takvimi'nin vade girdisi buradan düzenlenir.

**§5c Doluluk verisi:** `GET /sales/reservations/occupancy-overview?year=` (yeni,
2026-07-19) — 12 ayın oda-gece toplamı `past_nights` (gece tarihi ≤ bugün, İstanbul TZ) /
`future_nights` kırılımıyla + chip alanları (`today_rooms/today_pct`, `current_month`,
`year_pct`). Günlük görünüm mevcut `daily-occupancy?month=` endpoint'ini kullanır.
Gece dağıtımı `summary` ile birebir aynı (generate_series).

**§5c-ciro + yıl karşılaştırma (2026-07-21):** `occupancy-overview` aylarına
`eur` / `past_eur` / `future_eur` (gece bazlı orantılı ciro: `eur_total / nights` —
summary/agency-status ile AYNI dağıtım) ve yanıta `year_eur` eklendi. UI: aylık barların
üzerinde `N oda-gece · X K/M €` etiketi (mobilde sağ kolonda), günlük görünümde sütun içi
dikey ciro etiketi (`h ≥ %40` olan barlarda; ileri günlerde koyu, gerçekleşende beyaz metin)
+ tooltip/mobil satırda ciro. **Karşılaştır butonu** (yalnız aylık görünüm, `Button` sm):
önceki 2 yılın overview'u çekilir (`compareCache` — geçmiş yıl verisi değişmediğinden yıl
başına 1 fetch), verisi olmayan yıl (`year_room_nights == 0`) gizlenir; her ayın altına
ince bar — 1. önceki yıl `bg-brass`, 2. `bg-gray-400` (lejant yıl etiketli). Karşılaştırma
barı tek parça (gerçekleşen/ileri kırılımı ana yıla özgü).

**§5d Nakit Akım payload ekleri (2026-07-19, `compute_settlement`):**
- `cashflow.calendar.months[12]`: `{total, collected, overdue, pending, cumulative}` —
  collected yalnız CARİ AYDAN ÖNCEKİ aylarda (tahsil edildi varsayımı), pending cari+ileri
  aylarda, `overdue` GERÇEK hak ediş gecikmesi (aşağıda). Kümülatif salt tahsilat koşan
  toplamı; `calendar.devreden` = `cashflow.tail`. Kırmızı KIRPILMAZ — projeksiyon (coll)
  ile muhasebe (overdue) ayrı kaynak, kırpmak KPI mutabakatını bozar.
- `overdue.{total,rows}`: `compute_receivables` grup satırlarının `overdue_tl` değeri
  güncel kurla EUR'a çevrilir (avanslarla aynı yöntem); satırda `max_days` +
  `oldest_due_month`. Vade AYINA dağıtım: geçmiş aya düşen açık vade → o ay; artan
  (cari ay içinde geçen) → cari ay; yıl öncesinden devreden → Ocak. Yalnız
  `year == bugünün yılı` iken hesaplanır (geçmiş/gelecek yıl seçiminde boş).
- **`advances` genişletmesi (2026-07-19 akşam — "Acente Finansal Özet" grafiği):**
  `advances.rows[]` artık avans alanlarına ek `revenue` (seçili yıl grup cirosu, EUR),
  `invoiced` (kesilen TÜM faturalar, `invoiced_tl`), `collected` (haricen tahsilatlar,
  `collected_external_tl` — kasa/banka; **'120-340 VİRMAN' avans-mahsup bacakları HARİÇ**,
  yoksa mahsup barıyla çift sayılırdı — ALLTOURS'ta kanıtlandı, `hakedis.md`) ve
  `overdue` (grup vadesi geçen) taşır;
  blok toplamlarına `total_invoiced`/`total_collected` eklendi. Fatura/tahsilat/avans
  muhasebe KÜMÜLATİFİDİR (yıl filtresi yok, güncel kurla EUR) — ciro ise seçili yıla
  aittir; UI açıklaması bu farkı belirtir. Satır seçimi değişti: yalnız avansı olan
  değil, 6 kalemden HERHANGİ biri > 0 olan grup listelenir (sıralama: ciro ↓, avans ↓).
  UI: `SalesCashFlowPanel` "Acente Avans & Mahsup" bölümü **"Acente Finansal Özet"**
  gruplu bar grafiğine dönüştü — grup başına 6 yatay bar (alınan avans teal-700 ·
  rezervasyon cirosu teal-500 · kesilen fatura brass · kalan avans borcu amber-500 ·
  haricen tahsilat emerald-500 · vadesi geçen red-600), tüm acenteler/kalemler ortak
  ölçekli (global max), sıfır değer "—".

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
- `src/lib/components/sales/OccupancyPanel.svelte` — Doluluk sekmesi (aylık/günlük görünüm).
- `src/lib/components/sales/AgencyDistributionPanel.svelte` — Acenteler sekmesi (Bireysel/Gruplu).
- `src/lib/components/sales/DailyMovesPanel.svelte` — Günlük Hareketler sekmesi (gün kartları;
  eski `DailyActivityPanel.svelte` 2026-07-19 basit tasarımla SİLİNDİ — git geçmişinde durur).
- `src/lib/components/sales/SalesCashFlowPanel.svelte` — Nakit Akım sekmesi.
- `src/lib/utils/salesDesign.ts` — panellerin ortak saf yardımcıları (eurCompact, grup rollup,
  konaklama-gece yayılımı, çizgili doku) + `salesDesign.test.ts` (16 vitest).
- `src/lib/components/sales/ReservationsPanel.svelte` — Rezervasyonlar sekmesi (eski otel-rezervasyon sayfası).
- `src/lib/components/sales/RoomTypesPanel.svelte` — Oda Tipleri sekmesi.
- `src/lib/config/navigation.ts` — Satış grubunda TEK NavItem (`I.scale` ikon).

**Test:** `backend/tests/test_acente_mahsup.py` (RBAC + shape + projeksiyon matematiği +
tahsilat takvimi/overdue) · `backend/tests/test_reservations.py::test_occupancy_overview_*`.

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
| GET | `/api/sales/acente-mahsup/` | `sales.acente_mahsup` view | Projeksiyon payload'ı (+`cashflow.calendar` ve `overdue` blokları, §5d). Query: `year`, `year_target` (EUR, boş=gerçek), `opening_cash` (EUR) — son ikisi 2026-07-19 basit tasarımdan beri UI'dan gönderilmez, API'de geri-uyumlu durur. 60sn TTL cache. |
| GET | `/api/sales/reservations/occupancy-overview` | `sales.acente_mahsup` view | **Doluluk genel bakışı** (2026-07-19): 12 ayın gerçekleşen/ileri oda-gece kırılımı + bugün/cari ay/yıl chip verileri. Query: `year`. 2026-07-21: ay başına `eur/past_eur/future_eur` + `year_eur` (gece bazlı orantılı ciro — bar etiketi + yıl karşılaştırma). |
| GET | `/api/sales/acente-mahsup/agency-status` | `sales.acente_mahsup` view | **Acente × Durum × Dönem** kırılımı (EUR tutar + rezervasyon adedi). Query: `granularity` (`day`/`month`/`year`, varsayılan `month`), `year` (month/day dönem yılı), `month` (yalnız `day`), **`group_id`** (acente grubu filtresi → üyeleri bireysel gösterir; **`0`=Diğer** = top-N dışı acenteler), **`agency`** (tek ham acente filtresi), **`top_n`** (kök tabloda tek tek gösterilecek en büyük grup sayısı, varsayılan **7**; kalanı "Diğer"). 60sn TTL cache. `compute_agency_status()`. |

Konfig düzenleme (vade/kickback) mevcut acente-grup endpoint'iyle yapılır:
`PATCH /api/sales/agency-groups/{id}` (izin: `sales.acente_mahsup` use) —
`term_days` (0-365) ve `kickback_percent` (0-100) alanları eklendi.

## 5b. Acente × Durum Kırılımı (2026-07-08)

> **2026-07-19 not:** Bu kırılımın UI'ı ("Rezervasyon & Ciro" sekmesi) basit tasarımla
> KALDIRILDI; `agency-status` endpoint'i ve motoru geri-uyumluluk için DURUYOR (başka
> tüketici bağlanabilir). Acente analizi artık "Acenteler" sekmesindedir.

Rezervasyonların **anlık PMS durumuna** göre acente bazlı dağılımı (projeksiyon **değil**).
Motor: `agency_settlement_service.compute_agency_status()`.

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

## 6. Frontend UI Yapısı (2026-07-19 basit tasarım)

- **Tasarım kaynağı:** repo yedeğindeki `Acente Mahsup ve Nakit Akım.zip` (finfdg,
  commit `a52a789`) — 4 sekmeli dc.html; renkler tema token'larıyla birebir
  (`teal-700`=#1b2b45 lacivert, `teal-500`=#56719a bar dolgusu, `brass`=#bd9a45,
  çizgili ileri-doku `salesDesign.FUTURE_STRIPE`).
- **Sayfa iskeleti:** PageHeader (yalnız başlık — açıklama ve aksiyon yok; Acente Ayarları
  butonu Acente Dağılımı kartında, 2026-07-19) → Doluluk chip'leri (StatCard ×3,
  yalnız Doluluk sekmesinde; mobilde snap-scroll + nokta göstergesi) → **alt-çizgili sekme
  barı** (tasarım deseni; SegmentedControl değil) → aktif panel. Sekmeler keep-alive.
- **Paneller:** her tasarım sekmesi kendi bileşeninde (`OccupancyPanel` /
  `AgencyDistributionPanel` / `DailyMovesPanel` / `SalesCashFlowPanel`) — kendi fetch'i,
  `tick` prop'u (sayfadan canlı-yenileme tetiği) ve ortak `year` prop'u ile.
- **Bileşenler:** PageHeader, StatCard (chip + Nakit KPI), SegmentedControl (Günlük/Aylık,
  Bireysel/Gruplu), MoneyInput (kickback), Modal + Button (Acente Ayarları), EmptyState,
  TableSkeleton. Tüm tutarlar `tabular-nums`; kompakt EUR `salesDesign.eurCompact`
  ("1,23 M €" tasarım biçimi).
- **Kaldırılan (2026-07-19):** senaryo barı (hedef/açılış nakit + localStorage), funnel,
  hedef ilerleme çubuğu, runway SVG'si, projeksiyon fatura tablosu, Acente × Durum
  drill-down UI'ı, eski `DailyActivityPanel`.

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
