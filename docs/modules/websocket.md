# WebSocket Altyapısı

## Genel Bilgi
- **Endpoint:** `WS /api/ws`
- **Auth:** Upgrade request cookie'sinden JWT, fallback olarak auth mesajı
- **Router:** `backend/app/routers/ws.py`
- **Manager:** `backend/app/websocket/manager.py`
- **Frontend store:** `frontend/src/lib/stores/websocket.svelte.ts`

## Bağlantı Yönetimi
- **ConnectionManager** (singleton) — `dict[user_id, set[WebSocket]]` tutar
- Aynı kullanıcı birden fazla cihaz/sekmeden bağlanabilir
- **Ping/pong keepalive:** Client her 30 sn `ping` gönderir, server `pong` döner (sadece bu amaçla `setInterval` izinli)
- **Reconnect:** Bağlantı koparsa exponential backoff (1s → 2s → 4s → … max 30s, en çok 10 deneme)
- **Global canlandırma (R4, 2026-07-11):** `routes/dashboard/+layout.svelte` `window 'online'` +
  `document 'visibilitychange'` (görünür ve `wsState.connected === false` ise) event'lerinde
  `resetReconnect()` çağırır — deneme sayacı sıfırlanıp bağlantı yoksa yeniden kurulur
  (idempotent; bağlıysa no-op → mesajlaşma sayfasındaki yerel handler ile çakışmaz).
  Denemeler tükenince `wsState.reconnecting = false` yapılır → **Topbar bağlantı göstergesi**:
  bağlıyken hiçbir şey, reconnect sırasında sarı nokta + "Yeniden bağlanıyor", kalıcı kopuklukta
  kırmızı nokta + tıklanınca `resetReconnect()` çağıran buton (`wsState.everConnected` guard'ı
  ilk bağlanma penceresinde yanlış kırmızıyı engeller; `<md`'de yalnız nokta görünür).
- **Reconnect sonrası sentetik yeniden yayın:** her yeniden bağlanmada (ilk bağlantı HARİÇ) store
  yerel olarak `finance_updated` (`reconnect: true`) + `sales_updated` (`reconnect: true,
  synthetic: true`) yayınlar → açık sayfalar kopukluk sırasında kaçan event'leri telafi etmek için
  kendini tazeler. **`synthetic: true` kuralı:** payload-bağımlı `sales_updated` handler'ları bu
  bayrakta toast/otomatik-açma yan etkisi üretmeden yalnız **sessiz reload** yapmalıdır
  (ör. `ReservationsPanel.svelte`).

## Event Türleri

### Sistem Event'leri
| Event | Payload | Açıklama |
|---|---|---|
| `connected` | `{ online_users: [...], server_time: ISO }` | İlk bağlantıda başlangıç state |
| `user_online` | `{ user_id }` | Kullanıcı çevrimiçi oldu |
| `user_offline` | `{ user_id }` | Tüm bağlantılar kapandı |

### Mesajlaşma
`new_message`, `message_edited`, `message_deleted`, `message_read`, `typing`, `unread_updated`

### Bildirim
`notification` — her yeni bildirim için hedef kullanıcıya

### Finans (Nakit Akım)
`cash_flow_changed` — herhangi bir finans event'i (vendor tx, bank tx, check, credit payment) değiştiğinde debounce'lu broadcast (`finance_broadcast.py`)

### Sedna Senkronu
`sedna_sync_progress` — merkezi Sedna senkronunun adım adım ilerlemesi (aşağıdaki "Sedna Senkron İlerlemesi" bölümü)

### Onay Akışı
`approval_request` — onay bekliyor
`approval_decision` — onaylandı/reddedildi

## Broadcast Helper'ları
```python
from app.websocket.manager import manager

# Tek kullanıcıya
await manager.send_to_user(user_id, {"type": "notification", "data": {...}})

# Birden fazla kullanıcıya
await manager.send_to_users([u1, u2], {"type": "new_message", "data": {...}})

# Herkese (dikkatli kullan)
await manager.broadcast({"type": "announcement", "data": {...}})
```

## Debounce (Finans)
`backend/app/utils/finance_broadcast.py` — 500ms debounce window ile `cash_flow_changed` event'i birleştirilir (batch upload'ta 100 event tek mesajda)

## after_commit Yayın Sigortası (Faz 2 #15, 2026-07-12)

**Sorun sınıfı:** Bir mutasyon endpoint'i/executor'ı/import'u `finance_events`'e yazıyor ama
`broadcast_finance_update` çağırmayı unutuyor → açık sayfalar sessizce bayat kalıyordu (denetim
B sınıfı bulgular). **Kalıcı çözüm:** `backend/app/utils/finance_event_service.py` dosyasının
başındaki sigorta — finance_events'e yazan **HER yol** commit anında otomatik, modül-doğru
`finance_updated` yayınlar; elle broadcast unutulması artık bayatlık üretmez.

**Mekanizma:**
- `_SOURCE_TO_WS_MODULE` haritası `source_type` → `BroadcastModule` çevirir
  (bank→banks · check→checks · credit/cc_payment→credits · advance→advances ·
  vendor_payment→cariler · tax/recurring/rent_income/rent_expense/dividend/dividend_stopaj→accounting ·
  salary/withholding/sgk→hr).
- FE yazan tüm yollar `_mark_ws(source_type)` çağırır: `_upsert` (tüm `upsert_*` metodları buradan
  geçer), `invalidate`, `match` (iki taraf da), `unmatch`, `sync_tag` (bank). Modül adı
  process-global `_pending_ws_modules` set'ine eklenir.
