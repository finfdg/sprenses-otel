# Sistem — Hata Logları

## Genel Bilgi
- **Modül kodu:** `system.error_logs`
- **Üst modül:** `system`
- **Frontend rota:** `/dashboard/sistem/hata-loglar`
- **Backend prefix:** `/api/system/error-logs`
- **İzin kodu:** `system.error_logs` — sadece `can_view`

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/error_logs.py` |
| Model | `backend/app/models/error_log.py` |
| Middleware | `backend/app/main.py` — global exception handler ErrorLog'a yazar |
| Frontend | `frontend/src/routes/dashboard/sistem/hata-loglar/+page.svelte` |

## Veri Modeli
**`error_logs`**:
| Kolon | Açıklama |
|---|---|
| id | PK |
| level | Seviye (ERROR, CRITICAL, WARNING) |
| source | Kaynak modül/dosya adı |
| message | Hata mesajı |
| traceback | Full traceback (NULL olabilir) |
| method | HTTP metodu (GET/POST/…) |
| path | İstek yolu |
| user_id | Etkilenen kullanıcı (NULL olabilir) |
| ip_address | Kaynak IP |
| created_at | Zaman |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/error-logs/` | `system.error_logs:view` | Paginated, `level`/`source`/`search` (mesaj) filtresi |
| DELETE | `/api/system/error-logs/{id}` | `system.error_logs:use` | Tek kayıt sil |
| DELETE | `/api/system/error-logs/` | `system.error_logs:use` | Tümünü temizle |

## Global Exception Handler
`main.py:90-125` — beklenmeyen tüm exception'lar:
1. `logger.error()` ile stdout'a yazılır
2. `ErrorLog` tablosuna kayıt eklenir (details JSON)
3. Kullanıcıya **generic** `{"detail": "Sunucu hatası oluştu"}` döner (iç bilgi sızmaz)
4. 500 status code

## Geliştirme Kuralları
- **Sensitive data asla loglanmamalı:** `password`, `token`, `secret` alanları request_body'den maskelenir
- **Retention:** Şu an sınırsız, 90 gün üstü arşivlenmeli (gelecekte)
- **HTTPException loglanmaz:** Yalnızca `Exception` (beklenmeyen) hataları — 4xx business logic hataları normal akış
- **Push bildirim:** Adminlere kritik hata push'u (gelecekte)

## Hata Düzeltmeleri

### BaseHTTPMiddleware → Saf ASGI Middleware (2026-04-22)
**Sorun:** `SecurityHeadersMiddleware` `BaseHTTPMiddleware`'den miras alıyordu. Starlette `BaseHTTPMiddleware`, istemci bağlantısını kestiğinde veya `asyncio.CancelledError` oluştuğunda TaskGroup üzerinden çalıştırdığı endpoint task'ını iptal ediyor. Bu sırada uçuşta olan DB sorguları şu hatalarla kesiliyordu:
- `sqlalchemy.exc.ResourceClosedError: This Connection is closed` (login, 38 kayıt)
- `sqlalchemy.exc.InvalidRequestError: This session is provisioning a new connection; concurrent operations are not permitted` (cash-flow, bankalar, 40+ kayıt)
- `PendingRollbackError` + `InternalError` zinciri (bankalar)

**Çözüm:** `SecurityHeadersMiddleware` saf ASGI callable'a dönüştürüldü (`app/main.py`). TaskGroup sarmalaması kaldırıldı, header'lar `send_wrapper` içinde `http.response.start` mesajına eklenir. Mevcut header (uppercase dahil) varsa üzerine yazılmaz.

### Approval Workflow Duplicate Name (2026-04-22)
**Sorun:** `create_workflow` duplicate-name kontrolü `is_active=True` filtresi kullanıyordu. Pasif workflow (örn: `SGK onayı`, `is_active=False`) ile aynı isimde yeni kayıt deneyince ön-kontrol geçiyor ama DB seviyesinde `approval_workflows_name_key` unique constraint hatası fırlatıyordu (4 kayıt).

**Çözüm:** 
1. Ön-kontrolden `is_active.is_(True)` filtresi kaldırıldı — `name` kolonu DB'de unique, tüm kayıtlar kontrol edilmeli
2. `db.commit()` `IntegrityError` için try/except ile sarıldı — yarış durumu savunması

### Bank Account Duplicate IBAN (2026-04-22)
**Sorun:** `create_account` endpoint'i sadece `db.flush()` sırasında `IntegrityError` yakalıyordu. Autoflush veya eşzamanlı istek senaryolarında hata başka noktadan sızabiliyordu → 6 IntegrityError + 5 PendingRollbackError + ilişkili session zinciri hataları.

**Çözüm:** `db.add()` öncesi `BankAccount.iban` için explicit ön-kontrol eklendi. Flush'taki IntegrityError handler geri plan savunması olarak korundu.

### Butce audit_log dict tipi
Bkz: `backend/app/routers/finance/CLAUDE.md` — 2026-04-12 düzeltmesi (tüm `log_action(details=...)` çağrıları `json.dumps(...)` kullanır).
