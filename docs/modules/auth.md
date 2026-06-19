# Kimlik Doğrulama (Authentication)

## Genel Bilgi
- **Modül kodu:** `auth`
- **Üst modül:** (sistem seviyesi, menüde yok)
- **Frontend rota:** `/` (login), `/api/auth/me` ile oturum doğrulama
- **Backend prefix:** `/api/auth`
- **İzin kodu:** Gerekmez — anonim erişim (login/register), authenticated (me/change-password/logout)

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/auth.py` |
| Middleware | `backend/app/middleware/auth.py` — `get_current_user()`, `require_permission()` |
| Middleware | `backend/app/middleware/rate_limit.py` — Login için 5/dk IP bazlı |
| Util | `backend/app/utils/security.py` — `hash_password()`, `verify_password()`, `create_access_token()` |
| Util | `backend/app/utils/audit.py` — login/logout/register loglama |
| Schema | `backend/app/schemas/auth.py` |
| Model | `backend/app/models/user.py` |
| Frontend | `frontend/src/routes/+page.svelte` — login ekranı |
| Store | `frontend/src/lib/stores/auth.svelte.ts` |

## API Endpoint'leri
| Method | Path | Rate Limit | Açıklama |
|---|---|---|---|
| POST | `/api/auth/login` | 5/dk IP | Email + şifre ile giriş — HttpOnly cookie set eder |
| POST | `/api/auth/logout` | — | Cookie temizler, push aboneliği iptal |
| GET | `/api/auth/me` | — | Mevcut kullanıcı + rol + izinler |
| POST | `/api/auth/change-password` | — | Kendi şifresini değiştir (mevcut şifre ister) |

> **Public kayıt KALDIRILDI (2026-06-19):** `POST /api/auth/register` güvenlik nedeniyle silindi. İç (B2B) panel olduğundan internete açık self-service kayıt, herkesin "Personel" rolüyle yetkisiz oturum alıp otel verisini okumasına izin veriyordu. Kullanıcı oluşturma artık yalnızca admin tarafından `POST /api/system/users/` (`system.users:use`) ile yapılır. `UserRegister` şeması da kaldırıldı.

## Güvenlik Kuralları
- **Token taşıma:** Yalnızca HttpOnly, Secure, SameSite=Lax cookie ile. `localStorage`'da token saklanması kesinlikle yasak.
- **Cookie flag'leri:** `auth.py:_set_auth_cookie()` içinde `httponly=True, secure=(not dev), samesite="lax"`
- **Şifre hash'leme:** bcrypt (`passlib`)
- **JWT algoritması:** HS256, süre `ACCESS_TOKEN_EXPIRE_MINUTES`
- **Saat dilimi:** Token `exp` claim'i `datetime.now(pytz.timezone("Europe/Istanbul"))` ile hesaplanır
- **Rate limiting:** Login endpoint'i IP bazlı 5 deneme/dakika — brute force koruması
- **Response body:** Login/register `access_token` döndürmez (cookie yeterli), sadece kullanıcı bilgisi

## WebSocket Entegrasyonu
- WebSocket upgrade request'inde cookie'den JWT okunur (`backend/app/routers/ws.py`)
- Fallback: auth mesajı ile token gönderimi destekli (geriye dönük uyumluluk)

## Audit Log
| Action | Entity Type | Ne zaman |
|---|---|---|
| `login` | `user` | Başarılı giriş |
| `login_failed` | `user` | Hatalı şifre/kullanıcı |
| `logout` | `user` | Çıkış |
| `register` | `user` | Yeni kullanıcı oluşturulduğunda |
| `change_password` | `user` | Kullanıcı kendi şifresini değiştirdi |

## Geliştirme Kuralları
- **Default credentials yasak:** `.env`'den okunmayan hiçbir default değer koda yazılmamalı (`config.py:30-34` SECRET_KEY 32 char + unsafe list kontrolü)
- **timing attack:** Şifre karşılaştırma `verify_password()` sabit zamanlı bcrypt ile, internal secret karşılaştırmaları `secrets.compare_digest()` ile
- **Password policy:** `validatePassword()` frontend'de min 6 karakter (CLAUDE.md'de güncellenmeli)
- **Logout flow:** Push aboneliğini iptal → cookie temizle → localStorage temizle (auth.svelte.ts)
