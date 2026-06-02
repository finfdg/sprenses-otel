# Mesajlaşma Modülü — Bildirim Sistemi

## Genel Bakış

Mesajlaşma modülü üç katmanlı bir bildirim sistemi kullanır:
1. **WebSocket (WS)** — Uygulama açıkken gerçek zamanlı bildirimler
2. **Push Notification (VAPID)** — Uygulama kapalıyken tarayıcı bildirimleri
3. **Ses Bildirimi** — Uygulama açıkken sesli uyarı

> **Kural:** Polling (`setInterval` + HTTP) kesinlikle yasaktır. Tüm gerçek zamanlı veri WebSocket event-driven olmalıdır.

---

## 1. WebSocket Bildirim Akışı

### Bağlantı ve Kimlik Doğrulama

```
Client bağlanır → {"type": "auth", "token": "JWT"} gönderir
  → Server doğrular → {"type": "connected", "user_id": X, "online_user_ids": [...]} döner
```

- İlk bağlantıda `connected` event'i online kullanıcı listesini içerir — ayrıca HTTP çağrısı gerekmez
- Keepalive: Her 30 saniyede `{"type": "ping"}` gönderilir

### Event Tipleri

| Event | Yön | Açıklama | Alıcılar |
|---|---|---|---|
| `auth` | C→S | JWT ile kimlik doğrulama | — |
| `ping` | C→S | Bağlantı canlı tutma (30sn) | — |
| `connected` | S→C | Bağlantı onayı + online kullanıcılar | Bağlanan kullanıcı |
| `new_message` | S→C | Yeni mesaj bildirimi | Konuşma üyeleri (gönderen hariç) |
| `message_edited` | S→C | Mesaj düzenlendi | Konuşma üyeleri (düzenleyen hariç) |
| `message_deleted` | S→C | Mesaj silindi (soft delete) | Konuşma üyeleri (silen hariç) |
| `read_status` | S→C | Okundu bilgisi güncellendi | Konuşma üyeleri (okuyan hariç) |
| `typing` | C→S / S→C | Yazıyor göstergesi | Hedef kullanıcı(lar) |
| `user_status` | S→C | Online/offline durum değişikliği | Konuşma partnerleri |
| `new_conversation` | S→C | Yeni konuşma oluşturuldu | Hedef kullanıcı |
| `group_member_added` | S→C | Gruba üye eklendi | Grup üyeleri |
| `group_member_removed` | S→C | Gruptan üye çıkarıldı | Grup üyeleri |
| `group_name_changed` | S→C | Grup adı değişti | Grup üyeleri |
| `group_admin_changed` | S→C | Grup admin değişikliği | Grup üyeleri |

### Mesaj Teslim Akışı (End-to-End)

```
Kullanıcı mesaj gönderir (POST /api/messages/conversations/{id})
  ↓
1. İzin kontrolü: require_permission("messaging", "use")
2. Rate limit kontrolü
3. DB: Message kaydı oluştur + Conversation.updated_at güncelle
4. DB: Gönderenin last_read_at güncelle
5. Audit log kaydı
  ↓
6. WS broadcast: manager.send_to_users(diğer_üyeler, new_message event)
7. Push bildirim (arka plan görevi): Çevrimdışı + sessiz olmayan üyelere
  ↓
8. HTTP yanıt: MessageResponse → gönderen
```

### Frontend Mesaj Alımı

```
WS "new_message" event gelir
  ├─ Açık konuşmadaysa:
  │   ├─ Mesajı listeye ekle
  │   ├─ Otomatik scroll (aşağıdaysa)
  │   └─ Otomatik okundu işaretle
  │
  └─ Başka konuşmadaysa:
      ├─ Bildirim sesi çal (sessiz değilse)
      └─ Sidebar badge güncelle
```

---

## 2. Push Notification (VAPID) Sistemi

### Ortam Değişkenleri

| Değişken | Açıklama |
|---|---|
| `VAPID_PRIVATE_KEY` | Push imzalama özel anahtarı |
| `VAPID_PUBLIC_KEY` | Tarayıcıya gönderilen genel anahtar |
| `VAPID_MAILTO` | Push servisi iletişim e-postası |

### API Endpoint'leri

| Endpoint | Metod | Açıklama |
|---|---|---|
| `/api/push/vapid-key` | GET | VAPID public key döner |
| `/api/push/subscribe` | POST | Push aboneliği oluştur/güncelle |
| `/api/push/unsubscribe` | DELETE | Push aboneliğini deaktif et |

### Abonelik Akışı

```
Frontend: subscribeToPush()
  1. Notification.requestPermission() → İzin iste
  2. GET /api/push/vapid-key → Public key al
  3. Service Worker kaydı kontrol et
  4. pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: ... })
  5. POST /api/push/subscribe → Abonelik bilgilerini backend'e gönder
```

