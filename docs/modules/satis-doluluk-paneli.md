# Satış & Doluluk Paneli Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `sales.hotel_reservation` (mevcut modül — YENİ RBAC modülü yok) |
| **Üst modül** | `sales` (Satış) |
| **Frontend rota** | `/dashboard/satis` |
| **Backend prefix** | Yok — yalnızca mevcut endpoint'leri tüketir (sıfır yeni backend) |
| **İzin seviyesi** | `view` (`sales.hotel_reservation`) — salt-okunur panel |
| **Onay akışı** | Yok — mutasyon içermez (yalnız okuma), `check_approval`/audit gerekmez |

## Amaç

Otel satış ve doluluk verisini **tek bakışta** sunan salt-okunur özet paneli.
Otel Rezervasyon modülünün dağınık metriklerini (KPI + dağılımlar) yöneticinin
hızlı okuyabileceği kart + grafik düzeninde toplar. Hiçbir veri kendi tablosundan
gelmez — tümü mevcut özet endpoint'lerinden okunur.

Panel, Yönetim Paneli'nin (`/dashboard/yonetim`) satış-odaklı, daha ayrıntılı
muadilidir: orada 10 üst-düzey KPI varken, burada doluluk trendi + acente/oda
tipi/pansiyon/uyruk kırılımları gösterilir.

## Dosya Haritası

### Backend (yeni dosya YOK — mevcut endpoint'ler tüketilir)
| Dosya | Açıklama |
|---|---|
| `backend/app/routers/sales/reservations/summary.py` | `GET /api/sales/reservations/summary` — tüm KPI + dağılımlar (`kpi`, `monthly`, `by_agency`, `by_nation`, `by_room_type`, `by_board`, `pickup`, `los_buckets`, `lead_time`). İzin: `sales.hotel_reservation`. |
| `backend/app/routers/sales/reservations/occupancy.py` | `GET /api/sales/reservations/daily-occupancy` — gün gün doluluk (panelde şimdilik kullanılmıyor; ileride drill-down için ayrılmış). İzin: `sales.hotel_reservation`. |
| `backend/app/routers/sales/reservations/daily_activity.py` | `GET /api/daily-activity/summary` — gelen/iptal günlük hareket + `cancel_rate`. İzin: `sales.daily_reservations` (opsiyonel kart). |
| `backend/app/schemas/reservation.py` | Yanıt şemaları (`SummaryResponse`, `KpiData`, `MonthlyRow`, `AgencyRow`, `NationRow`, `TypeRow`, `BoardRow` …) — alan adlarının kaynağı. |

### Frontend
| Dosya | Açıklama |
|---|---|
| `frontend/src/routes/dashboard/satis/+page.svelte` | Panel sayfası (yeni) — PageHeader + dönem seçici + KPI kartları + SVG doluluk trendi + dağılım kartları + opsiyonel günlük hareket kartı |
| `frontend/src/lib/config/navigation.ts` | `sales` NavGroup'una NavItem (`sales.hotel_reservation`, href `/dashboard/satis`) + `I.chartBar` ikon path'i eklendi → sidebar linki + route guard otomatik |

## Veri Kaynakları / Endpoint'ler

Panel **üç** mevcut GET endpoint'ini tüketir; hiçbir yeni endpoint eklenmez.

