---
description: CLAUDE.md kontrol-listesiyle yeni bir modül iskeleti oluştur (backend + frontend + test + doküman)
argument-hint: "<module.code> <Görünen Ad>  (ör: finance.kasa Kasa)"
---
Yeni modül ekle: `$ARGUMENTS` (modül kodu + görünen ad). CLAUDE.md'nin yeni-modül zorunluluklarına **birebir** uy. Önce benzer mevcut bir modülü referans al (CRUD → `finans/avanslar` + `sistem/kullanicilar`; planlı gider → `create_scheduled_router`). Uydurma; kalıpları kopyala.

**Adımlar:**
1. **Model** (`backend/app/models/`): kolonlar (PK→FK→veri→zaman damgası→flag) + index'ler. Python 3.9 (`Optional[...]`; `X | None` **YASAK**).
2. **Schema** (`backend/app/schemas/`): `Create` / `Update` / `Response`.
3. **Router** (`backend/app/routers/...`): dosya-içi düzen (docstring → import sırası → sabitler → router → `_`helper → CRUD `get/post/patch/delete` → `summary`). **HER mutasyon:** `require_permission(code,"use")` + `check_approval(...)` + `log_action(...)`. Para hareketi varsa `finance_event_svc.upsert_*/invalidate`.
4. **Router'ı kaydet** (ilgili `__init__.py` / `main.py`).
5. **Onay executor handler** (`approval_executor.py`): `_handle_<modül>` ekle + `_HANDLERS`'e bağla. Model alanları **gerçek kolonlarla birebir** (yoksa onaylar 500 verir; `TestExecutorImportIntegrity` mevcut handler'ları doğrular — yeni handler'ı da test et).
6. **Migration:** `/migration "<modül> tablosu"`.
7. **RBAC modül kaydı:** `modules` tablosuna ekle (`tests/ci/02_seed.sql` + canlı DB) + izin matrisi.
8. **Frontend sayfa** (`frontend/src/routes/dashboard/...`): tasarım sistemi (`PageHeader`/`StatCard`/`Button`/`StatusBadge`/`ConfirmDialog`/`MoneyInput`/`EmptyState`/`Pagination`/Lucide; AA teal-700; mobilde `<md` kart). `lib/config/navigation.ts`'e `NavItem` ekle → sidebar + route guard otomatik gelir.
9. **Türkçe:** tüm kullanıcı metinleri doğru Türkçe karakter (ASCII-Türkçe yasak).
10. **Test** (`backend/tests/test_<modül>.py`): happy-path + RBAC 403 (`viewer_user_headers`/`no_perm_user_headers`) + onay akışı (workflow→202→onayla→uygulandı).
11. **Doküman:** `docs/modules/<modül>.md` + ana `CLAUDE.md` (endpoint + RBAC + tablo listeleri) + ilgili modül-içi `CLAUDE.md`.

**Bitince:** `modul-denetci` subagent'ıyla denetlet ve `/test` ile testleri çalıştır. Eksik adım bırakma — özellikle 5 (executor handler) ve 11 (doküman) sık unutulur.