### Push Gönderim Koşulları

Push bildirim **yalnızca** şu koşullar sağlandığında gönderilir:
1. Alıcı **çevrimdışı** (`manager.is_online(uid) == False`)
2. Konuşma alıcı tarafından **sessize alınmamış** (`is_muted == False`)
3. Alıcının aktif push aboneliği var

### Push Payload Formatı

```json
{
  "title": "Gönderen Adı",           // Grup ise: "Gönderen Adı (Grup Adı)"
  "body": "Mesaj içeriği...",          // İlk 100 karakter
  "url": "/dashboard/mesajlasma",
  "tag": "conv-{conversation_id}",     // Aynı konuşma bildirimleri gruplar
  "icon": "/icon-192.png",
  "badge": "/icon-192.png"
}
```

### Service Worker Davranışı

- **Push alındığında:** `showNotification()` ile tarayıcı bildirimi göster
- **Bildirime tıklandığında:** Açık pencere varsa odakla + yönlendir; yoksa yeni pencere aç
- `renotify: true` — Aynı tag ile bile her bildirim gösterilir
- `requireInteraction: false` — Bildirim otomatik kapanır

### Hata Yönetimi

- **404/410 yanıtı:** Abonelik süresi dolmuş → `is_active = false` olarak işaretle
- **Diğer hatalar:** Logla, sessizce devam et

---

## 3. Ses Bildirimi

### Dosyalar

| Dosya | Açıklama |
|---|---|
| `frontend/static/sounds/notification.wav` | Bildirim ses dosyası |
| `frontend/src/lib/stores/notification.svelte.ts` | Ses yönetimi store'u |

### Yapılandırma

- **Ses seviyesi:** 0.5 (50%)
- **Preload:** `auto`
- **Depolama:** `localStorage` anahtarı `notification_sound`
- **Varsayılan:** Açık (`true`)

### Ses Çalma Koşulları

Bildirim sesi **yalnızca** şu koşullarda çalar:
1. Mesaj **başka bir kullanıcıdan** geldi (`!isFromMe`)
2. Konuşma **sessize alınmamış** (`!convMuted`)
3. Ses ayarı **açık** (`soundEnabled === true`)
4. Mesaj **WebSocket üzerinden** alındı

### iOS/Safari Desteği

- Mobil tarayıcılar ilk kullanıcı etkileşimine kadar ses çalmayı engeller
- `unlockAudio()`: İlk dokunuşta sessiz ses çalarak kilidi açar
- Sonraki `playNotificationSound()` çağrıları normal çalışır

### Ses Açma/Kapama

```typescript
// Topbar'daki ses ikonu ile kontrol edilir
toggleSound(enabled: boolean)
  → notificationSettings.soundEnabled güncelle
  → localStorage.setItem('notification_sound', ...)
```

---

## 4. Okunmamış Sayısı ve Badge

### Hesaplama Mantığı (Backend)

```sql
-- Her konuşma için okunmamış mesaj sayısı
SELECT COUNT(m.id) FROM messages m
JOIN conversation_members cm ON cm.conversation_id = m.conversation_id
WHERE m.sender_id != current_user_id        -- Kendi mesajlarım hariç
  AND m.is_deleted = FALSE                   -- Silinmemiş mesajlar
  AND m.created_at >= cm.joined_at           -- Gruba katılmadan öncekiler hariç
  AND (cm.last_read_at IS NULL OR m.created_at > cm.last_read_at)
```

### Frontend Gösterim

- **Sidebar badge:** Tüm konuşmaların toplam okunmamış sayısı
- **Konuşma listesi:** Her konuşmanın yanında okunmamış badge
- **Güncelleme:** `new_message` event'i ile artırılır, `read_status` ile sıfırlanır

### Okundu İşaretleme

```
Kullanıcı konuşmayı açar/mesaj görür
  → PATCH /api/messages/conversations/{id}/read
  → ConversationMember.last_read_at = now()
  → WS "read_status" broadcast → diğer üyelere
```

---

## 5. Okundu Bilgisi (Tik İşaretleri)

| Gösterge | Anlamı | Koşul |
|---|---|---|
| ✓ (tek tik) | Gönderildi | `message.created_at > otherUser.last_read_at` |
| ✓✓ (çift tik) | Okundu | `message.created_at <= otherUser.last_read_at` |

- `last_read_at` değeri `ConversationMember` tablosundan gelir
- WS `read_status` event'i ile gerçek zamanlı güncellenir

---

## Test Kullanıcıları

Aşağıdaki 50 test kullanıcısı + admin ve ferit mesajlaşma testleri için kullanılır.

