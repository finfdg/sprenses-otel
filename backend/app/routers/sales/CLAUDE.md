# Satış Modülü — Geliştirici Rehberi

Satış alt modülleri: `reservations/` (otel rezervasyon), `room_types`, `agency_groups`,
`flights` (uçak — widget tabanlı, yedek API client). Bu dosya satış modülüne katkı
kurallarını içerir.

## Yapı

- `reservations/` paketi: `uploads` (XLS yükleme + RecId upsert + `removal_candidates`),
  `listing`, `summary` (KPI + doluluk), `occupancy` (günlük drill-down).
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
