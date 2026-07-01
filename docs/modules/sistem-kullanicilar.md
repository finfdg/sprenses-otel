# Sistem — Kullanıcılar

## Genel Bilgi
- **Modül kodu:** `system.users`
- **Üst modül:** `system`
- **Frontend rota:** `/dashboard/sistem/kullanicilar`
- **Backend prefix:** `/api/system/users`
- **İzin kodu:** `system.users` — `can_view` / `can_use`

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/system_users.py` |
| Schema | `backend/app/schemas/user.py` |
| Model | `backend/app/models/user.py` |
| Response builder | `backend/app/utils/response_builders.py` — `build_user_responses_batch()` |
| Frontend | `frontend/src/routes/dashboard/sistem/kullanicilar/+page.svelte` |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/users/` | `system.users:view` | Paginated listesi (`items`, `total`, `page`, `page_size`, `pages`) |
| POST | `/api/system/users/` | `system.users:use` | Yeni kullanıcı (onay kontrolünden geçer) |
| PATCH | `/api/system/users/{id}` | `system.users:use` | Güncelle (onay kontrolünden geçer) |
| DELETE | `/api/system/users/{id}` | `system.users:use` | Sil (onay kontrolünden geçer) |
| POST | `/api/system/users/{id}/reset-password` | `system.users:use` | Admin şifre sıfırlar |

## Onay Akışı
Tüm POST/PATCH/DELETE endpoint'leri `check_approval(db, "system.users", entity_id, user_id, action, payload)` çağrısından geçer. Onay gerekiyorsa 202 döner.

## Performans
- **Batch response:** Liste endpoint'i `build_user_responses_batch()` kullanır — kullanıcı + rol + izin matrisi tek sorguda (N+1 yok)
- **joinedload:** `Role` ilişkisi eager load edilir (`system_users.py`)
- **Pagination:** Varsayılan `page_size=50`, max `200`

## Audit Log
| Action | Entity Type | Details |
|---|---|---|
| `create` | `user` | Email, ad, rol |
| `update` | `user` | Değişen alanlar |
| `delete` | `user` | Silinen kullanıcı ID |
| `reset_password` | `user` | Admin ID, hedef kullanıcı ID |

## Geliştirme Kuralları
- Şifre hash'i yanıtlarda asla dönülmemelidir
- Self-delete yasak (kullanıcı kendi hesabını silemez) — endpoint'te kontrol
- Email unique constraint — çakışma 409 döner
- Rol silinirken atanmış kullanıcılar varsa 400 döner (rol router'ında)