| # | Kullanıcı Adı | ID | Şifre | Departman |
|---|---|---|---|---|
| 1 | admin | 1 | admin123 | Yönetim |
| 2 | ferit | 2 | testuser123 | Mutfak |
| 3 | elif | 266 | testuser123 | Resepsiyon |
| 4 | deniz | 267 | testuser123 | Kat Hizmetleri |
| 5 | selim | 268 | testuser123 | Güvenlik |
| 6 | zeynep | 269 | testuser123 | Yönetim |
| 7 | emre | 270 | testuser123 | Teknik |
| 8 | selin | 271 | testuser123 | Spa |
| 9 | can | 272 | testuser123 | Yönetim |
| 10 | derya | 273 | testuser123 | Yönetim |
| 11 | oguz | 274 | testuser123 | Yönetim |
| 12 | nihan | 275 | testuser123 | Yönetim |
| 13 | ahmet | 276 | testuser123 | Resepsiyon |
| 14 | fatma | 277 | testuser123 | Resepsiyon |
| 15 | murat | 278 | testuser123 | Resepsiyon |
| 16 | seda | 279 | testuser123 | Resepsiyon |
| 17 | hakan | 280 | testuser123 | Resepsiyon |
| 18 | pinar | 281 | testuser123 | Resepsiyon |
| 19 | tolga | 282 | testuser123 | Resepsiyon |
| 20 | sevgi | 283 | testuser123 | Kat Hizmetleri |
| 21 | kadir | 284 | testuser123 | Kat Hizmetleri |
| 22 | melek | 285 | testuser123 | Kat Hizmetleri |
| 23 | cem | 286 | testuser123 | Kat Hizmetleri |
| 24 | gulsen | 287 | testuser123 | Kat Hizmetleri |
| 25 | tarik | 288 | testuser123 | Kat Hizmetleri |
| 26 | burcu | 289 | testuser123 | Kat Hizmetleri |
| 27 | ismail | 290 | testuser123 | Mutfak |
| 28 | hatice | 291 | testuser123 | Mutfak |
| 29 | volkan | 292 | testuser123 | Mutfak |
| 30 | sibel | 293 | testuser123 | Mutfak |
| 31 | kerem | 294 | testuser123 | Mutfak |
| 32 | asli | 295 | testuser123 | Mutfak |
| 33 | ufuk | 296 | testuser123 | Mutfak |
| 34 | serkan | 297 | testuser123 | Güvenlik |
| 35 | ebru | 298 | testuser123 | Güvenlik |
| 36 | yusuf | 299 | testuser123 | Güvenlik |
| 37 | dilek | 300 | testuser123 | Güvenlik |
| 38 | baris | 301 | testuser123 | Güvenlik |
| 39 | gamze | 302 | testuser123 | Güvenlik |
| 40 | erdem | 303 | testuser123 | Güvenlik |
| 41 | onur | 304 | testuser123 | Teknik |
| 42 | merve | 305 | testuser123 | Teknik |
| 43 | tugrul | 306 | testuser123 | Teknik |
| 44 | canan | 307 | testuser123 | Teknik |
| 45 | alper | 308 | testuser123 | Teknik |
| 46 | esra | 309 | testuser123 | Teknik |
| 47 | kaan | 310 | testuser123 | Teknik |
| 48 | gokhan | 311 | testuser123 | Spa |
| 49 | nilay | 312 | testuser123 | Spa |
| 50 | arda | 313 | testuser123 | Spa |
| 51 | berna | 314 | testuser123 | Spa |
| 52 | ozan | 315 | testuser123 | Spa |
| 53 | hande | 316 | testuser123 | Spa |
| 54 | taner | 317 | testuser123 | Spa |
| 55 | levent | 318 | testuser123 | Muhasebe |

---

## 6. Online/Offline Durumu

### Backend Yönetimi

```python
ConnectionManager._connections: Dict[int, List[WebSocket]]
# Çoklu sekme desteği: Her kullanıcı birden fazla WS bağlantısına sahip olabilir

Bağlantı açıldığında:
  → Kullanıcı ilk kez bağlandıysa: "user_status" {is_online: true} → partnerlere

Bağlantı kapandığında:
  → Kullanıcının hiç bağlantısı kalmadıysa: "user_status" {is_online: false} → partnerlere
```

### Frontend Gösterim

- `onlinePresence.ids`: Online kullanıcı ID'lerinin `Set`'i
- `connected` event'i ile başlangıç seti yüklenir
- `user_status` event'i ile gerçek zamanlı güncellenir
- Yeşil nokta ile görsel gösterim

---

## 7. Yazıyor Göstergesi (Typing)

### Rate Limiting

- **Frontend:** 2 saniyelik debounce (her tuş vuruşunda tekrar gönderilmez)
- **Backend:** 500ms minimum aralık (`TYPING_MIN_INTERVAL`)
- **Frontend timeout:** 3 saniye sonra otomatik temizleme