- SQLAlchemy **Session `after_commit`** listener'ı set'i boşaltıp her modül için
  `notify_finance_update_sync(module, "update")` çağırır; `after_rollback` set'i temizler
  (gerçek rollback'te sahte yayın yok).
- `notify_finance_update_sync` (`finance_broadcast.py`) sync context'ten yayın yapar
  (BackgroundTasks gerekmez; `manager.send_to_all_sync` köprüsü) ve **modül-başına 500ms
  zaman-tabanlı süprese** uygular — art arda commit'ler (import: commit + FIFO sync + commit)
  event yağmuru üretmez.

**Bilinçli sınırlar:**
- **Tek-worker varsayımı:** pending set process-global — `finance_broadcast` debounce set'iyle
  aynı bilinçli varsayım (uvicorn tek worker).
- **Nested SAVEPOINT nüansı:** `after_rollback` yalnız gerçek rollback'te tetiklenir; SAVEPOINT
  (begin_nested) rollback'i pending'i temizlemez → nadir sahte event zararsızdır (frontend
  yalnız yeniden yükler).
- **Elle broadcast'ler geriye uyumlu:** mevcut `broadcast_finance_update` çağrıları kaldırılmadı
  — sync süprese + frontend echo-guard çifte yenilemeyi emer. **FE yazMAYAN mutasyonlar**
  (ör. oda tipi CRUD, bütçe kategorisi) sigortanın kapsamı DIŞINDA — elle broadcast zorunlu
  kalır; `tests/test_broadcast_guard.py` AST bekçi testi finans router'larındaki mutasyon
  endpoint'lerini tarayıp ne FE yazan (sigortalı) ne elle broadcast çağıran endpoint'i
  whitelist'li olarak yakalar.

## Sedna Senkron İlerlemesi — `sedna_sync_progress` (Faz 2 #18, 2026-07-12)

`POST /api/finance/sedna/sync-all` artık **bloklamaz**: anında `{started: true, total,
steps: [{key, label}]}` döner (yalnız izinli adımlar); adımlar arka plan işinde
(`sedna_sync.py::_run_sync_all_job` → `run_sync_all_steps` çekirdeği, kendi DB oturumu) koşar.
İlerleme **`sedna_sync_progress`** WS event'iyle herkese yayınlanır (Topbar canlı gösterir):

| Aşama | Payload |
|---|---|
| Adım başladı | `{ type: "sedna_sync_progress", key, label, index, total, status: "running" }` |
| Adım bitti | `{ ..., status: "ok" \| "error", summary }` |
| Koşu bitti | `{ type: "sedna_sync_progress", status: "done", ok_count, total, steps: [...] }` |
| İş çöktü | `{ status: "done", ok_count: 0, total: 0, error: "Senkron beklenmedik şekilde durdu" }` |

- Sabit: `WSEvent.SEDNA_SYNC_PROGRESS` (`app/constants.py`) ↔ frontend `WS_EVENT` (`realtime.ts`).
- **Modül yayını adım biter bitmez gider** (sona biriktirme kaldırıldı): her başarılı adım
  `notify_finance_update_sync(step.broadcast, "upload")` yayınlar → cariler adımı biter bitmez
  cariler ekranı tazelenir. Rezervasyon adımı ayrıca `sales_updated`
  (module=`hotel_reservation`, action=`upload`) yayınlar.
- Tazelik rozeti: `GET /api/finance/sedna/last-sync` (cari/çek `sedna://import` yüklemeleri +
  `sedna_recon_runs`; `oldest_hours` = kritik cari+çek adımlarının en eskisi) → Topbar
  "Son: X sa önce" (>24 saat amber).
- Cari/çek/mutabakat çekirdek adımları ayrıca **otomatik timer** ile koşar
  (`backend/cron_sedna_sync.py` + `sprenses-sedna-sync.timer` — detay `docs/modules/sunucu.md`).

## `BroadcastModule.EXCHANGE_RATES` (2026-07-12)

Döviz cron'unun (`backend/cron_fetch_exchange_rates.py` → internal broadcast endpoint'i,
`module=exchange_rates`) öteden beri kullandığı literal, `BroadcastModule.EXCHANGE_RATES`
sabiti olarak `app/constants.py` + `realtime.ts`'e eklendi (mevcut değer DEĞİŞMEDİ — yalnız
sabitlendi). Döviz sayfası ve diğer liste sayfaları bu modül event'ine `useLiveRefetch`
composable'ı (`frontend/src/lib/utils/liveRefetch.svelte.ts`) ile bağlanır — composable'ın
kendi bölümü bu dosyaya frontend tarafında ayrıca eklenir.

## Geliştirme Kuralları
- **Polling yasak** — tüm gerçek zamanlı veri WS üzerinden (CLAUDE.md kuralı)
- **Auth:** Cookie preferred; eski client'lar için `{ type: "auth", token: "..." }` mesajı da kabul edilir
- **Tek-oturum tutarlılığı (P1 güvenlik, 2026-06-17):** `ws.py:_sync_verify_user_session` artık HTTP yolu
  (`middleware/auth.py:get_current_user`) ile **birebir** — `active_session_id is None` → reddedilir.
  Eskiden WS yolu None'ı "kabul et" sayıyordu; bu, çıkış yapmış bir kullanıcının süresi dolmamış JWT'siyle
  WS'e yeniden bağlanmasına izin veriyordu (HTTP reddederken). İki yol artık aynı oturum kuralını uygular.
- **Hata yönetimi:** Send sırasında `WebSocketDisconnect` → bağlantı manager'dan temizlenir
- **Event tipi yeni eklerken:** 
  1. Backend `manager.send_to_user(...)` ile gönder
  2. Frontend `websocket.svelte.ts` içinde handler ekle
  3. İlgili store'u güncelle
  4. Bu dosyayı güncelle
