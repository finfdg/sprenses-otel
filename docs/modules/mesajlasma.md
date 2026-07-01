# Mesajlaşma

## Genel Bilgi
- **Modül kodu:** `messaging`
- **Üst modül:** (kök)
- **Frontend rota:** `/dashboard/mesajlasma`
- **Backend prefix:** `/api/messages`
- **İzin kodu:** `messaging` — `can_view` / `can_use`

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/messages/` (conversations.py, messages.py, users.py, read.py, _helpers.py) |
| Rol cache | `backend/app/utils/messaging_role_cache.py` — messaging erişimli rol ID'leri (5dk TTL). **Cache state utils'tedir** (router değil) ki `system_service` izin değişiminde invalidate ederken service→router import yönü oluşmasın (2026-06-27 refactor). `_helpers.py` geriye uyum için `_get_messaging_role_ids`/`_invalidate_messaging_role_cache` adlarıyla re-export eder. |
| Model | `backend/app/models/conversation.py`, `message.py`, `conversation_member.py` |
| Schema | `backend/app/schemas/message.py` |
| WebSocket | `backend/app/routers/ws.py`, `backend/app/websocket/manager.py` |
| Frontend | `frontend/src/routes/dashboard/mesajlasma/+page.svelte` |
| Store | `frontend/src/lib/stores/messaging.svelte.ts` |

## Veri Modeli
- **`conversations`**: id, type (`private` | `group`), name, created_at, updated_at
- **`conversation_members`**: conversation_id, user_id, last_read_at, is_muted, joined_at
- **`messages`**: id, conversation_id, sender_id, content, is_edited, edited_at, is_deleted, created_at

## API Endpoint'leri
| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/messages/conversations` | Kullanıcının konuşma listesi (son mesaj + unread count) |
| POST | `/api/messages/conversations` | Yeni konuşma başlat (private/group) |
| GET | `/api/messages/conversations/{id}` | Konuşma mesajları (paginated) |
| POST | `/api/messages/conversations/{id}` | Mesaj gönder |
| PATCH | `/api/messages/conversations/{id}/messages/{msg_id}` | Mesaj düzenle (sadece gönderen) |
| DELETE | `/api/messages/conversations/{id}/messages/{msg_id}` | Soft delete — `is_deleted=true` |
| PATCH | `/api/messages/conversations/{id}/read` | Okundu işaretle (last_read_at güncelle) |
| GET | `/api/messages/unread-count` | Toplam okunmamış sayısı |
| GET | `/api/messages/users` | Mesajlaşılabilir kullanıcı listesi |

## Gerçek Zamanlılık (WebSocket)
**Polling KESİNLİKLE YASAK** — tüm event'ler WS üzerinden:
| Event | Tetikleyici | Alıcı |
|---|---|---|
| `new_message` | POST message | Konuşma üyeleri |
| `message_edited` | PATCH message | Konuşma üyeleri |
| `message_deleted` | DELETE message | Konuşma üyeleri |
| `message_read` | PATCH read | Diğer üye(ler) |
| `typing` | Client typing | Diğer üye(ler) |
| `user_online` / `user_offline` | WS connect/disconnect | İlgili kullanıcılar |
| `connected` | İlk bağlantı | Başlangıç verisi (online kullanıcılar) — ek HTTP gerekmez |

## Mesaj Düzenleme & Silme Kuralları
- **Düzenleme:** Yalnızca gönderen düzenleyebilir, `is_edited=true` ve `edited_at` set edilir, UI "düzenlendi" rozeti gösterir
- **Silme:** Soft delete (`is_deleted=true`) — içerik DB'de korunur, UI'da "Bu mesaj silindi" gösterilir (audit + geri alma için)
- **Okundu bilgisi:** `ConversationMember.last_read_at` ile tek/çift tik — her üye kendi son okuma zamanını tutar

## Okunmamış Sayısı
- **Tek SQL sorgusu** ile hesaplanır: her konuşma için `messages.created_at > member.last_read_at` COUNT
- Sidebar badge'i WS `unread_updated` event'i ile canlı güncellenir

## Push Bildirim
- **VAPID destekli web push** (`backend/app/utils/push.py`, `frontend/src/lib/utils/push.ts`)
- Kullanıcı sessize aldığı konuşmalardan push almaz (`is_muted`)
- Service worker: `frontend/src/service-worker.ts` — push event → notification show

## Geliştirme Kuralları
- **Onay akışı istisnası (bilinçli):** Mesajlaşma modülünün hiçbir POST/PATCH/DELETE endpoint'i
  `check_approval`'dan geçmez ve `approval_executor.py`'de `messaging` handler'ı yoktur — mesajlaşma
  finansal/onay gerektiren bir mutasyon içermez (konuşma/mesaj/üye işlemleri). Bu, CLAUDE.md onay
  kuralının bilinçli bir muafiyetidir.
- **Polling yasak:** `setInterval` yalnızca WS keepalive için
- **structuredClone fallback:** Svelte proxy objelerinde `structuredClone` başarısız olabilir → JSON parse fallback (log düşürülür)
- **İzin:** `hasPermission('messaging', 'view')` — görme yoksa modül menüde yok
- **Grup konuşma silme:** Admin veya konuşma sahibi (ileride)