### Özel ve Grup Konuşmalarda Fark

- **Özel konuşma:** `target_user_id` ile yalnızca hedefe gönderilir
- **Grup konuşma:** Gönderen hariç tüm üyelere broadcast edilir

---

## 8. Konuşma Sessize Alma (Mute)

- `ConversationMember.is_muted` alanı ile kontrol edilir
- Sessize alınan konuşmadan:
  - **Push bildirim gönderilmez**
  - **Bildirim sesi çalmaz**
  - WS mesajları yine de alınır (mesaj listesi güncellenir)

---

## 9. İlgili Dosyalar

### Backend

| Dosya | Açıklama |
|---|---|
| `backend/app/routers/messages/msg_operations.py` | Mesaj CRUD + WS broadcast + push tetikleme |
| `backend/app/routers/messages/conversations.py` | Konuşma CRUD + okundu işaretleme |
| `backend/app/routers/messages/_helpers.py` | WS event builder, yardımcı fonksiyonlar |
| `backend/app/routers/messages/groups.py` | Grup konuşma işlemleri |
| `backend/app/routers/messages/users.py` | Mesajlaşılabilir kullanıcı listesi |
| `backend/app/routers/ws.py` | WebSocket endpoint + typing handler |
| `backend/app/routers/push.py` | Push abonelik API'leri |
| `backend/app/websocket/manager.py` | WS bağlantı yöneticisi |
| `backend/app/utils/push.py` | Push bildirim gönderim helper'ı |
| `backend/app/models/message.py` | Message modeli |
| `backend/app/models/conversation.py` | Conversation + ConversationMember modelleri |
| `backend/app/models/push_subscription.py` | PushSubscription modeli |

### Frontend

| Dosya | Açıklama |
|---|---|
| `frontend/src/routes/dashboard/mesajlasma/+page.svelte` | Mesajlaşma sayfası |
| `frontend/src/lib/stores/messaging.svelte.ts` | Mesajlaşma state yönetimi |
| `frontend/src/lib/stores/websocket.svelte.ts` | WebSocket bağlantı yönetimi |
| `frontend/src/lib/stores/notification.svelte.ts` | Bildirim sesi yönetimi |
| `frontend/src/lib/utils/messaging-ws-handlers.svelte.ts` | WS event handler'ları |
| `frontend/src/lib/utils/messaging-helpers.svelte.ts` | Typing manager, yardımcı fonksiyonlar |
| `frontend/src/lib/utils/messaging-messages.svelte.ts` | Mesaj işlemleri |
| `frontend/src/lib/utils/messaging-ui.svelte.ts` | UI yardımcı fonksiyonları |
| `frontend/src/lib/utils/push.ts` | Push abonelik yönetimi |
| `frontend/src/lib/types/messaging.ts` | TypeScript tipleri |
| `frontend/src/service-worker.ts` | Service Worker (push handler) |

---

## 10. Veritabanı Tabloları

### messages

| Alan | Tip | Açıklama |
|---|---|---|
| `id` | int (PK) | Mesaj ID |
| `conversation_id` | int (FK) | Konuşma ID |
| `sender_id` | int (FK) | Gönderen kullanıcı ID |
| `content` | text | Mesaj içeriği |
| `message_type` | str | `text`, `image`, `file`, `video`, `system` |
| `file_url` | str? | Dosya URL'si |
| `file_name` | str? | Dosya adı |
| `file_size` | int? | Dosya boyutu |
| `file_type` | str? | MIME tipi |
| `is_edited` | bool | Düzenlendi mi |
| `edited_at` | datetime? | Düzenlenme zamanı |
| `is_deleted` | bool | Soft delete flag |
| `created_at` | datetime | Oluşturma zamanı |

### conversation_members

| Alan | Tip | Açıklama |
|---|---|---|
| `conversation_id` | int (FK) | Konuşma ID |
| `user_id` | int (FK) | Üye kullanıcı ID |
| `is_admin` | bool | Grup admini mi |
| `is_muted` | bool | Sessize alındı mı |
| `last_read_at` | datetime? | Son okunma zamanı (tik hesabı) |
| `joined_at` | datetime | Gruba katılma zamanı |

### push_subscriptions

| Alan | Tip | Açıklama |
|---|---|---|
| `user_id` | int (FK) | Kullanıcı ID |
| `endpoint` | str (unique) | Tarayıcı push endpoint URL |
| `p256dh_key` | str | Şifreleme anahtarı |
| `auth_key` | str | Kimlik doğrulama anahtarı |
| `is_active` | bool | Abonelik aktif mi |
| `user_agent` | str? | Tarayıcı bilgisi |
