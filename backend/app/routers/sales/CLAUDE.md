# Satış Modülü — Geliştirici Rehberi

> **2026-07-09 BİRLEŞTİRME:** Satış'ın RBAC modülü artık TEK: **`sales.acente_mahsup`**
> (Acente Mahsup & Nakit Akım). Eski `sales.hotel_reservation`, `sales.daily_reservations`
> ve `sales.room_types` modülleri kaldırıldı (migration `b3c9d5e7f1a2`); bu paketteki TÜM
> router'lar `require_permission("sales.acente_mahsup", "view"|"use")` kullanır ve
> `room_types` onayı executor'da `sales.acente_mahsup` anahtarıyla çalışır. Router/endpoint
> path'leri DEĞİŞMEDİ. UI tek sayfa: `/dashboard/satis/acente-mahsup` (8 sekme; eski üç
> sayfa `lib/components/sales/{Reservations,DailyActivity,RoomTypes}Panel.svelte` sekmeleri oldu).

Router paketleri: `reservations/` (otel rezervasyon + günlük hareketler), `room_types`,
`agency_groups`, `acente_mahsup` (projeksiyon panosu). Bu dosya satış
modülüne katkı kurallarını içerir.

## Acente Mahsup & Nakit Akım (`acente_mahsup.py`, `sales.acente_mahsup`)

- **Salt-okuma projeksiyon** (GET-only, 60sn TTL cache, `require_permission view`) → onay/broadcast
  kapsam dışı (Yönetim Paneli deseni). Mutasyon YOK.
- Motor: `services/agency_settlement_service.compute_settlement()` — rezervasyon cirosu (EUR,
  **çıkış ayında** tanınır) + `agency_groups` konfigü (`term_days`/`kickback_percent`) + gerçek
  avanslar (`receivable_service.compute_receivables` grup satırları, güncel kurla EUR) + yıl sonu
  hedef senaryosu → 5 sekmelik payload.
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
  `listing`, `summary` (KPI + doluluk), `occupancy` (günlük drill-down),
  `daily_activity` (**Günlük Hareketler** — `sales/__init__.py`'de AYRI prefix
  `/daily-activity` ile bağlanır (izin: `sales.acente_mahsup` view);
  Sedna CANLI gelen/iptal akışı, yerel tablo yok — iptal tarihçesi senkronda silindiğinden
  yerel veriyle cevaplanamaz. EUR çevrimi `sedna_import._currency_to_eur_factors` ile ORTAK.
  Salt-okunur → onay/broadcast kapsam dışı. Detay: `docs/modules/gunluk-hareketler.md`).
- `room_types`, `agency_groups`: oda tipi ve acente gruplama CRUD.
- `flights`: Travelpayouts/Aviasales — **frontend widget** embed kullanılır; backend
  client (`utils/travelpayouts_client.py`) yedekte tutulur (detay: `docs/modules/ucak-rezervasyon.md`).

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
`docs/modules/ucak-rezervasyon.md`.