| Endpoint | Kullanım | İzin | Notlar |
|---|---|---|---|
| `GET /api/sales/reservations/summary` | Birincil veri kaynağı — tüm KPI ve dağılımlar | `sales.hotel_reservation` view | Dönem filtresi `?start_date=YYYY-01-01&end_date=YYYY-12-31` (yıl) veya filtresiz (tüm dönem). KPI alanları **`kpi` nesnesi altında nested** (`kpi.occupancy_pct`, `kpi.adr`, `kpi.total_room_nights`, `kpi.total_rez`, `kpi.avg_los` …). |
| `GET /api/daily-activity/summary` | Opsiyonel günlük hareket kartı | `sales.daily_reservations` view | Yalnızca `hasPermission('sales.daily_reservations','view')` ise çağrılır. Sedna canlı sorgu → kapalıysa (`SEDNA_PASSWORD` yok / 503) kart sessizce gizlenir (hata loglanır). Son 30 gün penceresi kullanılır (geniş aralık Sedna'yı yavaşlatır). |
| `GET /api/sales/reservations/daily-occupancy` | (Ayrılmış — şu an panelde kullanılmıyor) | `sales.hotel_reservation` view | İleride aylık bar'ın gün-bazlı drill-down'ı için. |

### Dönem seçimi neden yıl bazlı?
`summary` endpoint'i ay değil **tarih aralığı** (`start_date`/`end_date`) ile
filtreler. Bu yüzden dönem seçici "Tüm Dönem" + son/gelecek yıllar (YYYY) sunar;
seçilen yıl `YYYY-01-01 … YYYY-12-31` aralığına çevrilir. Aylık doluluk trendi
zaten her ay için ayrı satır (`monthly[]`) döndüğünden, yıl içi ay kırılımı grafikte
görünür.

## Frontend UI Yapısı

Kanonik panel iskeleti (Yönetim Paneli analog) — yukarıdan aşağıya:

1. **PageHeader** — `<h1>` "Satış & Doluluk Paneli" + açıklama; `actions` snippet'inde
   dönem seçici (`Select`, `aria-label="Dönem seçimi"`) — değişince yeniden fetch.
2. **KPI kartları** (`StatCard`, `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5`):
   - Doluluk % (accent `teal`, ikon `BarChart3`)
   - ADR € (accent `blue`, ikon `Euro`)
   - Oda Gecesi (accent `gray`, ikon `BedDouble`)
   - Toplam Rezervasyon (accent `emerald`, ikon `CalendarCheck`)
   - Ort. Konaklama/LOS (accent `gray`, ikon `Clock`)
3. **Aylık Doluluk Trendi** — el-yapımı **inline SVG çizgi grafik** (`summary.monthly`'nin
   `occupancy_pct`'i). Döviz panelindeki pattern (`CHART_W`/`CHART_H`/`PAD`, `chartPath`
   `$derived.by`, yatay grid + hover tooltip, `<path stroke="#0d9488">`). Grafik kütüphanesi
   yok. Y ekseni 0–100 (veya tepe değer) arası %.
4. **Dağılım kartları** (beyaz `rounded-2xl border-gray-200 shadow-sm`, CSS yüzde bar'ları
   `h-2 bg-gray-100 → bg-teal-600`):
   - Acente Bazında Geceleme (`by_agency`, ilk 8 — bar = geceleme/maksimum)
   - Oda Tipi Doluluğu (`by_room_type`, ilk 8 — bar = doluluk %)
   - Pansiyon Tipi (`by_board` — bar = ciro/maksimum)
   - Uyruk İlk 10 (`by_nation` ilk 10 — bar = ciro/maksimum)
5. **Opsiyonel Günlük Hareket** kartı — yalnız `sales.daily_reservations` view izni +
   veri varsa: yeni vs iptal sayı/ciro + `StatusBadge` ile iptal oranı (%25 üstü `warning`,
   altı `info`).

### State yönetimi
- Svelte 5 runes: `$state` (summary/daily/loading/period/hoverIndex), `$derived` (canView/kpi/
  dağılım kısayolları/grafik path'leri).
- **Yükleme:** `TableSkeleton` (spinner/"Yükleniyor…" YASAK).
- **Boş/yetkisiz:** `EmptyState` (ikon `BarChart3`).
- **Gerçek zamanlılık:** `onWsEvent('sales_updated', …)` — `data.module === 'hotel_reservation'`
  (sabit: `BROADCAST_MODULE.HOTEL_RESERVATION`) ise özet yeniden çekilir. **Polling yok.**
  `onDestroy`'da abonelik temizlenir.
- **Hata yönetimi:** her `catch` → `console.error` + `showToast('… yüklenemedi', 'error')`
  (günlük hareket istisnası: Sedna kapalıysa kart sessizce gizlenir ama hata loglanır —
  opsiyonel/dış-bağımlı veri).

### Renk şeması
- Doluluk = teal (ana), ADR = blue, sayısal = gray, rezervasyon = emerald.
- Bar dolgusu `bg-teal-600` (kart içi göstergesi); buton/birincil teal-700 `Button`/`Select`'ten.
- En açık gövde metni `text-gray-500` (gray-400 değil — AA).
- İkonlar yalnızca **Lucide** (`BarChart3`, `Euro`, `BedDouble`, `CalendarCheck`, `Clock`,
  `Building2`, `Globe`, `UtensilsCrossed`, `TrendingUp`, `TrendingDown`).

## İzin / Audit / Onay

- **İzin:** `canView = hasPermission('sales.hotel_reservation','view')`. Yetki yoksa sayfa
  `EmptyState` ("Erişim yetkiniz yok") gösterir; backend `require_permission` asıl kapıdır,
  route guard (`requiredModuleForPath('/dashboard/satis') → sales.hotel_reservation`)
  derinlemesine savunmadır.
- **Audit / Onay:** Yok. Panel mutasyon içermez (salt-okuma) → `check_approval` ve audit
  gerekmez (CLAUDE.md: salt-okuma GET'ler onaydan muaf).

## Geliştirme Kuralları

1. **Sıfır yeni backend:** Bu panel yalnızca mevcut endpoint'leri tüketir. Yeni metrik
   gerekirse önce `summary.py` yanıtına alan eklenir (oradaki iş kuralları + testleriyle),
   panel sonra okur. Panele backend mantığı koyma.
2. **KPI alanları `kpi.*` altında:** `summary` yanıtında KPI'lar düz değil, `kpi` nesnesi
   içinde nested. Yeni KPI eklerken `summary.kpi.<alan>` yolunu kullan.
3. **Route çakışması yok:** `/dashboard/satis` grup prefix'i ile aynı; NavItem'ı tam-eşleşme
   (`prefixActive` yok) ile bağlanır. Route guard en-uzun-href kazandığından
   `/dashboard/satis/otel-rezervasyon` gibi alt rotalar `/dashboard/satis`'ı **gölgelemez**
   (pathname tam `/dashboard/satis` olduğunda yalnızca panel eşleşir).
4. **Günlük hareket opsiyonel ve hata-toleranslı:** `sales.daily_reservations` izni yoksa
   veya Sedna kapalıysa kart **hiç render edilmez**; bu beklenen davranıştır, panelin geri
   kalanını bloklamaz.
5. **Tasarım sistemi zorunlu:** StatCard/PageHeader/Select/StatusBadge/EmptyState/TableSkeleton/
   Lucide — elle stil/buton/emoji yok. Tek el-yapımı istisna: doluluk trendi SVG'si (grafik
   kütüphanesi olmadığından, döviz panelindeki yerleşik pattern).
6. **Türkçe karakterler:** Tüm görünür metin doğru Türkçe karakterlerle (Doluluk, Ortalama,
   İptal, Uyruk, Acente, Pansiyon…). ASCII-Türkçe yasak.
