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
