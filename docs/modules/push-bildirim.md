# Push Bildirim (Web Push)

## Genel Bilgi
- **Backend prefix:** `/api/push`
- **Protokol:** VAPID (Voluntary Application Server Identification) Web Push

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/push.py` |
| Model | `backend/app/models/push_subscription.py` |
| Util | `backend/app/utils/push.py` — `send_push()`, `send_push_to_user()` |
| Frontend util | `frontend/src/lib/utils/push.ts` — `subscribeToPush()`, `unsubscribeFromPush()`, `isPushSupported()` |
| Service Worker | `frontend/src/service-worker.ts` — push event handler |
| PWA Manifest | `frontend/static/manifest.json` |

## Veri Modeli
**`push_subscriptions`**:
| Kolon | Açıklama |
|---|---|
| id | PK |
| user_id | Kullanıcı FK |
| endpoint | Browser push endpoint URL (unique) |
| p256dh_key | ECDH public key |
| auth_key | Auth secret |
| user_agent | Tarayıcı bilgisi (debug) |
| created_at | Abonelik zamanı |

## API Endpoint'leri
| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/push/vapid-key` | VAPID public key (client subscribe için) |
| POST | `/api/push/subscribe` | Yeni abonelik kaydet |
| DELETE | `/api/push/unsubscribe` | Aboneliği sil (endpoint bazlı) |

## Akış
1. **Kullanıcı giriş yapar** → `auth.svelte.ts` → `subscribeToPush()` çağrılır
2. Tarayıcı `Notification.requestPermission()` → izin verirse ServiceWorkerRegistration.pushManager.subscribe
3. Frontend, subscription'ı `/api/push/subscribe`'a POST eder
4. **Bildirim gönderirken:** `send_push_to_user(user_id, title, body, url)` → `push_subscriptions` tablosundan endpoint'leri alır → `pywebpush` ile her birine gönderir
5. **Service worker** push event'ini yakalar → `self.registration.showNotification()`
6. **Kullanıcı çıkış yapar** → `unsubscribeFromPush()` → DB'den silinir

## Güvenlik & Config
- `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_MAILTO` `.env`'den okunur
- **HTTPS zorunlu** — Service Worker + Push yalnızca secure context'te çalışır
- Endpoint duplicate → upsert (UPDATE yerine aynı endpoint varsa user_id eşleşiyor)

## Geliştirme Kuralları
- **Gönderim hataları sessiz olmamalı:** `utils/push.py` her push hatası `ErrorLog` tablosuna yazılır
- **Eski endpoint'ler temizlenmeli:** 404/410 dönerse abonelik silinir (pywebpush exception handler)
- **iOS Safari:** Push desteği 16.4+ — frontend `isPushSupported()` ile kontrol eder
- **Service Worker update:** `service-worker.ts` değişirse build numarası artırılmalı, skipWaiting + clients.claim pattern'i kullanılır
