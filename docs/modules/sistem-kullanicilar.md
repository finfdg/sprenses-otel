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
| POST | `/api/system/users/{id}/send-verification` | `system.users:use` | E-posta teyit bağlantısı gönder (onaydan muaf) |
| POST | `/api/auth/verify-email` | PUBLIC | Teyit bağlantısını doğrula (auth router; imzalı token) |

## Onay Akışı
CRUD (POST/PATCH/DELETE) endpoint'leri `check_approval(db, "system.users", entity_id, user_id, action, payload)` çağrısından geçer. Onay gerekiyorsa 202 döner. **İstisna:** `reset-password` ve `send-verification` operasyonel işlemlerdir (entity CRUD değil) → onaydan muaf, sadece audit'lenir.

## E-posta Teyidi (Doğrulama)
- **Amaç:** Kullanıcının tanımlı e-posta adresinin gerçekten kendisine ait/erişilebilir olduğunu doğrulamak.
- **Kolonlar:** `users.email_verified` (bool, default false), `users.email_verified_at` (nullable). Migration: `f2b8d1a5c9e3`.
- **Akış:** Admin **"Teyit gönder"** butonuna basar → `send-verification` imzalı token'lı (`create_email_verification_token`, JWT, 48 saat, DB'siz) bağlantı üretir → `bilgi@sprenses.com`'dan e-posta gider → kullanıcı `/eposta-teyit?token=…` bağlantısına tıklar → `POST /api/auth/verify-email` (PUBLIC) token'ı doğrular → `email_verified=True`, `email_verified_at=now`.
- **Token güvenliği:** İmza `SECRET_KEY` ile; `purpose=email_verify` kontrolü; token içindeki e-posta kullanıcının **o anki** e-postasıyla eşleşmeli (e-posta değişmişse bağlantı geçersiz). Zaten doğrulanmışsa idempotent.
- **E-posta değişince sıfırlanır:** `apply_user_update` — e-posta değiştiğinde `email_verified=False`, `email_verified_at=None` (yeni adres yeniden doğrulanmalı). Bu davranış hem router hem onay executor'da ortak servis üzerinden geçerli.
- **UI:** Kullanıcı satırında rozet — **E-posta teyitli** (yeşil) / **E-posta teyit bekliyor** (amber) / **E-posta yok** (gri). Teyitsiz + e-postalı kullanıcıda "Teyit gönder" butonu.
- **SMTP bağımlılığı:** `send-verification`, SMTP kapalıysa (`SMTP_PASSWORD` boş) 503 döner. Detay: `docs/modules/eposta-bildirim.md`.
- **Test:** `tests/test_email_verification.py` (token roundtrip/amaç, send-verification izin/404/400/503/başarı, public verify geçerli/geçersiz/e-posta-değişti/idempotent, e-posta değişince sıfırlama).

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
| `send_verification` | `user` | Admin ID, hedef kullanıcı ID |
| `verify_email` | `user` | Kullanıcı kendi e-postasını doğruladı |

## Geliştirme Kuralları
- Şifre hash'i yanıtlarda asla dönülmemelidir
- Self-delete yasak (kullanıcı kendi hesabını silemez) — endpoint'te kontrol
- Email unique constraint — çakışma 409 döner
- Rol silinirken atanmış kullanıcılar varsa 400 döner (rol router'ında)
