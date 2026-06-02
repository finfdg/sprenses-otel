# Bildirimler (Notifications)

## Genel Bilgi
- **Modül kodu:** `notifications` (menü öğesi değil — sistem servisi)
- **Backend prefix:** `/api/notifications`
- **İzin kodu:** Gerekmez — yalnızca authenticated kullanıcı kendi bildirimlerine erişir

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/notifications.py` |
| Model | `backend/app/models/notification.py` |
| Util | `backend/app/utils/notification.py` — `create_notification()`, `notify_users()` |
| Util | `backend/app/utils/push.py` — VAPID push delivery |
| Frontend | Topbar dropdown — `frontend/src/lib/components/Topbar.svelte` |

## Veri Modeli
**`notifications`**:
| Kolon | Açıklama |
|---|---|
| id | PK |
| user_id | Hedef kullanıcı |
| type | `message`, `approval_request`, `approval_decision`, `vendor_assigned`, … |
| title | Başlık |
| body | İçerik |
| url | Tıklanınca yönlendirme hedefi |
| is_read | Okundu mu |
| created_at | Zaman |

## API Endpoint'leri
| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/notifications/` | Paginated bildirim listesi |
| PATCH | `/api/notifications/{id}/read` | Okundu işaretle |
| PATCH | `/api/notifications/read-all` | Hepsini okundu işaretle |
| GET | `/api/notifications/unread-count` | Okunmamış sayısı |

## Kullanım (Backend)
```python
from app.utils.notification import create_notification

create_notification(
    db, user_id=target_user.id, type="approval_request",
    title="Onay Bekliyor", body=f"{entity_type} kaydı onayınızı bekliyor",
    url="/dashboard/finans/onay"
)
# → DB insert + WS broadcast + push delivery (varsa)
```

## Gerçek Zamanlılık
- **WS event:** `notification` → client'a anlık bildirim, bildirim sesi çalınır
- **Push:** Kullanıcı offline ise VAPID push ile tarayıcı/OS bildirimi
- **Ses:** `notification.svelte.ts` içinde Audio API ile, iOS autoplay kısıtlaması için silent fail

## Geliştirme Kuralları
- **Yeni modül eklerken** önemli olaylar (onay talebi, atama, durum değişikliği) için `create_notification()` çağrısı yapılmalı
- **Spam koruması:** Aynı tip + aynı entity için kısa sürede tekrar bildirim üretilmez (modül bazlı)
- **Silme:** Kullanıcı tek tek silebilir (ileride), otomatik silme 30 gün sonra (gelecekte)
