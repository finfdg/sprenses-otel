# Tam Modül Uyum Denetimi — 2026-07-01

> **Kapsam:** 45 leaf (CRUD'lu) modülün tamamı · **Yöntem:** `modul-denetci` subagent'ı (salt-okunur), `Workflow` orkestrasyonu ile paralel (`.claude/workflows/denetle-moduller.js`).  
> **Koşu:** 46 ajan (45 denetim + 1 sentez) · ~4.7M token · ~60 dk.  
> **Nitelik:** Bulgular öneri/işaret niteliğindedir — kod DEĞİŞTİRİLMEDİ. Bazılarında nüans vardır (ör. `finance.onay` onay modülünün kendisidir; `butce/bulk` "toplu işlem" istisnası kapsamında sayılabilir). **Uygulamadan önce her bulgu doğrulanmalıdır.**

## Önem Özeti

| Kritik | Yüksek | Orta | Düşük | Toplam |
|---|---|---|---|---|
| 5 | 18 | 49 | 84 | 156 |

## Modül Bazlı Kırılım

| Modül | 🔴 K | 🟠 Y | 🟡 O | ⚪ D | Toplam |
|---|---|---|---|---|---|
| finance.butce | 2 | 1 | 3 | 2 | 8 |
| quality.forms | 1 | 2 | 3 | 0 | 6 |
| finance.krediler | 1 | 2 | 1 | 3 | 7 |
| finance.onay | 1 | 1 | 1 | 2 | 5 |
| system.error_logs | 0 | 2 | 2 | 2 | 6 |
| system.users | 0 | 2 | 2 | 2 | 6 |
| sales.hotel_reservation (Otel Rezervasyon) | 0 | 2 | 0 | 4 | 6 |
| finance.checks | 0 | 1 | 3 | 3 | 7 |
| finance.banks | 0 | 1 | 2 | 3 | 6 |
| finance.cariler | 0 | 1 | 2 | 3 | 6 |
| system.server (Sunucu İzleme) | 0 | 1 | 1 | 3 | 5 |
| system.approval | 0 | 1 | 1 | 2 | 4 |
| yonetim.panel | 0 | 1 | 1 | 0 | 2 |
| quality.templates | 0 | 0 | 2 | 4 | 6 |
| messaging (Mesajlaşma) | 0 | 0 | 2 | 3 | 5 |
| accounting.dividend | 0 | 0 | 2 | 2 | 4 |
| hr.sgk | 0 | 0 | 2 | 1 | 3 |
| hr.withholding | 0 | 0 | 2 | 1 | 3 |
| system.roles | 0 | 0 | 2 | 1 | 3 |
| accounting.recurring | 0 | 0 | 2 | 0 | 2 |
| accounting.rent_expense | 0 | 0 | 1 | 3 | 4 |
| finance.avanslar | 0 | 0 | 1 | 3 | 4 |
| system.audit_logs | 0 | 0 | 1 | 3 | 4 |
| system.modules | 0 | 0 | 1 | 3 | 4 |
| accounting.rent_income | 0 | 0 | 1 | 2 | 3 |
| accounting.taxes | 0 | 0 | 1 | 2 | 3 |
| dashboard (Panel) | 0 | 0 | 1 | 2 | 3 |
| hr.salary | 0 | 0 | 1 | 2 | 3 |
| stok.urunler | 0 | 0 | 1 | 2 | 3 |
| finance.sales_invoices | 0 | 0 | 1 | 1 | 2 |
| sales.flight (Uçak Rezervasyon) | 0 | 0 | 1 | 1 | 2 |
| stok.depolar | 0 | 0 | 1 | 1 | 2 |
| stok.hareketler | 0 | 0 | 1 | 1 | 2 |
| finance.doviz | 0 | 0 | 0 | 3 | 3 |
| hr.shift_schedule | 0 | 0 | 0 | 2 | 2 |
| hr.shifts | 0 | 0 | 0 | 2 | 2 |
| stok.maliyet | 0 | 0 | 0 | 2 | 2 |
| system.backup | 0 | 0 | 0 | 2 | 2 |
| accounting.fis_icmali | 0 | 0 | 0 | 1 | 1 |
| accounting.mizan | 0 | 0 | 0 | 1 | 1 |
| finance.cash_flow | 0 | 0 | 0 | 1 | 1 |
| hr.attendance | 0 | 0 | 0 | 1 | 1 |
| sales.room_types | 0 | 0 | 0 | 1 | 1 |
| system.docs | 0 | 0 | 0 | 1 | 1 |
| sales.daily_reservations (Günlük Hareketler) | 0 | 0 | 0 | 0 | 0 |

## Kesişen Temalar

Tekrarlayan desenler (tek tek düzeltmek yerine sınıf olarak ele alınmalı):

1. **Eksik `check_approval` (onay akışı)** — birden çok modülde POST/PATCH/DELETE onay kontrolünden geçmiyor (finance.butce/bulk, finance.onay, quality.forms fill-submit-review-reopen, finance.cariler ödeme-talimatları, system.error_logs silme, system.users reset_password). En yüksek öncelikli uyum boşluğu.
2. **RBAC 403 testi yok** — çoğu test dosyası yalnız admin `auth_headers` kullanıyor; `viewer_user_headers`/`no_perm_user_headers` ile 'view var, use yok → 403' yolu doğrulanmıyor. En yaygın tek desen (CLAUDE.md madde 11).
3. **Doküman/kod sapması** — docs/modules ve api-haritası birçok modülde bayat: hayalet kolonlar/durumlar/endpoint'ler (finance.banks, finance.checks `cashed`/`returned`, finance.krediler, quality.forms, system.error_logs).
4. **Eksik WS broadcast** — finance.krediler temel CRUD ve sales.room_types mutasyonları `broadcast_*` çağırmıyor → açık sekmeler gerçek zamanlı güncellenmiyor.
5. **Executor handler ↔ router davranış sapması** — finance.krediler `action` payload'ı okunmuyor; quality.forms executor'ında `update` dalı yok. AST testleri bu sınıfı yakalamıyor.

## Sentez (Otomatik Birleştirme)

<details><summary>Sentez ajanının birleşik anlatısı (aç/kapat)</summary>

Now I'll produce the consolidated report as my final response. Let me count the severities per module first for the summary table, then write everything.

Based on my analysis of the findings (filtering out the placeholder "test" entries for finance.cash_flow, hr.attendance, sales.room_types, and the empty sales.daily_reservations), here is the consolidated report:

# Modül Denetim Raporu — Birleştirilmiş Bulgular

Bu rapor, çok sayıda modül denetiminin bulgularını tek bir belgede toplar. Kritik ve Yüksek bulgular tek tek listelenmiştir. Orta ve Düşük bulgular kesişen temalara göre gruplanmıştır. Sonda modül-bazlı önem kırılımı tablosu yer alır.

> Not: `finance.cash_flow`, `hr.attendance`, `sales.room_types` girdilerindeki yer-tutucu ("test") bulgular ve boş `sales.daily_reservations` girdisi rapora dahil edilmemiştir.

---

## 1. Kritik Bulgular

Tümü onay akışı entegrasyonundaki (`check_approval` / executor handler) sapmalardır — modülün gerçek yazma yolunun onay motorunu tamamen atladığı veya onayın sessizce yanlış uygulandığı durumlar.

### K1 — `finance.butce`: Ana yazma yolu (`/bulk`) onay akışını tamamen atlıyor
- **Dosya:** `backend/app/routers/finance/butce.py:288-344` (`bulk_upsert_budgets`)
- **Sorun:** `POST /finance/butce/bulk` hiç `check_approval()` çağırmıyor; ayrıca `budget_service.upsert_budget`'i bypass edip router içinde elle `Budget()` insert/update yapıyor. `POST /` (tekil upsert) onaylı iken `/bulk` atlıyor → aynı iş için iki farklı davranış (executor create/update mantığıyla drift riski).
- **Düzeltme:** `/bulk`'a `check_approval()` ekle veya `budget_service.upsert_budget` üzerinden geçir; toplu-işlem istisnası uygulanacaksa gerekçesini kodda ve `docs/modules/butce.md`'de belgele.

### K2 — `finance.butce`: Frontend her hücreyi `/bulk` ile kaydediyor → onay fiilen etkisiz
- **Dosya:** `frontend/src/routes/dashboard/finans/butce/+page.svelte:202-220` (`saveBudgetCell`)
- **Sorun:** Her hücre değişikliği (800ms debounce) `POST /finance/butce/bulk` çağırır; onaylı tekil endpoint (`POST /finance/butce/`) frontend'den hiç çağrılmaz. Bir onay iş akışı tanımlansa bile günlük bütçe girişleri onaya hiç girmez.
- **Düzeltme:** K1 ile birlikte ele alınmalı — `/bulk` onaya sokulunca veya frontend tekil upsert'e yönlendirilince kapanır.

### K3 — `finance.krediler`: Kredi kapatma/yeniden-açma onayı sessizce yanlış uygulanıyor
- **Dosya:** `backend/app/routers/finance/krediler/products.py:417-422` (`close`), `482-487` (`reopen`) ↔ `backend/app/utils/approval_executor.py:286-318` (`_handle_finance_krediler`)
- **Sorun:** `close/reopen` endpoint'leri `{'action':'close'|'reopen', ...}` payload'ı ile `check_approval` çağırır ama handler `action` alanını hiç okumaz; genel `update` dalında `apply_product_update` payload'daki her key için `setattr(product, key, value)` (hasattr kontrolü yok) yapar. Sonuç: `product.action` sahte attribute olarak yutulur, `product.status` asla `closed` olmaz, ödenmemiş taksitlerin `finance_events` invalidate/upsert çağrıları çalışmaz → onaylı kredi kapatma DB'de sessizce uygulanmaz.
- **Düzeltme:** Handler'a `action` ayrımı ekle (close/reopen için credit_service'deki gerçek kapatma/açma fonksiyonunu çağır); close/reopen için uçtan-uca onay regresyon testi ekle.

### K4 — `finance.onay`: 4 mutasyon endpoint'inin hiçbiri `check_approval` çağırmıyor
- **Dosya:** `backend/app/routers/finance/onay.py:87-386` (`assign_department:87`, `approve_transaction:228`, `reject_transaction:302`, `remove_assignment:353`)
- **Sorun:** Dört mutasyon endpoint'i de sistem-seviyesi onay kontrolünden geçmiyor. Modülün kendisi bir departman-onay iş akışı olduğundan kavramsal çakışma olabilir ("onayı onaylatmak") ama bu istisna ne CLAUDE.md'de ne `docs/modules/onay.md`'de gerekçelendirilmiş. AST testi bu "hiç çağırmayan modül" durumunu yakalamaz.
- **Düzeltme:** İstisna bilinçliyse gerekçesini `docs/modules/onay.md` + router docstring'ine yaz; değilse `check_approval` entegre et.

### K5 — `quality.forms`: İş akışı durum geçişleri (fill/submit/review/reopen) onay akışı dışında
- **Dosya:** `backend/app/routers/quality/forms/fill_submit.py:52-116` (fill), `122-208` (submit), `214-272` (review), `278-328` (reopen)
- **Sorun:** Dört PATCH/POST endpoint'i de `form.status`, değerler, `review_comment`, `reviewed_by` mutasyonu yapıyor ama `check_approval()` yok; yalnız `create`/`delete` onaydan geçiyor. Bu geçişler dosya-yükleme/toplu-işlem/eşleştirme istisnalarına girmez.
- **Düzeltme:** Bu endpoint'lere `check_approval(...'update'...)` ekle ve executor'a `update` dalı ekle (bkz. Y-quality.forms handler bulgusu).

---

## 2. Yüksek Bulgular

### Y1 — `finance.banks` (dokümantasyon): `bankalar.md` gerçek şemayla uyuşmuyor
- **Dosya:** `docs/modules/bankalar.md:40-63, 96-97`
- **Sorun:** Dokümante edilen `name`/`balance` kolonları `bank_account.py`'de yok (gerçek: `bank_name`, `branch_name`, `account_no`, `iban`, ...); `bank_transactions` için `transaction_date`/`tag_category_id` yanlış (gerçek: `date`/`category_id`).
- **Düzeltme:** Dokümanı gerçek model kolonlarıyla senkronla.

### Y2 — `finance.butce` (test): RBAC ve `/bulk` onay-regresyon testi yok
- **Dosya:** `backend/tests/test_budget.py:1-205`
- **Sorun:** Tüm testler admin (`auth_headers`) ile; `viewer_user_headers`/`no_perm_user_headers` ile 403 yolu hiç test edilmiyor. `/bulk` için onay-akışı regresyon testi yok.
- **Düzeltme:** view-only/no-perm 403 testleri + `/bulk` davranışı için test ekle.

### Y3 — `finance.cariler` (onay): Ödeme Talimatı 6 mutasyon endpoint'inde `check_approval` yok
- **Dosya:** `backend/app/routers/finance/payment_instructions.py:158-386` (create/update/delete list, add/update/delete item)
- **Sorun:** Normal CRUD oldukları halde onay kontrolü yok; istisna kategorilerine girmiyor, gerekçe de belgelenmemiş. Banka portalına yüklenen gerçek para hareketleri üretir (YKB Excel export).
- **Düzeltme:** `check_approval()` ekle veya açık gerekçeyi docstring + `docs/modules/cariler.md`'ye yaz.

### Y4 — `finance.checks` (dokümantasyon): `cekler.md` hayalet durum değerleri içeriyor
- **Dosya:** `docs/modules/cekler.md:54,85,121,188,231-238`
- **Sorun:** Doküman `pending/cashed/returned/cancelled` durumlarını anlatıyor; gerçek kod yalnız `pending/paid/cancelled` tanır (`check.py:75`, `checks.py:262` pattern, `check_import.py`). `cashed`/`returned` kodda hiç yok.
- **Düzeltme:** Durum değerlerini ve geçiş akışını gerçek koda göre düzelt.

### Y5 — `finance.krediler` (WS): Temel CRUD endpoint'leri `broadcast_finance_update` çağırmıyor
- **Dosya:** `backend/app/routers/finance/krediler/products.py:252-388` (create/update/delete), `payments.py:24-158` (add/update/delete payment)
- **Sorun:** Yalnız `close_product` (458) ve `reopen_product` (523) broadcast yapıyor; temel CRUD hiç broadcast tetiklemiyor, `BackgroundTasks` bile almıyor. Diğer kullanıcıların açık krediler/nakit-akım sayfası canlı güncellenmez.
- **Düzeltme:** Tüm CRUD endpoint'lerine `BackgroundTasks` + `broadcast_finance_update(..., BroadcastModule.CREDITS, ...)` ekle.

### Y6 — `finance.krediler` (dokümantasyon): `krediler.md` ciddi ölçüde bayat
- **Dosya:** `docs/modules/krediler.md:26,28-30,44-72`
- **Sorun:** (1) `credit_payment.py` ayrı dosya sanılıyor (gerçekte `credit_product.py` içinde); (2) tablo şemaları yanlış (`principal`/`is_active` yok; gerçek: `total_amount`/`remaining_amount`/`status`/... ; payment'ta `due_date`/`is_paid`/`paid_date`/`match_number`); (3) `_regenerate_bch/kmh` D1-2 (2026-06-22) ile `credit_service.py`'ye taşındı, doküman yansıtmıyor; (4) `credit_service.py` + `_handle_finance_krediler` hiç anılmıyor.
- **Düzeltme:** Dokümanı D1-2 mimarisi + gerçek şema ile senkronla.

### Y7 — `finance.onay` (test): Happy-path + gerçek RBAC + onay yetkisi testi yok
- **Dosya:** `backend/tests/test_onay.py:1-98`
- **Sorun:** Yalnız 404/401 senaryoları var. Gerçek atama/onaylama/reddetme (Budget.actual_amount güncellemesi dahil), departman-müdürü-olmayan kullanıcının 403 alması, viewer/no-perm 403 testleri yok — salt-yüzeysel test.
- **Düzeltme:** Happy-path CRUD + departman yetki 403 + RBAC 403 testleri ekle.

### Y8 — `quality.forms` (onay executor): `_handle_quality_forms`'ta `update` dalı yok
- **Dosya:** `backend/app/utils/approval_executor.py:477-492`
- **Sorun:** Handler yalnız `create`/`delete` işliyor. K5 çözülüp fill/submit/review/reopen'a `action='update'` eklendiğinde payload sessizce kaybolacak/hata verecek.
- **Düzeltme:** Handler'a `update` dalı ekle (K5 ile birlikte).

### Y9 — `quality.forms` (dokümantasyon): `api-haritasi.md` kalite bölümü kodla uyuşmuyor
- **Dosya:** `docs/api-haritasi.md:247-251`
- **Sorun:** (a) hayalet `PATCH /api/quality/forms/{id}` (gerçek: `PATCH .../fill`, ve `POST` değil `PATCH`); (b) `GET /forms/{id}`, `DELETE /forms/{id}`, `POST /forms/{id}/reopen`, `GET /forms/{id}/pdf` dokümante edilmemiş.
- **Düzeltme:** Kalite endpoint listesini gerçek koda göre düzelt/tamamla.

### Y10 — `sales.hotel_reservation`: `reservation_service.py`'de import edilmemiş `HTTPException` (NameError)
- **Dosya:** `backend/app/services/reservation_service.py:160`
- **Sorun:** `run_reservation_import` DB hatasında `raise HTTPException(...)` çağırıyor ama `HTTPException` import edilmemiş → gerçek DB hatasında `NameError: name 'HTTPException' is not defined`. Ayrıca `services/` katmanı HTTP'siz olmalı (CLAUDE.md kural).
- **Düzeltme:** Servis katmanında HTTP'ye çevirme yapma — domain hatası fırlat, router'da HTTP'ye çevir (import de eklenmeli veya kaldırılmalı).

### Y11 — `sales.hotel_reservation` (test): RBAC 403 kapsamı yok
- **Dosya:** `backend/tests/test_reservations.py` (örn. 217-225)
- **Sorun:** Yalnız `test_unauthorized_blocked` (401) var; `viewer_user_headers`/`no_perm_user_headers` hiç kullanılmamış → view-izinli-ama-use-izinsiz kullanıcının POST/DELETE/bulk-delete'e 403 alması test edilmemiş. Kardeş dosya `test_reservation_sedna.py:44-45` doğru desene sahip.
- **Düzeltme:** view-only/no-perm 403 testleri ekle.

### Y12 — `system.approval` (izin): Mutasyon endpoint'leri `use` yerine `view` ile korunuyor
- **Dosya:** `backend/app/routers/approval/requests.py:492-498` (cancel), `546-552` (resubmit), `584-590` (trigger)
- **Sorun:** POST mutasyonları `require_permission("system.approval","view")` ile korunuyor (approve/reject/return doğru şekilde `use` istiyor). view-only kullanıcı talep iptal/resubmit yapabilir; `/trigger` çağırıp sahte onay talebi tetikleyebilir.
- **Düzeltme:** cancel/resubmit/trigger'ı `use` iznine çek.

### Y13 — `system.error_logs` (dokümantasyon): `hata-loglari.md` kod ile uyumsuz
- **Dosya:** `docs/modules/hata-loglari.md:6,19-32`
- **Sorun:** Rota `/dashboard/sistem/hata-loglari` yazıyor ama gerçek `.../hata-loglar` (`navigation.ts:156`). "Veri Modeli" hayalet kolonlar listeliyor (`status_code`, `error_type`, `error_message`, `stack_trace`, `request_body`); gerçek: `level`, `source`, `message`, `traceback`, `method`, `path`, `user_id`, `ip_address`.
- **Düzeltme:** Rota + kolon listesini gerçek modelle senkronla.

### Y14 — `system.error_logs` (onay): DELETE endpoint'lerinde `check_approval` yok
- **Dosya:** `backend/app/routers/error_logs.py:78-107` (`delete_error_log`, `clear_error_logs`)
- **Sorun:** Tekli ve toplu silme onay kontrolünden geçmiyor; istisna listesi bu durumu net kapsamıyor, gerekçe de belgelenmemiş. Executor'da handler da yok (AST testi bunu yakalamaz).
- **Düzeltme:** `check_approval` ekle veya modül dokümanı/CLAUDE.md'de açık istisna gerekçesi yaz.

### Y15 — `system.server` (test): RBAC 403 yolu hiç test edilmiyor
- **Dosya:** `backend/tests/test_system_server.py:1-270`
- **Sorun:** Tüm testler admin ile; `viewer_user_headers`/`no_perm_user_headers` hiç kullanılmamış → view-only kullanıcının restart denemesinin, izinsiz kullanıcının GET denemesinin 403 aldığı test edilmiyor.
- **Düzeltme:** view-only ve no-perm 403 testleri ekle.

### Y16 — `system.users` (onay): `reset_password` onay akışının tamamen dışında
- **Dosya:** `backend/app/routers/system_users.py:178-203`
- **Sorun:** POST `reset_password` şifre hash'ini değiştiriyor + `active_session_id=None` yapıyor ama `check_approval()` yok (yalnız `log_action`). `_handle_system_users` (executor:227-243) yalnız create/update/delete işliyor, reset-password dalı yok. Bilinçli istisna belgelenmemiş.
- **Düzeltme:** `check_approval` ekle + executor'a reset-password dalı, veya gerekçeyi `docs/modules/sistem-kullanicilar.md`'de belgele.

### Y17 — `system.users` (test): Modül-bazlı uçtan-uca onay regresyon testi yetersiz
- **Dosya:** `backend/tests/test_approval_system.py:718-743`
- **Sorun:** `test_user_create_password_redacted_e2e` yalnız 202 + payload redaction'ı doğruluyor; `approve()` hiç çağrılmıyor → onaylanınca kullanıcının gerçekten oluşturulduğu/güncellendiği/silindiği doğrulanmıyor. AST testleri payload-key uyuşmazlığını/yan-etki eksikliğini yakalamaz.
- **Düzeltme:** system.users için gerçek onayla→uygula regresyon testi ekle.

### Y18 — `yonetim.panel`: GM paneli cache'inde invalidation yok → bayat veri
- **Dosya:** `backend/app/routers/yonetim.py:33-48` (`_cache` global dict + `_cached()`)
- **Sorun:** 60 sn TTL'li process-içi cache, `sales_invoice_service`'in aksine hiçbir invalidation hook'una sahip değil. Kanıt: `test_yonetim_panel.py::TestDashboard::test_dashboard_shape` + `test_cost_control.py::test_yonetim_dashboard` art arda → ikincisi `assert 0 == 100.0` ile fail (cache kirliliği). Prod'da: Sedna/finans mutasyonu sonrası panel 60 sn'ye kadar bayat veri gösterir.
- **Düzeltme:** `mizan.py`/`sales_invoice_service.py` desenindeki gibi `_invalidate_yonetim_cache()` ekle ve senkron/mutasyon noktalarından (veya test conftest autouse fixture'dan) çağır.

---

## 3. Orta ve Düşük Bulgular — Tematik Gruplar

Bulgular kesişen temalara göre gruplanmıştır; her temada temsili `dosya:satır` örnekleri verilmiştir.

### T1 — Eksik RBAC 403 testi (view vs use ayrımı) — *en yaygın tema*
Testler yalnız admin (`auth_headers`) + kimliksiz (401) senaryolarını kapsıyor; `viewer_user_headers`/`no_perm_user_headers` ile "view-izinli ama use-izinsiz kullanıcı POST/PATCH/DELETE'te 403 alır" davranışı doğrulanmıyor. Router koruması genelde doğru, eksik olan davranışsal testtir.
- `backend/tests/test_scheduled_base.py:707-725` (8 scheduled modülün tamamı: taxes/recurring/rent_income/rent_expense/dividend/salary/withholding/sgk)
- `backend/tests/test_finance.py:176-260` (banks CRUD/upload)
- `backend/tests/test_checks.py` (checks ana CRUD; yalnız Sedna import test edilmiş)
- `backend/tests/test_sales_invoices.py:36-37` (3 GET endpoint'i)
- `backend/tests/test_advances.py`, `test_system_users.py`, `test_system_roles.py`, `test_system_modules.py`, `test_error_logs.py`, `test_ws_push_audit.py` (audit-logs), `test_stock.py:123-125` (urunler/hareketler/depolar)

### T2 — Doküman/kod sapması (hayalet endpoint, kolon, parametre, dosya haritası)
Modül dokümanları veya API haritası koddan sapmış: hayalet endpoint/kolon/parametre veya güncellenmemiş dosya haritaları.
- `docs/modules/bankalar.md:97` — hayalet `DELETE /banks/accounts/{id}/statements/{stmt_id}` (router'da yok)
- `docs/modules/butce.md:85-86` — `invoices` tablosu referansı (gerçek: `vendor_transactions.budget_category_id`)
- `docs/modules/cariler.md:22` — `cariler.py` tek dosya sanılıyor (gerçekte paket); `vendor_bank_account`/`payment_instruction`/`vendor_service` haritada yok
- `docs/modules/cekler.md:16-30,74-87` — `check_import.py`/`check_service.py` + banka-tahmini/anomali/süpürme mekanizmaları anılmamış; `GET /checks/number-anomalies` eksik
- `docs/modules/satis-faturalari.md:57` — `/advances` alan adları yanlış (`total_collected`/`net_advance` → gerçek `received`/`remaining`)
- `docs/modules/audit-log.md:34` — hayalet `start_date`/`end_date` parametreleri (kodda yok)
- `docs/modules/sistem-moduller.md:26` — "Paginated" yanlış (endpoint düz `List` döner)
- `docs/modules/sistem-kullanicilar.md:34` — pagination `page_size=20/max=100` yanlış (gerçek: 50/200)
- `docs/modules/sistem-roller.md:48` — hayalet "Admin rolü korumalı" kuralı (kodda `role.name=="Admin"` kontrolü yok)
- `docs/modules/otel-rezervasyon.md:194` — emoji ikon referansı (kod Lucide kullanıyor)
- `docs/modules/mesajlasma.md:11-37` + `docs/api-haritasi.md:24-33` — `groups.py`/`msg_operations.py` dokümante değil; birçok endpoint listede yok
- `docs/api-haritasi.md:360-372` — `GET /product-purchases/{id}` + `/pdf` merkezi katalogda eksik (kodda var)

### T3 — Merkezi sabitler: WS event tipi literal string
`onWsEvent('finance_updated'/'connected'/...)` gibi çağrılarda `WS_EVENT.*` sabiti kullanılmıyor. `WsEventType` union typo'yu derleme zamanı yakaladığından risk düşük; proje-geneli stil sapması (ortak `ScheduledModule.svelte` + ~18 sayfada; yalnız devam-takip/vardiya-cizelgesi sabit kullanıyor).
- `frontend/src/lib/components/ScheduledModule.svelte:531` (8 scheduled modülü etkiler)
- `frontend/src/routes/dashboard/+layout.svelte:50,58,63,76,83` (connected/permission_changed/...)
- `frontend/src/routes/dashboard/finans/{krediler:782,onay:156}/+page.svelte`

### T4 — Merkezi sabitler: `source_type` literal string / etiket haritası tekrarı
`SourceType.*` sabiti yerine literal string, veya kaynak→etiket haritasının çift tanımı.
- `backend/app/routers/finance/cariler/uploads.py:101,370,441,463` — literal `"vendor_payment"` (`SourceType.VENDOR_PAYMENT` var)
- `backend/app/routers/finance/check_import.py:363` — literal `"check"` (aynı dosya 190'da `SourceType.CHECK`)
- `backend/app/utils/entry_generator.py:21-30` ↔ `finance_event_service.py:292-301` — `source_type → Türkçe etiket` haritası iki dosyada birebir tekrar

### T5 — UI: Inline spinner (Skeleton/Button-loading yerine elle `animate-spin`)
CLAUDE.md veri-yüklemede `TableSkeleton`/`FormSkeleton`, buton-içi beklemede `Button loading` ister.
- `muhasebe/mizan/+page.svelte:280` (defter modal); `finans/bankalar/+page.svelte:510-516` (upload overlay); `finans/doviz/+page.svelte:252,341` (ilk yükleme + grafik); `lib/components/ScheduledModule.svelte:1070` (onay-detay modal)

### T6 — UI: Kanonik bileşen yerine elle yazım (StatCard/Button/MoneyInput/EmptyState/ConfirmDialog/Pagination)
Paylaşılan bileşen atlanıp elle uygulanmış.
- **StatCard:** `finans/butce/+page.svelte:403-469` (özel tıklanabilir kartlar); `stok/depolar/+page.svelte` (hiç StatCard yok)
- **Button (elle bg-teal):** `lib/components/quality/TemplateBuilder.svelte:134-141` (ve 164-354 birçok ham buton)
- **MoneyInput:** `finans/butce/+page.svelte:619-627` (grid'de ham `<Input type="text">` + `parseFloat`)
- **EmptyState:** `.../otel-rezervasyon/UploadsHistoryModal.svelte:32` (düz metin)
- **ConfirmDialog:** `sistem/hata-loglar/+page.svelte:234-242` (elle Modal+Button); `finans/cariler/+page.svelte:1354,1519` (`removeDeptAssignment` onaysız)
- **Pagination:** `lib/components/ScheduledModule.svelte:317` (sabit `page_size=200`); `finans/cekler/+page.svelte:178` (`page_size=500`, truncation uyarısı yok)

### T7 — UI: AA kontrast (teal-600, gray-400) ve ikon standardı
teal dolu zemin 700 olmalı, en açık gövde metni gray-500; ikonlar Lucide olmalı.
- **teal-600:** `finans/doviz/+page.svelte:252,341` (spinner metni)
- **gray-400:** `finans/krediler/+page.svelte:842,862,868,874,1578`; `stok/urunler/+page.svelte:84,105` (stok=0, ~2.54:1); `sistem/yedekleme/+page.svelte:188,200`
- **Checkbox `text-teal-600`:** `stok/urunler/+page.svelte:56` (kanonik: `accent-teal-700`)
- **Emoji/Unicode ikon:** `lib/components/messaging/MessageInput.svelte:206` (😊); `lib/components/quality/TemplateBuilder.svelte:153-386` (▲▼✕ — Lucide değil)
- **Kırmızı chip AA:** `ik/vardiya-cizelgesi/+page.svelte:282` (`bg-red-600`)

### T8 — Onay akışı: Gerekçesiz muafiyet (eşleştirme/manuel/toplu endpoint'ler)
`check_approval` bilinçli atlanmış olabilir ama gerekçe kodda/dokümanda yok; kimi kritik değil ama gri alan.
- `finance/advances.py:221-262` (`match_advance` — durum→received, gerekçe yok)
- `finance/cariler/matching.py:90-283` (match/unmatch/devir — 4 endpoint, gerekçe docstring'de yok)
- `finance/banks.py:351-419` (`create_manual_transaction` — manuel para hareketi, ana istisna listesine oturmuyor)
- `finance/krediler/payments.py:24-31` (`add_payments` — toplu taksit, gerçek para hareketi)
- `quality/templates.py:466-495` (`delete_template_logo` — düz state mutasyonu, ayrı gerekçe yok)
- `sales/flights.py:53-56` (`POST /search` — salt-okunur proxy, gerekçe yazılmamış)
- `messages/*` (tüm CRUD — makul istisna ama `docs/modules/mesajlasma.md`'de belgelenmemiş)
- `approval/workflows.py` + `requests.py` (onay motorunun kendisi — makul ama `onay-akisi.md`'de gerekçe yok)

### T9 — Modül-bazlı uçtan-uca onay regresyon testi eksik
Paylaşılan handler'lar (özellikle `_handle_scheduled`) yalnız tek modülle (`hr.salary`) test edilmiş; AST testi yalnız handler varlığını doğrular.
- `backend/tests/test_approval_system.py:766` — 8 scheduled modülden yalnız salary test edilmiş (taxes/recurring/rent_income/rent_expense/dividend/withholding/sgk için yok); `recurring`'in `vendor_id`→`sync_recurring_from_vendors` yan etkisi ayrıca doğrulanmıyor
- `quality.forms` için regresyon testi yok (`quality.templates`'te var)

### T10 — Onay payload tip coerce (JSON serileşme → tarih string)
Onay payload'ı `json.dumps(default=str)` ile serileşince tarihler string olur; tüketici `date.fromisoformat` ile coerce etmezse SQLAlchemy Date kolonuna string atanır.
- `backend/app/services/scheduled_service.py:60-81` (`apply_entry_update` — genel `setattr` döngüsü coerce etmiyor); `approval_executor.py:151-164` (entry dalı); tetikleyici: `approval_check.py:111`. `hr.withholding` entry-update onaya girerse `entry_date`/`paid_date` etkilenir (test edilmemiş); `credit_service._coerce_date` deseninin karşılığı yok
- `approval_executor.py:179-195` — fallback `ScheduledDefinition(...)` `billing_offset_months` set etmiyor (router set ediyor)

### T11 — Eksik audit log (mutasyonda `log_action` yok)
- `messages/conversations.py:448-459` (`toggle_mute` — diğer mutasyonlar loglanıyor)
- `error_logs.py:78-107` (tekli + toplu silme — geri alınamaz "Tümünü Temizle" iz bırakmıyor)

### T12 — Hata yönetimi: sessiz/eksik catch (console.error/showToast eksik)
- `yonetim/+page.svelte:36-37` — `.catch(() => ({}))` / `.catch(() => [])` (banka bakiyesi/kredi taksiti sessizce yutuluyor)
- `finans/krediler/+page.svelte:318-320,359-361,370-373` — yalnız `console.error`, `showToast` yok
- `ik/vardiyalar/+page.svelte:51-60` — `load()` catch'i yalnız `console.error`
- `approval/requests.py:68-69` — `except Exception: pass` (kardeş `approval_check.py:39-40` `logger.debug(exc_info=True)` kullanıyor)

### T13 — Eksik / dağınık modül dokümantasyonu (`docs/modules/*.md` yok)
- `dashboard` (Panel) — `docs/modules/panel.md` yok, CLAUDE.md tablosunda satır yok
- `quality.forms`/`quality.templates` — `docs/modules/kalite.md` yok (yalnız router-içi CLAUDE.md var)
- `system.server` — `docs/modules/sunucu.md` yok; ana CLAUDE.md dosya haritası (`231-232`) `system_server.py`/`system_backup.py`/`system_docs.py` içermiyor; modül-içi CLAUDE.md de yok

### T14 — Kod temizliği / stil (ölü import, kod tekrarı, docstring, frontend/backend tutarsızlığı)
- `finance/advances.py:4` — kullanılmayan `import re`
- `finance/onay.py:256-277` — `budget_service.upsert_budget` mantığının router'da elle tekrarı
- `system_modules.py:1`, `models/module.py:1`, `schemas/module.py:1` — modül docstring'i eksik
- `validation.ts:10-15` (min 6) ↔ `schemas/user.py:67-93` (min 8) — şifre uzunluğu tutarsız; `sistem/kullanicilar/+page.svelte:333` placeholder "En az 6 karakter" (gerçek 8)
- `sales/reservations/sedna_import.py:34-37` — `GET /sedna-status` yalnız `get_current_user` (kardeş modüller `require_permission(view)`); `UploadsHistoryModal.svelte:62-68` — ikon-only butonda `aria-label` yok + `p-1.5` (~30px < 44px)
- `mesajlasma/CLAUDE.md:225-286` — düz-metin test kullanıcı şifreleri git'e commit ediliyor

### T15 — Frontend WS broadcast / ölü dinleyici (`finance.butce`)
- `finance/butce.py` (tüm dosya) — hiç `broadcast_finance_update` yok, `BroadcastModule`'da BUTCE sabiti yok; buna rağmen `finans/butce/+page.svelte:332` `onWsEvent('finance_updated', ...)` dinliyor → ölü kod/işlevsiz gerçek-zamanlılık (diğer tüm finans modülleri broadcast yapıyor)

### T16 — Diğer düşük (test kapsam derinliği, doküman küçük tutarsızlıkları, güvenlik notu)
- `test_scheduled_base.py` — ~43/46 test yalnız `MODULES[:1]` (`tax`) ile; `recurring`/`sgk` gibi modüllere özgü alanlar (`vendor_id`, `billing_offset_months`) jenerik testlerde geçmiyor
- `test_fis_icmali.py:109-122` — `voucher-detail` için 403 testi eksik (diğer 2 GET'te var)
- `test_checks.py:95-101` — `PATCH /{id}/status` happy-path (iptal kademesi) doğrudan test edilmemiş
- `dashboard/+page.svelte` — component/unit test yok (izin-bazlı kart görünürlüğü, `fmt()` testsiz)
- `ScheduledModule.svelte` — Vitest dosyası yok (onay modal, cari senkron gibi mantık testsiz)
- `system_server.py:195-200` — audit `action="restart"` standart listede yok (dokümante edilmemiş)
- `docs/modules/muhasebe-ik.md:14` — "4 alt modül" (gerçekte 5, dividend eklenince güncellenmemiş)
- `docs/modules/doviz.md:131-137` — onay muafiyeti gerekçesi (mutasyon endpoint'i yok) yazılmamış
- `docs/modules/vardiyalar.md` (hr.shifts) — "Test" alt başlığı yok (shift_schedule'da var)
- `system.docs` (`system_docs.py:122-142`) — tüm `.py/.svelte/.ts` kaynak kodunu geniş kullanıcı kitlesine sunuyor; literal secret olmadığı sürece risk yok, ama CI'ye gitleaks/detect-secrets önerilir
- `test_system_backup.py:1-55` — `run_backup`/`restore_backup` gerçek başarı yolu (commit/push/checkout) mock'lanmadan test edilmiyor (bilinçli, prod repo kirletmeme)
- `test_shift_schedule.py:38-48` — DELETE/bulk/copy-week için ayrı 403 testi yok (onay regresyonu var)

---

## 4. Kesişen Temalar (Modüller-Arası Tekrarlayan Desenler)

Aşağıdaki desenler tek bir modüle değil, çok sayıda modüle yayılmış sistemik sorunlardır. Bunların çoğu tekil bir kaynağın (ortak bileşen, ortak test yapısı, ortak handler) düzeltilmesiyle toplu kapatılabilir.

| # | Desen | Kök neden | Etkilenen alan | Toplu çözüm |
|---|---|---|---|---|
| **X1** | **Eksik RBAC 403 testi** (view/use ayrımı doğrulanmıyor) | Testler admin-only yazılmış; `viewer_user_headers`/`no_perm_user_headers` fixture'ları neredeyse hiç kullanılmıyor (repo-geneli grep boş) | ~15+ modül (T1) | Ortak test yapılarına (özellikle `test_scheduled_base.py` parametrik) view-only/no-perm 403 testi ekle |
| **X2** | **Doküman/kod sapması** (hayalet endpoint/kolon/parametre, bayat dosya haritası) | Kod değişince `docs/modules/*.md` + `api-haritasi.md` güncellenmemiş (CLAUDE.md "Değişiklik Dokümantasyonu — Zorunlu" kuralına aykırı) | 12+ doküman (T2, Y1/Y4/Y6/Y9/Y13) | Her modülde doküman-kod senkron denetimi; CI'de basit endpoint/kolon karşılaştırması |
| **X3** | **WS event literal string** (`WS_EVENT.*` kullanılmıyor) | Ortak `ScheduledModule.svelte` + ~18 sayfada literal desen; yalnız 2 sayfa sabiti kullanıyor | Proje-geneli (T3) | Ortak bileşen + sayfalarda `WS_EVENT.*`'e geçir (düşük risk, tipli union) |
| **X4** | **Gerekçesiz onay muafiyeti** | Eşleştirme/manuel/toplu endpoint'ler `check_approval` atlıyor ama gerekçe kodda/dokümanda yok | 8+ endpoint (T8) + Kritikler K4/K5 | Her bilinçli atlama için docstring + modül dokümanında tek satır gerekçe; ana CLAUDE.md istisna listesini referansla |
| **X5** | **Ortak handler tek modülle test** | `_handle_scheduled` 8 modülde paylaşılıyor, yalnız `hr.salary` uçtan-uca test edilmiş; AST testi yalnız handler varlığını yakalar | 8 scheduled + quality.forms (T9) | Modüle-özgü davranış dallarına (direction, vendor-sync, coerce) hedefli regresyon testi |
| **X6** | **UI: paylaşılan bileşen atlanıyor** (inline spinner, StatCard/Button/MoneyInput/ConfirmDialog elle) | Kanonik iskelet/bileşen yerine ada-stil elle yazım | 8+ sayfa (T5, T6) | Ortak bileşende düzelt → tüm modüllere yayılsın (özellikle `ScheduledModule.svelte`) |
| **X7** | **AA kontrast ihlali** (teal-600, gray-400) | Kanonik teal-700/gray-500 yerine düşük-kontrast tonlar | 6+ sayfa (T7) | Sayfa taraması + ton düzeltmesi |

---

## 5. Modül-Bazlı Önem Kırılımı

| Modül | Kritik | Yüksek | Orta | Düşük | Toplam |
|---|---|---|---|---|---|
| finance.butce | 2 | 1 | 2 | 2 | 7 |
| finance.banks | 0 | 1 | 2 | 3 | 6 |
| finance.krediler | 1 | 2 | 1 | 3 | 7 |
| finance.onay | 1 | 1 | 1 | 2 | 5 |
| finance.cariler | 0 | 1 | 2 | 3 | 6 |
| finance.checks | 0 | 1 | 3 | 3 | 7 |
| finance.avanslar | 0 | 0 | 1 | 3 | 4 |
| finance.doviz | 0 | 0 | 0 | 3 | 3 |
| finance.sales_invoices | 0 | 0 | 1 | 1 | 2 |
| quality.forms | 1 | 2 | 3 | 0 | 6 |
| quality.templates | 0 | 0 | 2 | 4 | 6 |
| sales.hotel_reservation | 0 | 2 | 0 | 4 | 6 |
| sales.flight | 0 | 0 | 1 | 1 | 2 |
| system.users | 0 | 2 | 1 | 3 | 6 |
| system.approval | 0 | 1 | 1 | 2 | 4 |
| system.error_logs | 0 | 2 | 2 | 2 | 6 |
| system.server | 0 | 1 | 1 | 3 | 5 |
| system.roles | 0 | 0 | 2 | 1 | 3 |
| system.modules | 0 | 0 | 1 | 3 | 4 |
| system.audit_logs | 0 | 0 | 1 | 3 | 4 |
| system.backup | 0 | 0 | 0 | 2 | 2 |
| system.docs | 0 | 0 | 0 | 1 | 1 |
| yonetim.panel | 0 | 1 | 1 | 0 | 2 |
| dashboard (Panel) | 0 | 0 | 1 | 2 | 3 |
| messaging | 0 | 0 | 2 | 3 | 5 |
| accounting.taxes | 0 | 0 | 1 | 2 | 3 |
| accounting.recurring | 0 | 0 | 2 | 0 | 2 |
| accounting.rent_income | 0 | 0 | 1 | 2 | 3 |
| accounting.rent_expense | 0 | 0 | 1 | 3 | 4 |
| accounting.dividend | 0 | 0 | 2 | 2 | 4 |
| accounting.fis_icmali | 0 | 0 | 0 | 1 | 1 |
| accounting.mizan | 0 | 0 | 0 | 1 | 1 |
| hr.salary | 0 | 0 | 1 | 2 | 3 |
| hr.withholding | 0 | 0 | 2 | 1 | 3 |
| hr.sgk | 0 | 0 | 2 | 1 | 3 |
| hr.shifts | 0 | 0 | 0 | 2 | 2 |
| hr.shift_schedule | 0 | 0 | 0 | 2 | 2 |
| stok.urunler | 0 | 0 | 1 | 2 | 3 |
| stok.hareketler | 0 | 0 | 1 | 1 | 2 |
| stok.maliyet | 0 | 0 | 1 | 1 | 2 |
| stok.depolar | 0 | 0 | 1 | 1 | 2 |
| **TOPLAM** | **5** | **21** | **50** | **83** | **159** |

> Placeholder/boş girdiler (`finance.cash_flow`, `hr.attendance`, `sales.room_types`, `sales.daily_reservations`) tabloya dahil edilmemiştir.

**Öne çıkan öncelikler:** Onay akışı entegrasyonu (5 Kritik + birçok Yüksek) en riskli alandır — özellikle `finance.butce`'nin ana yazma yolunun onayı atlaması (K1/K2), `finance.krediler` close/reopen'ın sessizce yanlış uygulanması (K3) ve `quality.forms` durum geçişlerinin muaf kalması (K5) öncelikli düzeltilmelidir. İkinci öncelik `reservation_service.py`'deki NameError'a yol açan import hatası (Y10) ve `yonetim.panel` cache invalidation eksikliğidir (Y18 — hem test hem prod'da kanıtlı). Sistemik olarak en yaygın iki tema **eksik RBAC 403 testleri** (X1) ve **doküman/kod sapması** (X2) olup, ortak test yapıları ve doküman senkronizasyonuyla toplu kapatılabilir.

</details>

## Tüm Bulgular (Önem Sırasına Göre)

### 🔴 Kritik (5)

**K1. `finance.butce` — Onay akışı (ZORUNLU) — check_approval eksik**  
*Yer:* `backend/app/routers/finance/butce.py:288-344 (bulk_upsert_budgets)`  
POST /finance/butce/bulk endpoint'i hiçbir check_approval() çağrısı yapmıyor; ayrıca doğrudan router içinde elle Budget() insert/update yapıyor (budget_service.upsert_budget kullanmıyor, service katmanını bypass ediyor). CLAUDE.md 'dosya yükleme/toplu işlem' istisnasını tanısa da bu istisna Excel/PDF içe-aktarma gibi operasyonel toplu işlemler içindir — burada 'bulk' aslında normal kullanıcı tetikli CRUD mutasyonudur (frontend TEK hücre değişiminde bile bu endpoint'i çağırıyor, bkz. sonraki bulgu). Sonuç: bütçe modülünün GERÇEK yazma yolu (tekil upsert değil, /bulk) onay akışından tamamen muaf kalıyor — CLAUDE.md'nin 'Tüm modüllerin POST/PATCH/DELETE endpoint'leri onay kontrolünden geçmelidir' kuralını ihlal ediyor. Aynı router'da POST '/' (upsert_budget) check_approval + budget_service.upsert_budget kullanırken /bulk bunları atlıyor → aynı iş için iki farklı davranış (drift riski — approval_executor'daki create/update mantığıyla senkron değil).

**K2. `finance.butce` — Onay akışı ile fiili kullanım deseni çelişkisi**  
*Yer:* `frontend/src/routes/dashboard/finans/butce/+page.svelte:202-220 (saveBudgetCell)`  
Bütçe grid sayfasındaki HER hücre değişikliği (tek ay/kategori planlanan tutarı) `POST /finance/butce/bulk` çağırır — sayfanın normal/ana kaydetme yolu budur (800ms debounce ile). Tekil upsert endpoint'i (`POST /finance/butce/`, onaylı ve regresyon testli) frontend'den hiç çağrılmıyor. Böylece finance.butce için bir onay iş akışı tanımlansa bile kullanıcının günlük bütçe girişleri onay sürecine hiç girmeden doğrudan uygulanıyor — CLAUDE.md'nin onay akışı zorunluluğunu fiilen etkisiz kılıyor.

**K3. `finance.krediler` — Onay akışı (executor handler) — router davranışını birebir yansıtmalı**  
*Yer:* `backend/app/routers/finance/krediler/products.py:417-422 (close), 482-487 (reopen) ↔ backend/app/utils/approval_executor.py:286-318 (_handle_finance_krediler)`  
close_product/reopen_product endpoint'leri check_approval(db, 'finance.krediler', product_id, user.id, 'update', {'action': 'close'|'reopen', ...}) çağırıyor (özel 'action' anahtarlı payload). _handle_finance_krediler bu 'action' alanını hiç okumuyor — yalnızca _target=='payment' ayrımı yapıp değilse genel 'update' dalında credit_service.apply_product_update(db, product, payload) çağırıyor. apply_product_update ise payload'daki her key için doğrudan setattr(product, key, value) yapıyor (hasattr kontrolü yok): payload {'action':'close','closed_date':'...'} onaylanınca product.action='close' (DB kolonu olmayan, sessizce yutulan Python attribute) set edilir, product.closed_date güncellenir AMA product.status hiçbir zaman 'closed' olmaz ve ödenmemiş taksitlerin finance_event_svc.invalidate/upsert_credit_payment çağrıları hiç çalışmaz. Onay üzerinden yapılan kredi kapatma/yeniden-açma talebi onaylandıktan sonra sessizce yanlış uygulanır (durum değişmez, finance_events nakit akımdan çıkmaz/geri gelmez). tests/test_approval_system.py içinde krediler için create/payment-update/product-delete regresyon testleri var ama close/reopen regresyonu yok — bu sınıf hatayı böyle bir test yakalardı.

**K4. `finance.onay` — Onay Akışı Entegrasyonu — Zorunlu (check_approval)**  
*Yer:* `backend/app/routers/finance/onay.py:87-386 (tüm POST endpoint'leri)`  
assign_department (87), approve_transaction (228), reject_transaction (302), remove_assignment (353) — modülün 4 mutasyon endpoint'inin HİÇBİRİ `check_approval(db, 'finance.onay', ...)` çağırmıyor. CLAUDE.md 'Tüm modüllerin POST/PATCH/DELETE endpoint'leri onay kontrolünden geçmelidir' kuralına aykırı; istisna listesi (dosya yükleme/toplu işlem/eşleştirme/salt-okunur Sedna) bu endpoint'leri kapsamıyor. Not/nüans: modülün kendisi zaten bir 'departman onay iş akışı' (dept_status: pending→approved/rejected) olduğundan, sistem-seviyesi onay akışına (approval_workflows) tabi tutulması kavramsal bir çakışma yaratabilir (onayı onaylatmak). Ancak bu istisna CLAUDE.md'de veya docs/modules/onay.md'de açıkça gerekçelendirilmemiş — bilinçli bir mimari karar mı yoksa gözden kaçmış bir modül mü belirsiz. approval_executor.py'de de finance.onay için hiçbir handler yok (grep sonucu boş) — bu tutarlı (check_approval hiç çağrılmadığından handler gerekmiyor) ama testler (`test_approval_system.py::test_all_approval_callers_have_executor_handler`) bu tür 'hiç çağırmayan modül' durumunu YAKALAMIYOR çünkü AST testi yalnızca check_approval çağıran modülleri tarıyor. Öneri: CLAUDE.md/docs/modules/onay.md içine bu istisnanın gerekçesi (departman onayı zaten kendi onay mekanizması) açıkça yazılmalı; yoksa check_approval entegre edilmeli.

**K5. `quality.forms` — Onay akışı (ZORUNLU) — CLAUDE.md § Onay Akışı Entegrasyonu**  
*Yer:* `backend/app/routers/quality/forms/fill_submit.py:52-116 (fill), 122-208 (submit), 214-272 (review), 278-328 (reopen)`  
PATCH /forms/{id}/fill, POST /forms/{id}/submit, POST /forms/{id}/review, POST /forms/{id}/reopen — dördü de state mutasyonu yapan PATCH/POST endpoint'leri (form.status, form değerleri, review_comment, reviewed_by değiştiriyor) ama hiçbirinde check_approval() çağrısı yok. Sadece crud.py'deki create (satır 160) ve delete (satır 223) onay kontrolünden geçiyor. CLAUDE.md 'Tüm modüllerin POST/PATCH/DELETE endpoint'leri onay kontrolünden geçmelidir' der; dosya yükleme/toplu işlem/eşleştirme gibi bilinçli istisnalar bu endpoint'lere uymuyor (bunlar iş akışı durum geçişleri, özel/istisnai kategoriye girmiyor). Sonuç: bir workflow tanımlansa bile form doldurma/gönderme/onaylama/reddetme/yeniden-açma asla onaya düşmez.

### 🟠 Yüksek (18)

**Y1. `finance.banks` — Dokümantasyon (docs/modules/*.md güncel olmalı)**  
*Yer:* `docs/modules/bankalar.md:40-63, 96-97`  
Doküman gerçek şemayla uyuşmuyor: 'bank_accounts' tablosunda dokümante edilen 'name' (satır 40) ve 'balance' (satır 44) kolonları backend/app/models/bank_account.py içinde MEVCUT DEĞİL (gerçek kolonlar: bank_name, branch_name, account_no, iban, currency, holder_name, blocked_amount, is_active, created_by, created_at). Ayrıca 'bank_transactions' tablosu için dokümante edilen 'transaction_date' (satır 54) ve 'tag_category_id' (satır 60) kolon adları da yanlış — gerçek model kolonu 'date' ve 'category_id' (backend/app/models/bank_transaction.py:40,60). Bu doküman kod ile senkron değil, geliştiriciyi yanlış yönlendirir.

**Y2. `finance.butce` — Test — RBAC ve onay-akışı regresyon eksikliği**  
*Yer:* `backend/tests/test_budget.py:1-205`  
Tüm testler tek `auth_headers` (admin) fixture'ı ile yazılmış; `viewer_user_headers`/`no_perm_user_headers` ile 403 yolu hiç test edilmiyor (yalnız test_permissions.py genel listesinde birkaç GET/POST/DELETE path'i var, o da admin ve kimliksiz erişimle sınırlı — gerçek view-only/no-perm kullanıcı testi yok). Ayrıca `/bulk` endpoint'i için onay-akışı regresyon testi de yok (zaten check_approval çağırmadığından mantıklı ama bu durumun kendisi bir gerekçe belgesi/test ile açıkça işaretlenmemiş). test_approval_system.py'de yalnızca tekil POST '/' için `test_budget_create_via_approval_upserts_not_duplicate` var; kategori CRUD ve /bulk için onay regresyonu yok.

**Y3. `finance.cariler` — Onay Akışı (ZORUNLU) — check_approval eksikliği**  
*Yer:* `backend/app/routers/finance/payment_instructions.py:158-386 (create_instruction_list, update_instruction_list, delete_instruction_list, add_items, update_item, delete_item)`  
Ödeme Talimatı listeleri/kalemleri üzerindeki 6 mutasyon endpoint'inin hiçbirinde `check_approval()` çağrısı yok ve CLAUDE.md'nin izin verdiği istisna kategorilerinden (dosya yükleme, toplu işlem, eşleştirme, salt-okunur içe aktarma) hiçbirine girmiyor — normal CRUD. Ne router docstring'inde ne de docs/modules/cariler.md'de bu muafiyet için bir gerekçe yazılı. Toplu ödeme talimatları banka portalına yüklenen gerçek para hareketleri ürettiğinden (YKB Excel export) onay atlanması riskli. Öneri: ya check_approval() ekle ya da CLAUDE.md'deki istisna listesine uygun açık bir gerekçe (docstring + docs/modules/cariler.md) yaz.

**Y4. `finance.checks` — Dokümantasyon güncelliği (madde 10)**  
*Yer:* `docs/modules/cekler.md:54,85,121,188,231-238`  
Modül dokümanı çek durumlarını 'pending/cashed/returned/cancelled' olarak anlatıyor ve 'Durum Geçişleri' bölümünde pending→cashed / pending→returned akışını tarif ediyor. Ancak gerçek kod (backend/app/models/check.py:75, backend/app/routers/finance/checks.py:262 `pattern="^(pending|paid|cancelled)$"`, check_import.py:36-43 `_check_status_from_pos`) yalnızca üç durumu tanır: pending, paid, cancelled. 'cashed' ve 'returned' kodda hiç kullanılmıyor — doküman kod gerçekliğinden önemli ölçüde sapmış (hayalet durum değerleri), yeni geliştiriciyi yanlış yönlendirir.

**Y5. `finance.krediler` — WS Broadcast — Zorunlu (her CRUD işlemi sonunda broadcast_finance_update çağrılmalı)**  
*Yer:* `backend/app/routers/finance/krediler/products.py:252-388 (create_product/update_product/delete_product), backend/app/routers/finance/krediler/payments.py:24-158 (add_payments/update_payment/delete_payment)`  
Yalnızca close_product (satır 458) ve reopen_product (satır 523) broadcast_finance_update(background_tasks, BroadcastModule.CREDITS, 'update') çağırıyor. Temel CRUD endpoint'leri (create/update/delete ürün, add/update/delete ödeme) hiç broadcast tetiklemiyor ve BackgroundTasks parametresi bile almıyor. CLAUDE.md 'Her CRUD işlemi sonunda broadcast' kuralına aykırı — bir kullanıcı kredi ürünü/ödeme ekler-günceller-silerse, aynı anda krediler/nakit akım sayfasını açık tutan diğer kullanıcılar/sekmeler WS ile bilgilendirilmez (yalnız işlemi yapanın kendi tarayıcısı loadData() ile HTTP polling benzeri manuel yeniden çekme yapıyor).

**Y6. `finance.krediler` — Dokümantasyon — docs/modules/<modül>.md güncel olmalı**  
*Yer:* `docs/modules/krediler.md:28-30 (Dosya Haritası), :44-72 (Veritabanı Şeması), :26 (_helpers.py içeriği)`  
Doküman ciddi ölçüde bayat: (1) 'app/models/credit_payment.py' ayrı dosya olarak listelenmiş ama CreditPayment gerçekte credit_product.py içinde tanımlı; (2) credit_products tablo şeması tamamen yanlış — dokümanda 'principal'/'is_active' kolonları var ama gerçek modelde yok (gerçek: total_amount, remaining_amount, status, closed_date, bsmv_rate, commission_rate, linked_account_id); credit_payments şemasında dokümanda 'payment_date'/'status'/'remaining_balance' var ama gerçek modelde 'due_date'/'is_paid'+'paid_date'/match_number var; (3) _helpers.py açıklamasında hâlâ _regenerate_bch_payments/_regenerate_kmh_payments'ın orada olduğu yazıyor ama bu fonksiyonlar D1-2 (2026-06-22) ile app/services/credit_service.py'ye taşındı — doküman bu taşımayı hiç yansıtmıyor; (4) app/services/credit_service.py (router+executor ortak service mimarisi) ve approval_executor.py::_handle_finance_krediler hiç anılmıyor. finans router CLAUDE.md (backend/app/routers/finance/CLAUDE.md) bu D1-2 mimarisini doğru belgelemiş ama modül-özel docs/modules/krediler.md senkronize edilmemiş.

**Y7. `finance.onay` — Test kapsamı — happy-path + gerçek RBAC (403) + onay akışı**  
*Yer:* `backend/tests/test_onay.py:1-98`  
Test dosyası yalnızca 404 (kayıt yok) ve 401/403 (auth yok — login olmadan) senaryolarını kapsıyor. Hiçbir test: (1) gerçek başarılı bir departman ataması (assign→200/pending), (2) departman müdürü olarak gerçek onaylama (approve→200/approved + Budget.actual_amount güncellemesi), (3) reddetme (reject→200/rejected), (4) yetkisiz/departman-müdürü-olmayan kullanıcının onaylama denemesi (403 'Bu departmanın onay yetkiniz yok'), (5) viewer_user_headers/no_perm_user_headers ile gerçek RBAC 403 testi yapmıyor. CLAUDE.md 11. madde: 'En az happy-path + RBAC (403 yolu, viewer_user_headers/no_perm_user_headers) + onay akışı testi var mı? Salt-200 yüzeysel testlerden kaçınılmış mı?' — bu modül tam tersi durumda: salt-404/401 yüzeysel testler var, happy-path ve gerçek yetki testi yok. Diğer finans modülleri (test_advances.py, test_checks.py) gerçek create/update/delete akışlarını test ediyor, bu modül etmiyor.

**Y8. `quality.forms` — Onaylanan talep için executor handler eksiksiz olmalı — CLAUDE.md § Onay Akışı Entegrasyonu**  
*Yer:* `backend/app/utils/approval_executor.py:477-492 (_handle_quality_forms)`  
_handle_quality_forms yalnız action_type=='create' ve 'delete' işliyor; 'update' dalı yok. Bu, madde 1'deki eksikliğin doğal sonucu (fill/submit/review/reopen zaten check_approval çağırmadığı için hiç 'update' payload'ı üretilmiyor) ama executor'ın kendisi de bu senaryoyu desteklemiyor — ileride biri fill/submit/review/reopen'a check_approval eklerse (action='update') executor'da karşılık gelen dal bulunmayacak ve payload sessizce kaybolacak/hata verecek.

**Y9. `quality.forms` — Dokümantasyon — docs/api-haritasi.md güncel olmalı**  
*Yer:* `docs/api-haritasi.md:247-251`  
Kalite Yönetimi bölümü kodla uyuşmuyor: (a) 'PATCH /api/quality/forms/{id}' diye hayalet bir endpoint listelenmiş — kodda böyle bir PATCH yok (gerçek endpoint PATCH /forms/{id}/fill, ayrıca yanlışlıkla 'POST /forms/{id}/fill' olarak da yazılmış — kod POST değil PATCH kullanıyor: fill_submit.py:52). (b) GET /api/quality/forms/{id} (form detay, crud.py:120), DELETE /api/quality/forms/{id} (crud.py:211), POST /api/quality/forms/{id}/reopen (fill_submit.py:278), GET /api/quality/forms/{id}/pdf (pdf.py:21) hiç dokümante edilmemiş.

**Y10. `sales.hotel_reservation (Otel Rezervasyon)` — Onay akışı / Kod kalitesi — services/ katmanı HTTP'siz olmalı + import hatası**  
*Yer:* `backend/app/services/reservation_service.py:160`  
`run_reservation_import` fonksiyonu DB hatası olduğunda `raise HTTPException(status_code=500, detail="Rezervasyon senkronu sırasında veritabanı hatası.")` çağırıyor, ama dosyada `HTTPException` hiç import edilmemiş (import listesi: json, logging, date, Optional, Session, ExchangeRate, Reservation, User, log_action, fetch_reservations — satır 8-19). Gerçek bir DB hatası tetiklendiğinde `NameError: name 'HTTPException' is not defined` fırlar; kullanıcıya 500 + anlamlı mesaj yerine belirsiz bir unhandled exception döner. Ayrıca CLAUDE.md 'services/ = domain iş mantığı, HTTP'siz' ayrımına da aykırı — services katmanı FastAPI'nin HTTPException'ına bağımlı olmamalı, hatayı router'a/çağırana fırlatıp orada HTTP'ye çevirmeli.

**Y11. `sales.hotel_reservation (Otel Rezervasyon)` — Test — RBAC (403) kapsamı**  
*Yer:* `backend/tests/test_reservations.py (tüm dosya, örn. satır 217-225)`  
`test_reservations.py` upload/listing/summary/delete-upload/bulk-delete endpoint'lerini kapsıyor ama yalnızca `test_unauthorized_blocked` ile 401 (kimlik doğrulama yok) senaryosunu test ediyor. `viewer_user_headers`/`no_perm_user_headers` fixture'ları hiç kullanılmamış → view-izinli-ama-use-izinsiz bir kullanıcının POST/DELETE/bulk-delete'e 403 alması test edilmemiş. Kardeş dosya `test_reservation_sedna.py:44-45`'te aynı kalıp (`test_import_requires_use`) doğru uygulanmış — ana modülde eksik.

**Y12. `system.approval` — İzin sistemi — mutasyon endpoint'i 'use' ile korunmalı**  
*Yer:* `backend/app/routers/approval/requests.py:492-498 (cancel), 546-552 (resubmit), 584-590 (trigger)`  
cancel_request, resubmit_request ve trigger_approval endpoint'leri POST (mutasyon: durum değiştirir / yeni ApprovalRequest oluşturur) olmalarına rağmen require_permission("system.approval", "view") ile korunuyor — approve/reject/return ise doğru şekilde "use" istiyor (satır 352, 417, 459). CLAUDE.md 'İzin Sistemi' kuralı: her POST/PATCH/DELETE 'use' ile korunmalıdır. Şu an sadece view izni olan (use'u olmayan) bir kullanıcı kendi talebini iptal/yeniden gönderebilir veya /trigger'ı çağırabilir. cancel/resubmit'te iş-mantığı (owner/approver kontrolü) ek bir güvenlik katmanı sağlasa da, modülün deklare edilen izin modeliyle (can_view=görme, can_use=ekleme+düzenleme+silme) tutarsız; view-only kullanıcı teorik olarak /trigger çağırıp başka bir modülde (entity_type dışarıdan verilen) sahte bir onay talebi tetikleyebilir.

**Y13. `system.error_logs` — Onay akışı (ZORUNLU) — check_approval çağrısı**  
*Yer:* `backend/app/routers/error_logs.py:78-107`  
DELETE /{log_id} ve DELETE / (toplu temizleme) endpoint'leri check_approval(db, "system.error_logs", ...) çağırmıyor. CLAUDE.md 'Tüm modüllerin POST/PATCH/DELETE endpoint'leri onay kontrolünden geçmelidir' der; istisna listesi ('dosya yükleme, toplu işlem, eşleştirme') bu durumu net kapsamıyor — hata logu silme salt-teknik/idempotent bir işlem olsa da kural gereği ya check_approval eklenmeli ya da modül CLAUDE.md'sinde/doküманda açık istisna gerekçesi yazılmalı. Şu an docs/modules/hata-loglari.md'de de bu konuda hiçbir gerekçe yok. Approval_executor.py'de de system.error_logs için handler yok (check_approval çağrılmadığı için AST testi de bunu yakalamaz).

**Y14. `system.error_logs` — Dokümantasyon — docs/modules/hata-loglari.md kod ile uyumsuz**  
*Yer:* `docs/modules/hata-loglari.md:6,19-32`  
Doküman frontend rotasını `/dashboard/sistem/hata-loglari` olarak veriyor ama gerçek klasör/route `frontend/src/routes/dashboard/sistem/hata-loglar` (navigation.ts:156 de aynı şekilde `/dashboard/sistem/hata-loglar`). Ayrıca 'Veri Modeli' tablosu tamamen hayalet kolonlar listeliyor: status_code, error_type, error_message, stack_trace, request_body — gerçek ErrorLog modelinde (backend/app/models/error_log.py:19-26) bunlar yok; gerçek kolonlar level, source, message, traceback, method, path, user_id, ip_address'tir. Doküman kod değişmeden önce yazılmış eski bir tasarımı yansıtıyor, hiç güncellenmemiş.

**Y15. `system.server (Sunucu İzleme)` — Test kapsamı — RBAC (403 yolu)**  
*Yer:* `backend/tests/test_system_server.py:1-270`  
Dosyadaki tüm testler yalnızca `auth_headers` (admin) ile çalışıyor. conftest.py'de hazır olan `viewer_user_headers` (can_view=True/can_use=False) ve `no_perm_user_headers` fixture'ları hiç kullanılmamış. CLAUDE.md madde 11 'en az happy-path + RBAC (403 yolu, viewer_user_headers/no_perm_user_headers)' testini zorunlu kılıyor. require_permission('system.server','use') / ('system.server','view') bağımlılıklarının gerçekten 403 döndürdüğü — view-only kullanıcının POST/restart denemesi, hiç izni olmayan kullanıcının GET denemesi — hiç test edilmiyor; sadece tamamen auth'suz (401/403 karışık) senaryo var.

**Y16. `system.users` — Onay akışı (ZORUNLU) — check_approval her mutasyonda**  
*Yer:* `backend/app/routers/system_users.py:178-203`  
`reset_password` endpoint'i POST metodu ile hassas bir mutasyon yapıyor (şifre hash'i değiştirme + `active_session_id=None` ile oturum kapatma) ama `check_approval()` çağrısı hiç yok — sadece `log_action` var. CLAUDE.md 'Tüm modüllerin POST/PATCH/DELETE endpoint'leri onay kontrolünden geçmelidir' der ve istisna listesi yalnız 'dosya yükleme, toplu işlem, eşleştirme' içindir; şifre sıfırlama bu listede yok. approval_executor.py:227-243'teki `_handle_system_users` da yalnız create/update/delete action_type'larını işliyor, reset-password için bir dal yok — yani bu endpoint onay akışının tamamen dışında bırakılmış ve bu bilinçli istisna docs/modules/sistem-kullanicilar.md'de gerekçelendirilmemiş.

**Y17. `system.users` — Test — modül-bazlı uçtan-uca onay regresyon testi**  
*Yer:* `backend/tests/test_approval_system.py:718-743`  
`test_user_create_password_redacted_e2e` yalnızca onay talebinin 202 döndüğünü ve payload'da şifrenin redakte edildiğini doğruluyor; `approve()` hiç çağrılmıyor. CLAUDE.md, `_handle_system_users` gibi executor handler'lar için 'onaylanınca gerçekten uygulanıyor mu' diye uçtan-uca regresyon testi zorunlu tutuyor (örnek desen: `test_create_room_type_via_approval_regression`, `test_check_status_via_approval_regression`). `system.users` için böyle bir test (onayla → kullanıcı gerçekten DB'de oluştu/güncellendi/silindi mi) yok; AST testleri (`TestExecutorImportIntegrity`) yalnız import/alan geçerliliğini yakalar, payload-key uyuşmazlığı veya yan-etki eksikliğini yakalamaz.

**Y18. `yonetim.panel` — Test izolasyonu / cache invalidation eksikliği (finans veri tazeliği)**  
*Yer:* `backend/app/routers/yonetim.py:33-48 (_cache global dict + _cached())`  
`_cache` process-içi global dict, 60 sn TTL ile `/yonetim/dashboard` sonucunu önbelleğe alıyor ancak eşdeğer `sales_invoice_service.py` cache'inin aksine (orada `_invalidate_compute_cache()` var, satır 137) hiçbir invalidation hook'u YOK. Kanıt: `tests/test_yonetim_panel.py::TestDashboard::test_dashboard_shape` ve `tests/test_cost_control.py::test_yonetim_dashboard` aynı pytest sürecinde art arda çalıştırıldığında ikincisi başarısız oluyor (`assert 0 == 100.0`) — ilk testin ürettiği eski/boş sonuç cache'den dönüyor. Doğrulama komutu: `python -m pytest tests/test_yonetim_panel.py::TestDashboard::test_dashboard_shape tests/test_cost_control.py::test_yonetim_dashboard -q` → `1 failed, 1 passed`; tek başına her iki dosya da geçiyor (saf cache-kirliliği, iş mantığı hatası değil). Production riski aynı yönde: bir Sedna/rezervasyon senkronu veya finans mutasyonu sonrası GM paneli 60 saniyeye kadar bayat veri gösterebilir çünkü hiçbir yerde cache invalidate edilmiyor. Öneri: `mizan.py`/`sales_invoice_service.py` deseninde açık bir `_invalidate_yonetim_cache()` eklenmeli ve ilgili senkron/mutasyon noktalarından (ya da en azından test conftest'inde autouse fixture ile) çağrılmalı.

### 🟡 Orta (49)

**O1. `accounting.dividend` — Test — Onay akışı (madde 11 + CLAUDE.md 'modül-bazlı uçtan-uca onay regresyon testi')**  
*Yer:* `backend/tests/test_scheduled_base.py (tüm dosya, 725 satır) ve backend/tests/test_approval_system.py:766-800`  
accounting.dividend için onay akışını (check_approval → 202 → executor _handle_scheduled → aktifleşme) doğrudan test eden bir regresyon testi yok. test_scheduled_base.py hiç approval/check_approval/requires_approval test etmiyor. test_approval_system.py'deki tek scheduled-onay testi (test_scheduled_salary_create_via_approval) yalnızca hr.salary üzerinden çalışıyor; dividend paylaşılan _handle_scheduled/scheduled_service kodunu kullandığından dolaylı örtülüyor ama CLAUDE.md'nin özellikle önerdiği 'modül-bazlı' regresyon testi (ör. test_create_room_type_via_approval_regression gibi) dividend için mevcut değil. AST testi (TestExecutorImportIntegrity) yalnızca handler'ın VAR olduğunu doğrular, payload/davranış doğruluğunu değil.

**O2. `accounting.dividend` — Test — RBAC/izin testi (madde 11)**  
*Yer:* `backend/tests/test_scheduled_base.py:707-724 (class TestPermissions)`  
TestPermissions sınıfı yalnızca kimlik-doğrulaması-olmayan istekleri (401/403) test ediyor; viewer_user_headers/no_perm_user_headers/use_user_headers fixture'ları dosyada hiç kullanılmıyor (grep sonucu boş). Yani 'view' iznine sahip ama 'use' izni olmayan bir kullanıcının POST/PATCH/DELETE'te gerçekten 403 aldığı doğrulanmıyor — yalnızca require_permission'ın var olduğu (router koduyla) biliniyor, ama davranışsal test yok. Bu eksiklik dividend dahil parametrize edilen 8 modülün tamamını etkiliyor (modüle özgü değil, ortak test dosyasından kaynaklanıyor).

**O3. `accounting.recurring` — Test kapsamı — modül-bazlı derinlik**  
*Yer:* `backend/tests/test_scheduled_base.py:15-24 (MODULES listesi) + parametrize kullanımı (örn. satır 74,85,94,105,129,135,141,147,153,159,184,196,210,222,247,260,266,284,302,320,338,351,361,394,417,431,437,458,474,488,502,512,525,539,579,596,618,631,657)`  
46 test fonksiyonundan yalnızca 3 tanesi (`test_create_monthly`, `test_list_empty`, `test_summary_structure`) `MODULES` (8 modülün tamamı) ile parametrize; kalan ~43 test `MODULES[:1]` yani yalnızca `tax` (accounting.taxes) üzerinde çalışıyor. `accounting.recurring` için update/delete/cascade/entry-update/pagination/lifecycle senaryolarının hiçbiri doğrudan test edilmiyor — fabrika ortak kod olduğu için risk düşük ama `recurring`'e özgü davranış (vendor_id alanı, billing_offset_months) bu jenerik testlerde hiç geçmiyor.

**O4. `accounting.recurring` — Onay akışı — modül-bazlı uçtan-uca regresyon testi**  
*Yer:* `backend/tests/test_approval_system.py:766 (test_scheduled_salary_create_via_approval, yalnızca hr.salary için)`  
CLAUDE.md 'yeni handler için modül-bazlı uçtan-uca onay regresyon testi eklenmeli' diyor; scheduled fabrikasının onay regresyon testi yalnız `hr.salary` ile yazılmış. `accounting.recurring`'in kendine özgü dalı — onay sırasında `vendor_id` set edilmiş bir tanımın onaylanınca `scheduled_service.post_create` üzerinden `sync_recurring_from_vendors`'ı gerçekten tetikleyip tetiklemediği — ayrı test edilmiyor. AST testi (`test_all_approval_callers_have_executor_handler`) yalnız handler'ın VARLIĞINI doğruluyor, vendor-sync yan etkisinin çalıştığını doğrulamaz.

**O5. `accounting.rent_expense` — Test — modül-bazlı onay regresyon testi (CLAUDE.md "Test katmanları" bölümü)**  
*Yer:* `backend/tests/test_approval_system.py:766 (yalnız test_scheduled_salary_create_via_approval var); backend/app/utils/approval_executor.py:139-148 (_SCHEDULED_SOURCE_MAP, 8 modül)`  
CLAUDE.md, AST testlerinin (TestExecutorImportIntegrity) payload-anahtar uyuşmazlığını/eksik yan-etkiyi yakalayamadığını belirtip her yeni handler için modül-bazlı uçtan-uca onay regresyon testi eklenmesini şart koşuyor. 8 scheduled modülden (taxes/recurring/rent_income/rent_expense/dividend/salary/withholding/sgk) yalnızca `salary` için böyle bir test var (`test_scheduled_salary_create_via_approval`). `accounting.rent_expense` için onay→executor uçtan-uca regresyon testi yok. Ortak `_handle_scheduled` kod yolu olduğundan risk düşük (salary testi dolaylı kapsıyor) ama kural harfiyen uygulanmamış.

**O6. `accounting.rent_income` — Test — RBAC (403) kapsamı**  
*Yer:* `backend/tests/test_scheduled_base.py:707-725 (TestPermissions), conftest.py:246-260 (auth_headers=admin)`  
TestPermissions sınıfı yalnızca kimlik doğrulaması OLMAYAN erişimi test ediyor (401/403 anonim). accounting.rent_income dahil 8 scheduled modülün hiçbirinde 'view var ama use yok' veya 'hiç izni yok' senaryosu (conftest.py'deki viewer_user_headers/no_perm_user_headers fixture'ları) ile gerçek RBAC 403 testi yok — tüm testler admin (tam yetkili) auth_headers ile çalışıyor. CLAUDE.md '11. Test' maddesi happy-path + RBAC (403 yolu) testi ister. Öneri: test_scheduled_base.py'ye rent_income (ve diğer scheduled modüller) için viewer_user_headers ile POST/PATCH/DELETE'in 403 döndüğünü doğrulayan parametrik test eklenmeli.

**O7. `accounting.taxes` — Test — RBAC (403) senaryosu eksik**  
*Yer:* `backend/tests/test_scheduled_base.py:1-728 (accounting.taxes dahil 8 modül parametrize)`  
Dosyada happy-path, validasyon, pagination, kaynak-izolasyonu ve `test_unauthenticated_*` (kimlik doğrulaması OLMAYAN istek → 401/403) testleri var; ancak CLAUDE.md madde 11'in istediği 'view-only/no-perm YETKİLİ kullanıcı POST/PATCH/DELETE dener → 403' senaryosu (`viewer_user_headers`/`no_perm_user_headers` fixture'ları) accounting.taxes için (ve diğer 7 scheduled modül için) hiç yok. `require_permission(permission_code, 'use')` doğru uygulanmış olsa da bunu doğrulayan bir test yok.

**O8. `dashboard (Panel)` — Dokümantasyon (CLAUDE.md "Değişiklik Dokümantasyonu" ve "Modül Dokümantasyon Şablonu")**  
*Yer:* `docs/modules/ (dashboard.md yok); CLAUDE.md Mevcut Modül Dokümantasyonları tablosu; backend/tests/ci/02_seed.sql:46`  
Panel (dashboard) modülü RBAC'ta kayıtlı (02_seed.sql:46 — code='dashboard') ve frontend/src/routes/dashboard/+page.svelte olarak var, ama docs/modules/ altında bu modüle ait bir doküman dosyası yok; CLAUDE.md'deki 'Mevcut Modül Dokümantasyonları' tablosunda da 'Panel'/'Dashboard' satırı bulunmuyor (sadece 'Yönetim Paneli' → yonetim-paneli.md var, o farklı bir modül: yonetim.panel). CLAUDE.md açıkça 'Her modülün kendi CLAUDE.md/doküman dosyası... Yeni modül eklerken bu klasöre modül dokümantasyonu oluşturulmalıdır' diyor. Modül basit bir salt-okuma aggregator olsa da en azından kısa bir doküman (genel bilgi + hangi endpoint'leri tükettiği + izin haritası) beklenir. Öneri: docs/modules/panel.md ekle, CLAUDE.md tablosuna satır ekle.

**O9. `finance.avanslar` — Onay akışı (ZORUNLU) — CLAUDE.md: 'Dosya yükleme, toplu işlem, eşleştirme gibi özel endpoint'ler hariç tutulabilir'**  
*Yer:* `backend/app/routers/finance/advances.py:221-262 (match_advance)`  
POST /avanslar/{id}/match endpoint'i mutasyon (status→received, received_date/received_amount/bank_transaction_id yazıyor) ama check_approval() çağrısı yok. CLAUDE.md 'eşleştirme' endpoint'lerini onaydan muaf tutabileceğini söylüyor, bu nedenle kural ihlali sayılmaz; ancak kod içinde veya docs/modules/avanslar.md'de bu istisnanın gerekçesi yazılı değil. Onay gerektiren bir workflow tanımlıysa, banka eşleştirmesiyle avans durumu onaysız 'received'e çekilebiliyor — bu maddi bir finansal durum değişikliği içerdiğinden CLAUDE.md ruhuna göre gözden geçirilmeli veya en azından gerekçe yorum satırıyla belirtilmeli.

**O10. `finance.banks` — Dokümantasyon — hayalet endpoint (dokümante edilip kodda olmayan)**  
*Yer:* `docs/modules/bankalar.md:97 vs backend/app/routers/finance/banks.py`  
Doküman 'DELETE /banks/accounts/{id}/statements/{stmt_id} — Ekstre sil (işlemler geri alınır)' endpoint'ini listeliyor ancak banks.py router'ında böyle bir endpoint YOK (router'da sadece GET /accounts/{id}/statements var, silme yok). Kullanıcı olmayan bir özelliğe güvenip API çağırmaya çalışabilir.

**O11. `finance.banks` — Onay akışı (ZORUNLU) — handler router davranışını birebir yansıtmalı**  
*Yer:* `backend/app/services/bank_account_service.py:10-22 vs backend/app/routers/finance/banks.py:140-151`  
Router create_account endpoint'i onaydan ÖNCE ve create_fn çağrısından önce IBAN tekrar kontrolü yapıp kullanıcıya net 'Bu IBAN zaten kayıtlı' (400) mesajı döner, ayrıca IntegrityError'ı da yakalayıp aynı mesajı verir (banks.py:141-151). Executor handler'ı (_make_crud_handler → bank_account_service.create_account) bu ön-kontrolü yapmaz; onaylı bir create sırasında IBAN çakışırsa IntegrityError doğrudan execute_approved_payload'ın genel except'ine düşer (approval_executor.py:59-62) → talep 'başarısız' loglanır ama kullanıcıya iş-kuralına özgü bir açıklama (IBAN çakışması) iletilmez, sadece generic hata. Router ile executor davranışı burada tam birebir değil (CLAUDE.md: 'Handler, router endpoint'inin davranışını BİREBİR yansıtmalı').

**O12. `finance.butce` — Merkezi sabitler — WS broadcast eksik / BroadcastModule'da tanımsız**  
*Yer:* `backend/app/routers/finance/butce.py (tüm dosya) ve backend/app/constants.py:78-102 (BroadcastModule)`  
butce.py hiçbir yerde `broadcast_finance_update()` çağırmıyor ve `BroadcastModule` sınıfında BUTCE/BUDGET için bir sabit de yok. Buna rağmen frontend +page.svelte:332 `onWsEvent('finance_updated', () => loadAllData())` ile dinliyor — backend hiçbir zaman bu event'i bütçe değişikliği için tetiklemediğinden bu dinleyici pratikte ölü kod / işlevsiz gerçek-zamanlılık. Başka bir kullanıcının aynı anda düzenlediği bütçe grid'i canlı yansımaz (sayfa yenilenene kadar). CLAUDE.md 'WS Broadcast — Zorunlu: Her CRUD işlemi sonunda broadcast' kuralına aykırı; diğer finans modülleri (advances, banks, checks, cariler vb.) hepsi BroadcastModule sabiti + broadcast_finance_update kullanıyor, butce dışarıda kalmış.

**O13. `finance.butce` — UI tasarım sistemi — MoneyInput yerine ham input**  
*Yer:* `frontend/src/routes/dashboard/finans/butce/+page.svelte:619-627`  
Bütçe grid hücrelerindeki para tutarı girişi `<Input type="text">` ile yapılıyor, `MoneyInput.svelte` kullanılmıyor. CLAUDE.md 'tüm para girişleri için MoneyInput zorunludur' der ve bütçe grid'i bilinçli istisnalar listesinde (mizan/fis-icmali/roller-matrisi/vardiya-çizelgesi/KMH yoğun-matris tabloları) yer almıyor. 12-aylık yoğun grid yapısı MoneyInput'un canlı-binlik-format/imleç-koruma UX'i olmadan basit string parse (`parseFloat(value.replace(',','.'))`) ile çalışıyor — TR biçimlendirme/binlik ayraç yok, kullanıcı '1234567' yazarsa canlı '1.234.567' görmez.

**O14. `finance.butce` — Dokümantasyon — /bulk onay muafiyeti belgelenmemiş**  
*Yer:* `docs/modules/butce.md:55-68 (API Endpoint'leri tablosu)`  
Doküman API tablosunda POST /bulk için 'Toplu bütçe upsert' yazıyor ama onay akışından muaf olduğuna dair hiçbir not/gerekçe yok (CLAUDE.md'nin 'Dosya yükleme, toplu işlem gibi özel endpoint'ler hariç tutulabilir' maddesi gerekçelendirme beklerken burada sessizce atlanmış). Router yorumlarında da (butce.py) bu muafiyetin bilinçli bir mimari karar olduğuna dair açıklama yok — CLAUDE.md'nin finans/CLAUDE.md'deki diğer modüllerde görülen 'onaydan muaf (gerekçe: ...)' yorum deseni burada eksik.

**O15. `finance.cariler` — Onay Akışı (ZORUNLU) — gerekçesiz muafiyet**  
*Yer:* `backend/app/routers/finance/cariler/matching.py:90-283 (match_vendor_with_check, unmatch_vendor_check, unmatch_vendor_transaction, mark_as_devir)`  
4 mutasyon endpoint'i check_approval() çağırmıyor. finance/cash_flow/matching.py'deki eşleştirme endpoint'leriyle tutarlı bir mimari örüntü (eşleştirme genel olarak onaydan muaf tutuluyor) olsa da, bu dosyada (matching.py başlık docstring'i dahil) CLAUDE.md'nin talep ettiği açık istisna gerekçesi yazılı değil — diğer muaf modüllerde (sedna_import.py, bank_accounts.py, uploads.py) docstring'de net gerekçe var, burada yok. match_number ataması finance_events'i doğrudan etkilediğinden belgelenmeli.

**O16. `finance.cariler` — Test — RBAC/happy-path kapsam boşluğu**  
*Yer:* `backend/app/routers/finance/cariler/matching.py (tüm endpoint'ler) — tests/ altında karşılık test yok`  
match-check, unmatch-check, unmatch, devir endpoint'leri için tests/ dizininde hiçbir test bulunamadı (pytest --collect-only ile doğrulandı: 'match-check'/'unmatch'/'devir' hiçbir test dosyasında geçmiyor). Skorlama mantığı (get_candidate_checks) ve match_number_seq akışı da testsiz. CLAUDE.md 'en az happy-path + RBAC + onay akışı testi' şartını karşılamıyor.

**O17. `finance.checks` — Dokümantasyon güncelliği (madde 10) — kodda var, dokümanda eksik**  
*Yer:* `docs/modules/cekler.md:16-30,74-87`  
Dosya haritası hâlâ tüm iş mantığının checks.py'de olduğunu varsayıyor; 2026-06-27 refactor sonrası oluşan app/routers/finance/check_import.py (Sedna içe-aktarma, dedup/infer/sweep mantığı) ve app/services/check_service.py hiç anılmıyor. Ayrıca 'Banka Tahmini' (bank_name_inferred/infer_check_banks), 'Çek No Uyuşmazlık Tespiti' (detect_check_no_mismatches) ve 'Bayat Çek Süpürme' (_sweep_stale_checks) mekanizmaları — backend/app/routers/finance/CLAUDE.md'de detaylıca belgelenmiş olmasına rağmen — docs/modules/cekler.md'ye hiç yansıtılmamış. API tablosunda da GET /checks/number-anomalies eksik (docs/api-haritasi.md'de doğru şekilde var, ama modül dokümanında yok).

**O18. `finance.checks` — Dosya yükleme limitleri tutarlılığı**  
*Yer:* `frontend/src/routes/dashboard/finans/cekler/+page.svelte:340`  
FileDropzone `maxSize={50 * 1024 * 1024}` (50 MB) kabul ediyor, ancak backend `validate_upload_file(file, allowed_types=["excel"])` (checks.py:66) Excel dosyaları için CLAUDE.md/file_validation.py kuralı gereği 10 MB üst sınır uyguluyor (MAX_EXCEL_SIZE). Kullanıcı 10-50 MB arası bir dosya seçtiğinde FileDropzone'da hata almadan yükleme denenir, backend 400 ile reddeder — gereksiz kafa karışıklığı. FileDropzone maxSize'ı 10 MB'a çekilmeli (docs/modules/cekler.md:93'te doğru 10 MB yazıyor, frontend bununla uyumsuz).

**O19. `finance.checks` — Test kapsamı — RBAC 403 yolu**  
*Yer:* `backend/tests/test_checks.py (tüm dosya, 26 test)`  
finance.checks'in ana CRUD endpoint'leri (PATCH /{id}/status, DELETE /uploads/{id}, POST /upload, POST /match-bank) için `viewer_user_headers`/`no_perm_user_headers` ile 403 testi yok. Yalnızca Sedna import endpoint'i için (`TestSednaCheckImport.test_requires_use`) view-only kullanıcının 403 aldığı test ediliyor. Diğer testler `test_list_without_auth` gibi yalnızca auth yokluğunu (401/403) kontrol ediyor, izin seviyesi (view vs use) ayrımını test etmiyor. CLAUDE.md'nin 'en az happy-path + RBAC (403 yolu)' test kuralına kısmi uyum.

**O20. `finance.krediler` — Onay akışı — tüm POST/PATCH/DELETE check_approval'dan geçmeli**  
*Yer:* `backend/app/routers/finance/krediler/payments.py:24-31 (add_payments)`  
POST /{product_id}/payments (toplu taksit/ödeme planı ekleme) hiç check_approval çağırmıyor; ayrıca credit_service ortak fonksiyonlarını da kullanmıyor, CreditPayment kayıtlarını doğrudan router içinde oluşturuyor. CLAUDE.md 'dosya yükleme, toplu işlem, eşleştirme gibi özel endpoint'ler hariç tutulabilir' istisnası burada gerekçelendirilmemiş — bu endpoint gerçek para hareketi (yeni taksit → finance_events) yaratıyor, otomatik/salt-veri senkron akışı (Sedna/Excel import) değil, elle girilen finansal veridir. Onay-muafiyeti bilinçli bir tasarım kararıysa gerekçesi kodda/dokümanda belirtilmeli; değilse check_approval eklenmeli ve executor'da 'bulk create' target'ı için handler yazılmalı.

**O21. `finance.onay` — UI Tasarım Sistemi — ConfirmDialog (native confirm() yasak, tehlikeli aksiyon onayı)**  
*Yer:* `frontend/src/routes/dashboard/finans/cariler/+page.svelte:1354,1519 (removeDeptAssignment çağrıları)`  
Departman atamasını kaldırma (`removeDeptAssignment`, finance/onay/remove/{vtx_id} çağıran fonksiyon) butonlarda doğrudan `onclick={() => removeDeptAssignment(tx.id)}` ile hiçbir onay diyaloğu (ConfirmDialog) olmadan tetikleniyor. Native confirm() kullanılmıyor (o kısım doğru) ama CLAUDE.md/docs/ui-kurallari.md 'Silme/onay diyaloğu' standardına göre geri alınamaz nitelikte olmasa da kullanıcı verisini sıfırlayan (department_id, budget_category_id, dept_status vb. tüm alanları null'a çeken) bir aksiyon için ConfirmDialog beklenir. Sayfada zaten ConfirmDialog import edilmiş (satır 12) ve başka yerlerde kullanılıyor (satır 1746) — bu aksiyona uygulanmamış.

**O22. `finance.sales_invoices` — Test kapsamı — RBAC (403 yolu) GET endpoint'lerinde eksik**  
*Yer:* `backend/tests/test_sales_invoices.py:36-37 (tüm dosya)`  
Modülde tek RBAC testi POST /sedna-import için var (viewer_user_headers ile 403). GET /sales-invoices/, /summary, /advances endpoint'lerinde izinsiz erişim (no_perm_user_headers veya view-izni-olmayan kullanıcı ile 403 bekleyen) testi yok. CLAUDE.md 11. madde 'en az happy-path + RBAC (403 yolu)' şartını her endpoint için ister; burada sadece mutasyon endpoint'i kapsanmış, 3 GET endpoint'i kapsanmamış.

**O23. `hr.salary` — Test (madde 11) — RBAC 403 yolu**  
*Yer:* `backend/tests/test_scheduled_base.py:707-725, backend/tests/test_permissions.py:38,72`  
hr.salary (ve fabrikayı paylaşan diğer 7 scheduled modül) için sadece 'kimliksiz erişim → 401/403' testleri var (TestPermissions.test_unauthenticated_*). CLAUDE.md madde 11 'RBAC (403 yolu, viewer_user_headers/no_perm_user_headers)' testini de zorunlu koşuyor; ancak conftest.py'deki viewer_user_headers/no_perm_user_headers/use_user_headers fixture'larını kullanan hiçbir test yok (repo genelinde grep boş döndü). Yani can_view-only bir kullanıcının POST/PATCH/DELETE'te gerçekten 403 aldığı, ya da hiç izni olmayan kullanıcının GET'te 403 aldığı ayrıca doğrulanmıyor — yalnızca require_permission'ın var olduğu router kodundan (statik) çıkarılıyor.

**O24. `hr.sgk` — Pagination (UI tasarım sistemi + CLAUDE.md Liste istek/yanıtı kuralı)**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte:317 (loadData) ve tüm dosya (Pagination.svelte import edilmemiş)`  
Backend `GET /api/hr/sgk/` doğru sayfalama yanıtı (`items, total, page, page_size, pages`) dönüyor (scheduled_base.py:105-127), ama frontend `ScheduledModule.svelte` bunu kullanmıyor: `api.get(`${apiPrefix}/?year=${selectedYear}&page_size=200`)` ile sabit 200 kayıt çekip `Pagination.svelte` bileşenini hiç render etmiyor (diğer kanonik sayfalar — avanslar, bankalar, onay-akışı — Pagination kullanıyor). Yıl başına tanım sayısı 200'ü aşarsa (çok departmanlı SGK kalemi gibi senaryoda) sessizce veri kaybı olur; ayrıca CLAUDE.md 'Pagination' zorunluluğuna aykırı.

**O25. `hr.sgk` — Test kapsamı — RBAC 403 (viewer_user_headers/no_perm_user_headers)**  
*Yer:* `backend/tests/test_scheduled_base.py:707-725 (TestPermissions sınıfı)`  
TestPermissions sınıfı yalnızca kimlik doğrulaması OLMAYAN (401/403) erişimi test ediyor ve yalnızca `/api/accounting/taxes` prefix'i ile (parametrize edilmemiş — MODULES listesi kullanılmıyor). `hr.sgk` dahil hiçbir scheduled modülde izni olan-ama-yetkisiz kullanıcı (`viewer_user_headers` sadece can_view veya `no_perm_user_headers`) ile 403 senaryosu test edilmiyor. CLAUDE.md'nin 'en az happy-path + RBAC (403 yolu)' test kuralına kısmen uyulmamış — happy-path zaten güçlü (parametrik CRUD+summary), ama yetki-reddi testi eksik.

**O26. `hr.withholding` — Onay akışı — payload tip coerce (CLAUDE.md: 'Onay payload'ı JSON'a serileşir → tarihler string olur; service tüketicisi date.fromisoformat ile coerce etmeli')**  
*Yer:* `backend/app/services/scheduled_service.py:60-81 (apply_entry_update); backend/app/utils/approval_executor.py:151-164 (_handle_scheduled, target=='entry' dalı); backend/app/utils/approval_check.py:111 (json.dumps(payload, default=str))`  
hr.withholding entry-update onay gerektiren bir role atanmışsa: router check_approval(db, permission_code, entry_id, ..., entry_payload) çağırır (scheduled_base.py:325-329), payload approval_check.py:111'de json.dumps(payload, default=str, ...) ile DB'ye yazılır — bu adımda Pydantic date nesneleri str(date(...)) formatına döner (ör. '2026-03-20'). Onaylandığında executor json.loads(...) ile bunu STRING olarak geri okur ve scheduled_service.apply_entry_update içindeki genel setattr(entry, field, value) döngüsü (satır 64-70) bu string'i coerce etmeden doğrudan entry.entry_date / entry.paid_date (SQLAlchemy Date kolonu) alanına atar. credit_service._coerce_date deseninin burada karşılığı yok. Router'dan gelen normal (onaysız) çağrıda Pydantic zaten native date objesi ürettiğinden sorun görünmez — yalnızca onay-gerektiren rol için entry_date/paid_date güncellemesinde tetiklenir; bu kombinasyon test edilmemiş.

**O27. `hr.withholding` — Test kapsamı — RBAC (403 yolu, viewer_user_headers/no_perm_user_headers)**  
*Yer:* `backend/tests/test_scheduled_base.py:704-725 (class TestPermissions)`  
TestPermissions sınıfı yalnızca 'unauthenticated' (401/403, kimlik doğrulama yok) senaryolarını ve yalnızca /api/accounting/taxes prefix'ini (parametrik değil) kapsıyor. hr.withholding dahil hiçbir scheduled modül için 'view izni var ama use yok' (viewer_user_headers) veya 'hiç izin yok' (no_perm_user_headers) senaryosunda POST/PATCH/DELETE'in gerçekten 403 döndüğünü doğrulayan bir test yok. conftest.py'de bu fixture'lar mevcut (viewer_user_headers, no_perm_user_headers, make_user_with_perms) ama bu dosyada hiç kullanılmamış. require_permission() middleware'i kod okumasıyla doğru göründüğü halde, CLAUDE.md'nin açıkça istediği 'happy-path + RBAC 403 yolu' testi eksik.

**O28. `messaging (Mesajlaşma)` — Onay Akışı Entegrasyonu (check_approval) — Zorunlu / istisna gerekçesi dokümante edilmeli**  
*Yer:* `backend/app/routers/messages/conversations.py:272,448,465,531; groups.py:41,147,235,304,382; msg_operations.py:39,113,191,240`  
Modüldeki hiçbir POST/PATCH/DELETE endpoint'i check_approval() çağırmıyor ve approval_executor.py'de "messaging" için handler yok. CLAUDE.md istisnaları yalnızca "dosya yükleme, toplu işlem, eşleştirme" olarak sayar; mesajlaşma CRUD'u finansal/onay gerektiren bir akış olmadığından makul bir istisna olabilir ama bu gerekçe ne ana CLAUDE.md'de ne de docs/modules/mesajlasma.md'de yazılı — sessiz/gerekçesiz sapma olarak görünüyor. Öneri: docs/modules/mesajlasma.md'ye "messaging modülü onay akışından bilinçli olarak muaftır çünkü finansal/onay gerektiren mutasyon içermez" notu eklenmeli.

**O29. `messaging (Mesajlaşma)` — Audit log — Tüm CRUD'larda log_action zorunlu**  
*Yer:* `backend/app/routers/messages/conversations.py:448-459 (toggle_mute)`  
PATCH /conversations/{id}/mute endpoint'i bir mutasyon (kullanıcı tercihi güncelleme) olmasına rağmen log_action() çağrısı yok. Aynı dosyadaki diğer tüm mutasyonlar (create_conversation:381, delete_conversation:520) audit logluyor; mute endpoint'i bu düzenden sapıyor.

**O30. `quality.forms` — Dokümantasyon — docs/modules/<modül>.md zorunlu**  
*Yer:* `CLAUDE.md 'Mevcut Modül Dokümantasyonları' tablosu (Kalite satırı yok); backend/app/routers/quality/CLAUDE.md mevcut`  
Kalite/Formlar modülü için docs/modules/ altında ayrı bir dosya yok (ör. docs/modules/kalite.md). Yalnızca router-içi backend/app/routers/quality/CLAUDE.md var — bu 'ilgili modül-içi CLAUDE.md' şartını karşılıyor ama CLAUDE.md'nin kendi 'Modül Dokümantasyon Şablonu' + 'Mevcut Modül Dokümantasyonları' tablosu diğer tüm modüller için docs/modules/*.md dosyası şart koşuyor; Kalite bu listede yok.

**O31. `quality.forms` — Test — RBAC (403 yolu) kapsamı**  
*Yer:* `backend/tests/test_quality_module.py (tüm dosya, örn. satır 90-636)`  
Testler yalnız auth_headers (admin) + token-yok (401) senaryolarını kapsıyor (ör. satır 113-116, 261-263). viewer_user_headers/no_perm_user_headers ile 'view izni var ama use yok → 403' veya 'hiç izin yok → 403' senaryosu quality.forms için test edilmemiş. TestReopenAuthorization (satır 465-541) sadece assignee-bazlı (filler/approver) yetkiyi test ediyor, RBAC view/use ayrımını değil.

**O32. `quality.forms` — Test — onay akışı regresyon testi**  
*Yer:* `backend/tests/test_approval_system.py (quality.forms için karşılık yok; quality.templates için test_quality_template_via_approval_regression örneği var)`  
CLAUDE.md, AST testlerinin (TestExecutorImportIntegrity) payload-anahtar uyuşmazlığını/eksik yan-etkiyi yakalayamadığını, bu yüzden yeni/değişen her handler için modül-bazlı uçtan-uca onay regresyon testi gerektiğini belirtiyor. quality.forms için böyle bir test yok (quality.templates'te var). check_approval->executor zinciri (create/delete) bu nedenle regresyona karşı korunmasız.

**O33. `quality.templates` — UI Tasarım Sistemi — elle bg-teal-* buton yazma yasağı**  
*Yer:* `frontend/src/lib/components/quality/TemplateBuilder.svelte:134-141`  
"+ Bölüm Ekle" butonu ham <button class="... bg-teal-700 text-white rounded-lg hover:bg-teal-800 ..."> ile yazılmış; Button.svelte kullanılmamış. CLAUDE.md: "Elle bg-teal-* ... rounded-lg buton yazma — AA kontrast ve tutarlılık tek kaynaktan gelir." Aynı dosyada satır 164-178 (bölüm sil ✕), 257-264 (alan sil ✕), 299-305 ve 348-354 (+ Ekle atama butonları) de ham <button> + elle renk sınıfları (bg-blue-50, bg-teal-50, text-red-600 vb.) kullanıyor — hiçbiri Button bileşenine sarılmamış.

**O34. `quality.templates` — Test kapsamı — RBAC (403) testi eksik**  
*Yer:* `backend/tests/test_quality_module.py:113-116 (TestTemplateList), 143-231 (TestTemplateCRUD)`  
quality.templates için POST/PATCH/DELETE ve GET endpoint'lerinde yalnızca 401 (token yok — test_list_templates_unauthorized) testi var; can_view-only (viewer_user_headers) veya hiç izni olmayan (no_perm_user_headers) kullanıcı ile 403 senaryosu test edilmiyor. Karşılaştırma: quality.forms tarafında TestReopenAuthorization sınıfı 403 senaryosunu (atanmamış kullanıcı reopen) net test ediyor, ama templates.py'nin require_permission('quality.templates','use') koruması hiç RBAC-negative testle doğrulanmamış.

**O35. `sales.flight (Uçak Rezervasyon)` — Test kapsamı (checklist madde 11)**  
*Yer:* `backend/app/routers/sales/flights.py:39-80; backend/app/main.py:203`  
backend/tests/ altında flights.py için hiçbir test yok. Router main.py:203'te gerçekten `app.include_router(sales.router, prefix='/api/sales', ...)` ile mount edilmiş ve `/api/sales/flights/airports`, `/api/sales/flights/search` dışarıdan HTTP ile erişilebilir durumda — docs/modules/ucak-rezervasyon.md ve docs/api-haritasi.md'nin 'yedekte, kullanılmıyor' ifadesine rağmen kod canlı ve production'da çağrılabilir. En azından happy-path + RBAC (view izni olmayan kullanıcı için 403) + hata yolu (Travelpayouts hata durumunda 502) testi eksik.

**O36. `stok.depolar` — Test (RBAC — 403 yolu)**  
*Yer:* `backend/tests/test_stock.py:123-124 (test_view_requires_permission yalnizca /summary'yi test ediyor); backend/tests/test_stock.py:116-120 (test_depots_with_consumption yalnizca auth_headers/admin ile)`  
stok.depolar modulunun kendi endpoint'i olan GET /stok/depots icin no_perm_user_headers ile 403 testi yok. Modulun RBAC kontrolu router seviyesinde dogru uygulanmis (require_permission("stok.depolar","view"), routers/stock.py:423) ancak testte dogrulanmamis — CLAUDE.md 'en az happy-path + RBAC (403 yolu)' kurali bu endpoint icin eksik kapsaniyor. Diger stok endpoint'leri (/summary) icin 403 testi var, /depots icin yok.

**O37. `stok.hareketler` — Test kapsamı — RBAC (403 yolu)**  
*Yer:* `backend/tests/test_stock.py:123-125`  
`test_view_requires_permission` yalnızca `stok.maliyet` alt-modülüne bağlı `/summary` endpoint'i için 403 kontrolü yapıyor. `stok.hareketler` (list_movements, backend/app/routers/stock.py:378-381) ve `stok.urunler`/`stok.depolar` için ayrı izin-yok (`no_perm_user_headers`) veya salt-view (`viewer_user_headers` ile use gerektiren yerde 403) testi yok. Modül 4 ayrı izin koduna (`stok.maliyet`, `stok.urunler`, `stok.hareketler`, `stok.depolar`) bölündüğünden her biri bağımsız test edilmeli; şu an tek testte varsayım genellemesi yapılıyor.

**O38. `stok.urunler` — Test kapsamı — RBAC (madde 11)**  
*Yer:* `backend/tests/test_stock.py (tüm dosya, özellikle 123-124. satır)`  
`stok.urunler` modülüne özgü `/api/stok/products` endpoint'i için ayrı bir 403 (yetkisiz erişim) testi yok. Dosyadaki tek RBAC testi `test_view_requires_permission` yalnızca `/summary` (stok.maliyet) endpoint'ini kontrol ediyor. `test_products_filter` (satır 95-103) yalnızca admin (`auth_headers`) ile happy-path'i test ediyor; `no_perm_user_headers`/`viewer_user_headers` ile `stok.urunler` izninin ayrı çalıştığını doğrulayan bir test yok. Aynı durum `stok.hareketler` (`/movements`) ve `stok.depolar` (`/depots`) için de geçerli — CLAUDE.md madde 11 her modül için happy-path + RBAC testi ister. Önerilen düzeltme: `test_stock.py` içine `stok.urunler`, `stok.hareketler`, `stok.depolar` izin kodlarına özel en az birer 403 testi eklenmeli (ör. `no_perm_user_headers` ile `/products`, `/movements`, `/depots` çağrılarının 403 döndüğünü doğrulayan testler).

**O39. `system.approval` — UI tasarım sistemi — modül kodu tutarlılığı (hasPermission)**  
*Yer:* `frontend/src/routes/dashboard/sistem/onay-akisi/+page.svelte:115`  
let canUse = hasPermission('system', 'use'); — diğer tüm sistem alt-sayfaları (roller, kullanicilar, moduller, hata-loglar, sunucu, yedekleme) kendi tam modül koduyla kontrol ediyor (ör. hasPermission('system.roles','use'), hasPermission('system.users','use')). onay-akisi sayfası tek başına üst-modül 'system' kodunu kullanıyor. Sonuç: system üst modülüne 'use' izni olan ama system.approval alt-modülüne özel 'use' izni OLMAYAN bir rol, backend 403 dönmesine rağmen (require_permission('system.approval','use') doğru kullanılıyor) frontend'de 'Yeni Tanım'/'Düzenle'/'Sil'/'Onayla'/'Reddet' butonlarını görüp tıklayacak ve sonra 403 toast'ı ile karşılaşacak — kullanılabilirlik sapması ve modüller-arası tutarlılık ilkesine aykırı. Düzeltme: hasPermission('system.approval', 'use') olmalı.

**O40. `system.audit_logs` — Dokümantasyon güncelliği (madde 10)**  
*Yer:* `docs/modules/audit-log.md:34 (CLAUDE.md:475 ile karşılaştır) vs backend/app/routers/audit.py:18-24`  
docs/modules/audit-log.md, endpoint'in "Paginated + filtrelenebilir (action, entity_type, user_id, start_date, end_date)" olduğunu yazıyor. Router'da (list_audit_logs, satır 18-24) yalnızca page, page_size, action, entity_type, user_id parametreleri tanımlı — start_date/end_date kodda yok. Dokümante edilip kodda olmayan (hayalet) parametre örneği; doküman güncellenmeli ya da özellik eklenmeli.

**O41. `system.error_logs` — Audit log — log_action çağrısı**  
*Yer:* `backend/app/routers/error_logs.py:78-107`  
Tekli silme (delete_error_log) ve toplu temizleme (clear_error_logs) endpoint'leri gerçek DB mutasyonu (silme) yapıyor ama hiçbirinde log_action(db, user_id, "delete", "error_log", ...) çağrısı yok. CLAUDE.md: 'Tüm CRUD işlemleri ve giriş/çıkış olayları audit_logs tablosuna kaydedilir.' Kim, kaç kayıt sildi bilgisi audit trail'de yer almıyor — özellikle 'Tümünü Temizle' geri alınamaz bir operasyon olduğundan iz bırakılması önemli.

**O42. `system.error_logs` — Test kapsamı — RBAC (403/viewer) testi eksik**  
*Yer:* `backend/tests/test_error_logs.py:37-52`  
Testler yalnızca kimliksiz erişim (401/403) kontrolü yapıyor; `view` iznine sahip ama `use` izni olmayan bir kullanıcı (viewer_user_headers) ile DELETE denemesinin 403 döndüğünü doğrulayan test yok. CLAUDE.md test kuralı: 'en az happy-path + RBAC (403 yolu, viewer_user_headers/no_perm_user_headers)' bekler. Mevcut testler yalnız admin (auth_headers) ile happy-path'i kapsıyor, izin ayrımı (view vs use) test edilmemiş.

**O43. `system.modules` — Test kapsamı — RBAC (403) ve onay-akışı regresyon testi eksik**  
*Yer:* `backend/tests/test_system_modules.py:1-369; backend/tests/test_permissions.py:44`  
test_system_modules.py kapsamlı happy-path + hata-durumu testleri içeriyor ama tüm 'yetkisiz erişim' testleri yalnızca token'sız (401) senaryosunu kontrol ediyor (test_*_unauthorized isimli testler). CLAUDE.md 11. madde 'en az happy-path + RBAC (403 yolu, viewer_user_headers/no_perm_user_headers)' testini zorunlu kılıyor; bu modülde can_view'i olup can_use'u olmayan (veya hiç izni olmayan) bir rolün POST/PATCH/DELETE'te 403 aldığını doğrulayan test yok. Ayrıca system.modules için onay-akışı (approval workflow üzerinden 202→executor uygulanması) uçtan-uca regresyon testi de yok — test_approval_system.py içinde 'system.modules' geçmiyor (grep 0 sonuç), sadece _handle_system_modules handler'ı var.

**O44. `system.roles` — Dokümantasyon / hayalet kural**  
*Yer:* `docs/modules/sistem-roller.md:48 (karşılaştır: backend/app/services/system_service.py:88-117, backend/app/routers/system_roles.py:69-139)`  
Doküman "Admin rol korumalı: name='Admin' olan rol silinemez/düzenlenemez" diyor, ancak kodda böyle bir özel kontrol yok. update_role/apply_role_update ve delete_role içinde yalnızca genel bir guard var: role.name=="Admin" kontrolü hiçbir yerde yapılmıyor; delete_role tek kısıtlama olarak "role'e atanmış kullanıcı var mı" sayısına bakıyor (system_service.py:112-116). Admin rolünün kullanıcı ataması kaldırılırsa (ör. tüm adminler başka role taşınırsa) rol adı değiştirilebilir veya silinebilir — dokümante edilen davranışla kod arasında fark var (dokümante edilip kodda olmayan kural).

**O45. `system.roles` — Test — RBAC 403 (viewer_user_headers/no_perm_user_headers)**  
*Yer:* `backend/tests/test_system_roles.py (tüm dosya, ör. 58-96, 137-195, 204-300, 309-339) ve backend/tests/test_permissions.py:43,74`  
test_system_roles.py'deki tüm GET/POST/PATCH/DELETE testleri yalnızca auth_headers (admin) ve kimliksiz (401) senaryolarını kapsıyor. Projenin sağladığı viewer_user_headers (can_view-only) veya no_perm_user_headers (izinsiz) fixture'ları ile "giriş yapmış ama can_use'u olmayan kullanıcı 403 alır" testi system.roles için hiçbir dosyada yok (grep sonucu boş). test_permissions.py yalnızca kimliksiz 401 + admin-erişebilir senaryolarını kapsıyor, view-only/no-perm 403 senaryosu içermiyor. CLAUDE.md test kuralı "en az happy-path + RBAC (403 yolu, viewer_user_headers/no_perm_user_headers)" gerektiriyor — bu boşluk var.

**O46. `system.server (Sunucu İzleme)` — Dokümantasyon — docs/modules/*.md**  
*Yer:* `docs/modules/ (sunucu.md dosyası yok)`  
system.server modülü için docs/modules/ altında bir dokümantasyon dosyası yok. CLAUDE.md 'Mevcut Modül Dokümantasyonları' tablosunda 'Sunucu' satırı bulunmuyor, ama RBAC modül listesinde (CLAUDE.md:426) 'Sunucu (system.server)' geçiyor ve şablon (Genel Bilgi/Dosya Haritası/API/Audit/Geliştirme Kuralları) zorunlu tutuluyor. docs/api-haritasi.md:263-265'te endpoint'ler kayıtlı ama modül-özel doküman (whitelist mantığı, sudo NOPASSWD gerekliliği, onay akışı istisnası gerekçesi gibi iş kuralları) yok.

**O47. `system.users` — Test — RBAC (403 yolu, viewer_user_headers/no_perm_user_headers)**  
*Yer:* `backend/tests/test_system_users.py (tüm dosya) ve backend/tests/test_permissions.py:42,73`  
test_system_users.py içinde yalnız 401 (token yok) ve admin (yetkili) senaryoları test ediliyor. test_permissions.py da yalnız 'kimliksiz erişim' (401/403) ve 'admin erişebilir' testleri içeriyor. `can_view=True, can_use=False` (viewer_user_headers) rolüyle POST/PATCH/DELETE denendiğinde 403 döndüğünü doğrulayan hiçbir test yok — CLAUDE.md test maddesi bunu happy-path + onay akışı testinin yanında ayrıca zorunlu tutuyor.

**O48. `system.users` — Frontend/backend tutarlılığı — şifre minimum uzunluk**  
*Yer:* `frontend/src/lib/utils/validation.ts:10-15 vs backend/app/schemas/user.py:67-72,88-93`  
Frontend `validatePassword()` minimum 6 karakter kabul ediyor ('Şifre en az 6 karakter olmalıdır'), ama backend `UserCreate.password_min_length` ve `PasswordReset.password_min_length` minimum 8 karakter zorunlu kılıyor. Kullanıcı 6-7 karakterli şifre girip frontend validasyonunu geçtiğinde backend 422 ile reddediyor — kullanıcıya önce yanlış (başarılı) izlenim, sonra sunucu hatası veriliyor.

**O49. `yonetim.panel` — UI Tasarım Kuralları — Sessiz hata (frontend `.catch(() => {})` yasak)**  
*Yer:* `frontend/src/routes/dashboard/yonetim/+page.svelte:36-37`  
`api.get('/finance/cash-flow/mobile-dashboard').catch(() => ({}))` ve `api.get('/finance/krediler/upcoming-payments...').catch(() => [])` — CLAUDE.md açıkça yasaklıyor: 'Sessiz hata | `.catch(() => {})` yok (dashboard panelinde 6 adet yakalandı)' ve 'her catch → console.error + showToast'. Bu iki çağrıda hata sessizce yutuluyor; kullanıcı banka bakiyesi/kredi taksiti verisinin çekilemediğini asla öğrenemiyor, panel sanki '0/₺0' doğruymuş gibi görünüyor. Öneri: `.catch((e) => { console.error('...', e); return {}/[]; })` şeklinde en azından console.error eklenmeli; kritik olmayan opsiyonel veri olduğu için toast zorunlu tutulmayabilir ama sessiz yutma kuralı ihlal ediliyor.

### ⚪ Düşük (84)

**D1. `accounting.dividend` — Dokümantasyon tutarlılığı (madde 10)**  
*Yer:* `docs/modules/muhasebe-ik.md:14`  
Doküman 'Tüm 4 alt modül aynı CRUD pattern'ını kullandığı için' diyor ama Genel Bilgi tablosunda (satır 8) 5 muhasebe alt modülü listeleniyor (accounting.taxes, recurring, rent_income, rent_expense, dividend). dividend eklendiğinde bu cümle güncellenmemiş; küçük bir sayısal tutarsızlık, kodla çelişki yok.

**D2. `accounting.dividend` — Merkezi sabitler — WS event tipi (madde 7)**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte:531`  
onWsEvent('finance_updated', ...) literal string ile çağrılıyor; lib/constants/realtime.ts'te WS_EVENT.FINANCE_UPDATED sabiti tanımlı olmasına rağmen kullanılmıyor. onWsEvent'in WsEventType union parametresi tiplendiği için typo riski düşük, ama CLAUDE.md'nin 'sihirli string yasak, merkezi sabit kullanılır' kuralına aykırı. Not: Bu ScheduledModule.svelte ortak bileşeninden kaynaklanan proje-geneli bir sapma (9 dosyada aynı literal kullanım tespit edildi) — accounting.dividend'a özgü değil, ancak dividend sayfası da bu bileşeni kullandığı için etkileniyor.

**D3. `accounting.fis_icmali` — Test kapsamı — RBAC (madde 11)**  
*Yer:* `backend/tests/test_fis_icmali.py:109-122 (voucher-detail testleri)`  
summary endpoint'i için test_requires_view (satır 22-24) ve vouchers endpoint'i için test_vouchers_requires_view (satır 103-106) ile 403/no_perm_user_headers testi mevcut; ancak voucher-detail endpoint'i (backend/app/routers/accounting/fis_icmali.py:157-161, require_permission('accounting.fis_icmali','view') ile korunuyor) için karşılık gelen bir 403 RBAC testi eksik. Router kodu doğru korunuyor (izin kontrolü mevcut), yalnızca test kapsaması tutarsız — diğer iki GET endpoint'iyle simetri kurulmalı. Öneri: test_fis_icmali.py'ye `client.get(f"{PREFIX}/voucher-detail?rec_id=1", headers=no_perm_user_headers)` için 403 bekleyen bir test eklenmeli.

**D4. `accounting.mizan` — UI tasarım sistemi — Loading göstergesi (Skeleton, spinner değil)**  
*Yer:* `frontend/src/routes/dashboard/muhasebe/mizan/+page.svelte:280`  
Hareketler (defter) modal'ında yükleme durumu `<Loader2 class="animate-spin inline" size={20} /> Yükleniyor…` ile elle yapılmış. CLAUDE.md 'Modüller Arası Tutarlılık Standardı' tablosunda 'Inline spinner' satırı bunu açıkça yasaklıyor: 'Veri yükleme = TableSkeleton/FormSkeleton (spinner DEĞİL); buton-içi bekleme = Button loading (Loader2)'; 'Elle animate-spin div/SVG + Yükleniyor... metni YOK' deniyor. Sayfanın ana mizan tablosunda TableSkeleton doğru kullanılmışken (satır 211), aynı sayfadaki defter modal'ında tutarsızlık var. Önerilen düzeltme: txLoading durumunda TableSkeleton (örn. rows=4 columns=6) kullanılmalı, manuel spinner+metin yerine.

**D5. `accounting.rent_expense` — UI Tasarım Sistemi — Pagination bileşeni (CLAUDE.md "Zorunlu bileşenler")**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte:317`  
Liste verisi `page_size=200` sabit parametresiyle tek seferde (yıl filtresiyle) çekiliyor; `Pagination.svelte` bileşeni hiç kullanılmıyor/render edilmiyor. CLAUDE.md liste sayfaları için Pagination'ı zorunlu kılıyor. Yıllık planlı gider kaydı sayısının pratikte düşük (≤~50) olması riski azaltıyor, ama tasarım standardına resmi bir sapma.

**D6. `accounting.rent_expense` — Merkezi sabitler — kaynak-etiket haritası tekrarı (sihirli string yerine app.constants kullanım ruhu)**  
*Yer:* `backend/app/utils/entry_generator.py:21-30 (DESC_PREFIX) ve backend/app/utils/finance_event_service.py:292-301 (desc_map)`  
`source_type → Türkçe etiket` haritası ("rent_expense": "Verilen Kira" dahil) iki ayrı dosyada birebir aynı içerikle literal olarak tekrar tanımlanmış. `SourceType` sabitleri kullanılıyor olsa da etiket metinleri merkezi bir yerde toplanmamış; biri güncellenip diğeri unutulursa nakit akım açıklamaları ile finance_event açıklamaları arasında sessiz tutarsızlık oluşabilir.

**D7. `accounting.rent_expense` — UI Tasarım Sistemi — Inline spinner kuralı (CLAUDE.md tablo: "Inline spinner")**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte:1070`  
Onay Detay Modal içeriği yüklenirken `Loader2` + `animate-spin` ile elle spinner render ediliyor. CLAUDE.md standardı veri yüklemede TableSkeleton/FormSkeleton, buton-içi beklemede `Button loading` öngörüyor; modal-içi küçük veri yüklemesi için ayrık bir istisna tanımlanmamış. Etkisi çok sınırlı (küçük onay-detay modalı) ama harfiyen standarda uymuyor.

**D8. `accounting.rent_income` — Test — Onay akışı modül-regresyonu**  
*Yer:* `backend/tests/test_approval_system.py:766 (test_scheduled_salary_create_via_approval) — accounting.rent_income için karşılığı yok`  
8 scheduled modülü tek ortak executor handler'ı (_handle_scheduled) ve ortak service (scheduled_service) kullanıyor; approval-executor uçtan-uca regresyon testi yalnızca hr.salary örneğiyle yazılmış. accounting.rent_income'a özgü direction=+1 (gelir yönü, finance_events'e INCOME olarak yazılması) onay-executor akışında ayrıca doğrulanmıyor. Ortak kod olduğundan kritik değil ama CLAUDE.md yeni/farklı-davranışlı handler için modül-bazlı regresyon testini teşvik ediyor. Öneri: rent_income create/update akışı için direction=+1'i doğrulayan kısa bir regresyon testi eklenebilir (opsiyonel, düşük risk).

**D9. `accounting.rent_income` — Merkezi Sabitler — WS event tipi literal**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte:531`  
onWsEvent('finance_updated', ...) literal string kullanıyor; lib/constants/realtime.ts içindeki WS_EVENT.FINANCE_UPDATED sabiti import edilip kullanılmıyor. Kanonik referans finans/avanslar:263 ve nakit-akim:365 sayfaları da aynı deseni kullandığından proje-genelinde yaygın bir tutarsızlık — rent_income'a özgü değil, ScheduledModule ortak bileşenine ait (8 modülü etkiler). onWsEvent zaten WsEventType union ile tipli olduğundan typo riski düşük; sadece stil tutarlılığı sorunu. Öneri: ScheduledModule.svelte içinde 'finance_updated' yerine WS_EVENT.FINANCE_UPDATED kullanılabilir (bu denetimin kapsamı dışında, proje-geneli ayrı bir iyileştirme olarak).

**D10. `accounting.taxes` — Test — modül-bazlı uçtan-uca onay regresyon testi eksik**  
*Yer:* `backend/tests/test_approval_system.py:766-800 (yalnız hr.salary örneklendi)`  
CLAUDE.md, AST testlerinin (TestExecutorImportIntegrity) payload-anahtar uyuşmazlığı/yan-etki eksikliğini yakalayamadığını, bu yüzden yeni/paylaşılan handler'lar için modül-bazlı uçtan-uca onay regresyon testi istiyor. `_handle_scheduled` + `scheduled_service` 8 modül arasında paylaşılsa da (risk düşük), `accounting.taxes` özelinde ayrı bir onay→uygula regresyon testi yok — yalnızca `hr.salary` temsilen test edilmiş. Diğer 7 modülün (taxes dahil) davranışı yalnızca dolaylı (ortak kod + AST handler-varlık testi) güvence altında.

**D11. `accounting.taxes` — Merkezi Sabitler — WS event literal string**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte:531`  
`onWsEvent('finance_updated', ...)` literal string ile çağrılmış; CLAUDE.md merkezi sabit kuralına göre `WS_EVENT.FINANCE_UPDATED` (lib/constants/realtime.ts) kullanılmalıydı. Not: Bu ScheduledModule'e özgü değil — projede 9 dosyada aynı literal desen var, yalnızca 2 dosya sabiti kullanıyor; `WsEventType` union tipi zaten typo'yu derleme zamanında yakaladığından risk düşük, ama modül-bazlı sapma olarak not edildi.

**D12. `dashboard (Panel)` — Test kapsamı (CLAUDE.md Test Sistemi bölümü)**  
*Yer:* `frontend/src/routes/dashboard/+page.svelte (test dosyası yok)`  
Panel sayfası (+page.svelte) için component/unit test bulunmuyor. Sayfa; izin bazlı kart görünürlüğü (canBanks/canChecks/canCredits/canAdvances/canCariler), fmt() para formatlama ve cardError/toplu-toast hata mantığı gibi test edilebilir saf mantık içeriyor ancak test edilmemiş. Diğer modüllerin çoğu (finance.ts, paymentMethods.ts, MoneyInput vb.) Vitest testine sahipken bu sayfanın hiç testi yok.

**D13. `dashboard (Panel)` — Merkezi Sabitler (WS event tipi literal yazılmaması)**  
*Yer:* `frontend/src/routes/dashboard/+layout.svelte:50,58,63,76,83`  
onWsEvent('connected', ...), onWsEvent('permission_changed', ...), onWsEvent('bank_statement_uploaded', ...), onWsEvent('force_logout', ...), onWsEvent('session_expired', ...) çağrıları event tipini literal string olarak yazıyor; CLAUDE.md 'Merkezi Sabitler' kuralı bunların lib/constants/realtime.ts içindeki WS_EVENT sabitinden (ör. WS_EVENT.CONNECTED, WS_EVENT.PERMISSION_CHANGED) kullanılmasını şart koşuyor — dosya bu sabitleri zaten tanımlıyor (realtime.ts:21,25,28-30). Not: proje genelinde yaygın bir sapma (18 dosyada literal kullanım, sadece 2 dosyada WS_EVENT. kullanımı: devam-takip ve vardiya-cizelgesi) — dashboard'a özgü değil ama modül kapsamında kanıt olarak mevcut.

**D14. `finance.avanslar` — Dokümantasyon — docs/modules/<modül>.md güncel olmalı, koddaki her endpoint dokümante edilmeli**  
*Yer:* `docs/modules/avanslar.md:49-58 (API Endpoint'leri tablosu) vs backend/app/routers/finance/advances.py:303-368`  
GET /avanslar/sedna-reconciliation endpoint'i kodda mevcut (Sedna 340 hesap mutabakatı, frontend'de 'Sedna Mutabakatı' butonuyla kullanılıyor) ama docs/modules/avanslar.md'nin API tablosunda listelenmemiş — dokümansız endpoint. Ayrıca _match_account yardımcı fonksiyonu ve Sedna mutabakat iş kuralı (isim+para birimi eşleştirme skoru) dokümana hiç yansımamış.

**D15. `finance.avanslar` — Test — happy-path + RBAC (403 yolu, viewer_user_headers/no_perm_user_headers) + onay akışı testi**  
*Yer:* `backend/tests/test_advances.py (tüm dosya)`  
test_advances.py yalnızca auth_headers (admin) ile happy-path senaryolarını kapsıyor; finance.avanslar için viewer_user_headers/no_perm_user_headers ile 403 döndüğünü doğrulayan bir RBAC testi bu dosyada yok. tests/test_permissions.py da sadece GET /avanslar/ (view) rotasını genel taramada kontrol ediyor, POST/PATCH/DELETE/match için izinsiz erişim testi yok. Not: onay akışı regresyon testleri tests/test_approval_system.py içinde finance.avanslar için mevcut ve iyi durumda (create/update/delete uçtan-uca onay+executor doğrulaması var) — eksik olan yalnızca saf RBAC 403 kapsamı.

**D16. `finance.avanslar` — Dosya-içi düzen / kod temizliği — kullanılmayan import olmamalı**  
*Yer:* `backend/app/routers/finance/advances.py:4`  
`import re` dosyada bulunuyor ancak hiçbir yerde kullanılmıyor (grep ile 're.' çağrısı yok). Ölü import; lint/temizlik açısından kaldırılmalı.

**D17. `finance.banks` — Onay akışı — istisna listesi netliği (dosya yükleme/toplu işlem/eşleştirme hariç tutulabilir)**  
*Yer:* `backend/app/routers/finance/banks.py:351-419 (create_manual_transaction)`  
Manuel (ekstre-dışı) banka hareketi ekleme endpoint'i check_approval çağırmıyor; kod içi yorumda 'Operasyonel düzeltme endpoint'i (dosya yükleme/eşleştirme gibi) — onay akışından muaf' gerekçesi var (satır 364) ve bu gerekçe finans/CLAUDE.md'de de belgelenmiş. Ancak CLAUDE.md ana dosyasındaki açık istisna listesi yalnız 'dosya yükleme, toplu işlem, eşleştirme' sayıyor — 'manuel para hareketi oluşturma' (yeni bir BankTransaction + finance_event insert eden gerçek bir mutasyon) bu üç kategoriye tam oturmuyor. Gerekçe modül CLAUDE.md'sinde var olsa da ana kuralın istisna listesinde yer almaması gri alan yaratıyor; onay akışı bilinçli atlanan her mutasyon için ana listeye de bir madde eklenmesi (veya gerekçenin ana CLAUDE.md'de referanslanması) daha sağlam olur.

**D18. `finance.banks` — UI tasarım sistemi — inline spinner yasak (Button loading dışında animate-spin kullanılmaz)**  
*Yer:* `frontend/src/routes/dashboard/finans/bankalar/+page.svelte:510-516`  
Dosya yükleme sırasında FileDropzone üzerine kaplanan overlay'de elle `<Loader2 size={20} class="animate-spin" />` + 'Yükleniyor...' metni kullanılmış. CLAUDE.md 'Inline spinner' kuralı: 'Elle animate-spin div/SVG + Yükleniyor... YOK — buton-içi bekleme = Button loading (Loader2)'. Burada Button loading kullanılamayacak bir overlay senaryosu olsa da (FileDropzone kendi durumunu yönetiyor), aynı desenin dosyada tekrarı standarttan sapma sayılır; TableSkeleton/Skeleton yerine spinner tercih edilmiş.

**D19. `finance.banks` — Test — RBAC (403 yolu) her mutasyon endpoint'i için doğrudan test edilmeli**  
*Yer:* `backend/tests/test_finance.py:176-260 (TestBankAccounts) ve backend/tests/test_permissions.py:13-50`  
test_permissions.py yalnız GET /api/finance/banks/accounts/ için kimliksiz-erişim (401/403) testi içeriyor; TestBankAccounts sınıfında create/update/delete/upload endpoint'leri için viewer_user_headers veya no_perm_user_headers ile açık bir 403 testi yok (yalnız happy-path auth_headers testleri var). test_bank_manual_transaction.py'de manual-transaction için 'use' izni testi (test_manual_tx_requires_use) mevcut — ama hesap CRUD (POST/PATCH/DELETE /accounts/) ve upload endpoint'lerinde eşdeğer bir RBAC testi eksik; salt-200 yüzeysel test riskine kısmen giriyor.

**D20. `finance.butce` — UI tasarım sistemi — StatCard yerine özel kart**  
*Yer:* `frontend/src/routes/dashboard/finans/butce/+page.svelte:403-469`  
Departman özet kartları ("Gelir/Gider/Net Durum") StatCard bileşeni yerine elle yazılmış `<button class="bg-white rounded-xl border...">` bloklarıdır — ikon-accent yok, kanonik StatCard şablonuna uymuyor. CLAUDE.md tablosunda 'Özet kart: TEK standart StatCard bileşeni... inline custom kart YOK' kuralı bütçeyi de kapsıyor (bilinçli istisnalar listesinde bütçe yok); ancak burada kartın aynı zamanda tıklanabilir navigasyon (departman seçimi) olması nedeniyle StatCard'ın doğrudan yeniden kullanımı biraz zorlanabilir — yine de sapma olarak not edilmeli.

**D21. `finance.butce` — Dokümantasyon — kod ile uyuşmayan tablo referansı**  
*Yer:* `docs/modules/butce.md:85-86`  
Doküman 'Bütçe kaydında veya faturada kullanılan kategori silinemez... budgets ve invoices tablolarında kullanım kontrolü yapılır' diyor. Gerçek kodda (butce.py:172-180) ikinci kontrol `invoices` tablosuna değil `vendor_transactions.budget_category_id` kolonuna karşı yapılıyor — 'invoices' adında bir tablo/model proje şemasında yok. Doküman güncel değil / yanlış terim kullanıyor, geliştiriciyi yanıltabilir.

**D22. `finance.cariler` — Merkezi Sabitler — sihirli string**  
*Yer:* `backend/app/routers/finance/cariler/uploads.py:101,370,441,463`  
FinanceEvent.source_type filtresi ve finance_event_svc.invalidate() çağrılarında literal "vendor_payment" string'i kullanılıyor; app/constants.py içinde SourceType.VENDOR_PAYMENT (SOURCE_VENDOR re-export) zaten tanımlı ve finance_event_service.py bunu kendi içinde kullanıyor. cariler/uploads.py bu merkezi sabiti import edip kullanmalı (örn. `from app.constants import SourceType` → `SourceType.VENDOR_PAYMENT`).

**D23. `finance.cariler` — Dokümantasyon — dosya haritası güncel değil**  
*Yer:* `docs/modules/cariler.md:22 (Dosya Haritası tablosu)`  
Doküman `backend/app/routers/finance/cariler.py` tek dosya olarak listeliyor; gerçekte bu bir paket (backend/app/routers/finance/cariler/__init__.py + uploads.py + vendors.py + payment_schedule.py + matching.py + sedna_import.py + bank_accounts.py). Ayrıca app/models/vendor_bank_account.py, app/models/payment_instruction.py, app/routers/finance/payment_instructions.py, app/services/vendor_service.py dosya haritasında hiç geçmiyor (Ödeme Talimatı ve Banka/IBAN bölümleri metinde var ama tablo güncellenmemiş).

**D24. `finance.cariler` — Onay Akışı — executor handler kapsam notu**  
*Yer:* `backend/app/utils/approval_executor.py:412-422 (_handle_finance_cariler)`  
Handler yalnızca action_type == 'update' işliyor (vendor_service.apply_vendor_update çağırıyor) — bu doğru çünkü router tarafında finance.cariler için yalnız payment-days/status PATCH'leri check_approval'a giriyor (entity_id=vendor_id, action='update'). Router ile executor birebir uyumlu, ortak service kullanılıyor (D1-2 deseni) — bu iyi bir bulgu, sorun değil, sadece doğrulama notu olarak eklendi.

**D25. `finance.cash_flow` — test**  
*Yer:* `test:1`  
test

**D26. `finance.checks` — Merkezi sabitler (sihirli string yasak)**  
*Yer:* `backend/app/routers/finance/check_import.py:363`  
`finance_event_svc.invalidate(db, "check", d.id)` çağrısında source_type literal `"check"` string olarak yazılmış; aynı dosyada satır 190'da doğru şekilde `SourceType.CHECK` sabiti kullanılıyor. Aynı dosya içinde tutarsız kullanım — CLAUDE.md'nin 'sihirli string yasak' kuralına küçük bir aykırılık.

**D27. `finance.checks` — Test kapsamı — happy-path durum güncelleme**  
*Yer:* `backend/tests/test_checks.py:95-101 (TestCheckStatus)`  
`PATCH /{check_id}/status` için tek test `test_status_update_not_found` (404 yolu) — gerçek pending→paid veya pending→cancelled (iptal kademesi: match_number/bank_transaction_id temizliği) happy-path senaryosu doğrudan bu endpoint üzerinden (onaysız/admin akışıyla) test_checks.py'de yok. Bu senaryolar yalnızca test_approval_system.py'deki onay-akışı regresyon testleriyle (approval devrede) dolaylı kapsanıyor; admin (approval muaf) akışında check_service.apply_check_status'un iptal kademesini doğru uyguladığını gösteren doğrudan bir test_checks.py testi eksik.

**D28. `finance.checks` — UI tasarım sistemi — Pagination**  
*Yer:* `frontend/src/routes/dashboard/finans/cekler/+page.svelte:178`  
`loadChecks()` `page_size=500` ile listeyi tek seferde çekiyor ve `Pagination` bileşeni hiç kullanılmıyor (client-side aylık gruplama + filtreleme yapılıyor). CLAUDE.md 'Bilinçli İstisnalar' listesinde bu sayfa açıkça anılmıyor; 500 sınırı üstünde çek birikirse (ör. çok yıllık veri) sessiz kesilme riski var, kullanıcıya truncation uyarısı da yok (nakit-akım sayfasındaki 2000+ uyarı desenine kıyasla eksik).

**D29. `finance.doviz` — UI Tasarım Sistemi — Inline spinner yasağı**  
*Yer:* `frontend/src/routes/dashboard/finans/doviz/+page.svelte:252, 341`  
Sayfa yükleme ve grafik yükleme durumunda elle `<Loader2 class="animate-spin">` kullanılmış. CLAUDE.md 'Modüller Arası Tutarlılık Standardı' tablosunda 'Inline spinner' kuralı: veri yükleme = TableSkeleton/FormSkeleton, elle animate-spin div/SVG yasak. Sayfa zaten TableSkeleton'ı tarihçe tablosunda kullanıyor (satır 452) ama üst-seviye ilk yükleme ve grafik yüklemesinde spinner'a dönülmüş. Döviz sayfası CLAUDE.md'de StatCard/EmptyState'ten muaf tutulmuş 'bilinçli istisna' listesinde ama bu istisna spinner kuralını kapsamıyor (istisna metni yalnızca StatCard/EmptyState'i sayıyor, Pagination/Skeleton'ın uygulanması gerektiğini özellikle belirtiyor).

**D30. `finance.doviz` — UI Tasarım Sistemi — teal tonu (700 olmalı, 600 değil)**  
*Yer:* `frontend/src/routes/dashboard/finans/doviz/+page.svelte:252, 341, 422`  
`text-teal-600` (spinner) ve `bg-teal-600` (grafik lejant çizgisi) kullanılmış. CLAUDE.md kuralı: dolu zemin/metin için teal-600 değil teal-700 (AA kontrast, 600 ≈ 3.8:1 → AA-fail). Grafik lejantındaki teal-600 çizgi CLAUDE.md'nin 'Bilinçli İstisnalar' bölümünde 'döviz grafik lejantındaki teal-600 çizgi (grafik rengiyle eşleşir)' olarak açıkça muaf tutulmuş — bu kısım sorun değil. Ancak spinner'daki `text-teal-600` (satır 252, 341) bu istisna kapsamında değil; metin/ikon rengi olarak AA kontrastı ihlal edebilir, teal-700 kullanılmalı.

**D31. `finance.doviz` — Dokümantasyon tutarlılığı — küçük eksiklik**  
*Yer:* `docs/modules/doviz.md:131-137 (Geliştirme Kuralları)`  
Dokümantasyon 'can_use izni bu modülde gerekmez' diyor ama onay akışı (check_approval) muafiyetinin gerekçesi (mutasyon endpoint'i hiç yok, dolayısıyla onay akışı kavramının bu modülde uygulanamaz olduğu) doküman içinde açıkça yazılmamış. CLAUDE.md'nin ana denetim maddesi 2 gereği salt-okunur modüllerde bu muafiyetin gerekçesinin modül dokümanında da belirtilmesi tutarlılık açısından faydalı olur (küçük/kozmetik, engelleyici değil).

**D32. `finance.krediler` — Merkezi sabitler (sihirli string yasak) — frontend WS event tipi literal yazılmamalı**  
*Yer:* `frontend/src/routes/dashboard/finans/krediler/+page.svelte:782`  
onWsEvent('finance_updated', ...) literal string ile çağrılıyor; lib/constants/realtime.ts içinde WS_EVENT.FINANCE_UPDATED sabiti tanımlı olduğu halde kullanılmıyor. Not: bu krediler'e özgü değil — finans altındaki 8 sayfanın tamamında aynı literal-string deseni var (proje-geneli tutarlı sapma), modüle özel bir gerileme değil.

**D33. `finance.krediler` — UI tasarım sistemi — ikincil metin/hint en açık ton text-gray-500 olmalı**  
*Yer:* `frontend/src/routes/dashboard/finans/krediler/+page.svelte:842,862,868,874,1578`  
text-gray-400 kullanımı (banka-bazlı zaman çizelgesi kartındaki 'Toplam'/tarih etiketleri, KMH 'Vadesiz · rotatif' notu, ödeme planı popup 'Kalan' etiketi). CLAUDE.md kuralı text-gray-400/300'ü gövde metninde AA-fail olarak yasaklıyor; burada çok küçük (text-[9px]/[10px]) yardımcı etiketler olsa da kural istisna tanımlamıyor — text-gray-500'e çekilmesi önerilir.

**D34. `finance.krediler` — Hata yönetimi — her catch console.error + gerekirse showToast içermeli**  
*Yer:* `frontend/src/routes/dashboard/finans/krediler/+page.svelte:318-320 (loadData ana catch), :359-361 (toggleExpand catch), :370-373 (loadCCStatements catch)`  
Bu catch bloklarında yalnızca console.error var, showToast çağrılmıyor. Sayfa ilk yüklemesi (loadData) veya kredi detay açma (toggleExpand) başarısız olursa kullanıcıya görünür bir bildirim gitmiyor, sayfa sessizce boş/eksik kalabilir. Diğer 14 yerde showToast düzgün kullanılmış; bu üç nokta tutarsız.

**D35. `finance.onay` — Merkezi Sabitler — WS event tipi literal yazılmamalı**  
*Yer:* `frontend/src/routes/dashboard/finans/onay/+page.svelte:156`  
`onWsEvent('finance_updated', ...)` literal string kullanıyor; `lib/constants/realtime.ts` içinde `WS_EVENT.FINANCE_UPDATED` sabiti mevcut olmasına rağmen import edilip kullanılmamış. CLAUDE.md: 'WS event tipleri... literal yazılmaz'. Diğer literal ('notification') için de aynı durum geçerli.

**D36. `finance.onay` — Kod tekrarı — budget_service.upsert_budget ile aynı mantığın router içinde elle tekrarı**  
*Yer:* `backend/app/routers/finance/onay.py:256-277`  
approve_transaction içindeki Budget kompozit-anahtar (department_id+budget_category_id+year+month) 'varsa güncelle yoksa oluştur' mantığı, `app/services/budget_service.py::upsert_budget` ile aynı deseni router içinde elle tekrarlıyor (davranışsal bug yok — doğru çalışıyor — ama finans modülü CLAUDE.md'sinde D1-2 notunda anlatılan 'ortak service' prensibine aykırı, ileride budget_service güncellenirse burası senkron kalmayabilir). Öneri: budget_service.upsert_budget çağrılabilir hale getirilsin (planned_amount parametresi opsiyonel/mevcut değeri koruyacak şekilde uyarlanarak).

**D37. `finance.sales_invoices` — Dokümantasyon — /advances yanıt alan adları kodla uyuşmuyor**  
*Yer:* `docs/modules/satis-faturalari.md:57 vs backend/app/routers/finance/sales_invoices.py:294-301`  
Doküman GET /sales-invoices/advances yanıtının alanlarını `total_collected` (yatırılan), `consumed`, `net_advance` (kalan) olarak tanımlıyor. Gerçek kod (_merged_advances → sales_invoice_service.py) ve router `received`, `consumed`, `remaining` alanlarını döner (bkz. sales_invoice_service.py:171-177,184-187 ve test_sales_invoices.py:106-107 `row["received"]`, `row["remaining"]`). Alan adları dokümanla kodda birebir değil — küçük ama yanıltıcı bir doküman driftı.

**D38. `hr.attendance` — test**  
*Yer:* `test:1`  
test

**D39. `hr.salary` — UI Tasarım Sistemi (madde 9) — Pagination**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte:317`  
Liste verisi `api.get(`${apiPrefix}/?year=${selectedYear}&page_size=200`)` ile sabit page_size=200 ve sayfa numarası olmadan tek seferde çekiliyor; `Pagination.svelte` bileşeni sayfada hiç import/kullanılmıyor. CLAUDE.md UI kuralı listesinde Pagination zorunlu bileşenler arasında sayılıyor. Pratikte bir yılda 200'den fazla maaş tanımı olması olası değil (aylık/yıllık periyotlarla sınırlı sayıda definition), bu yüzden risk düşük, ama kural harfiyen uygulanmıyor. Diğer 7 kardeş modül (taxes/recurring/rent/dividend/withholding/sgk) de aynı paylaşılan bileşeni kullandığından bu, hr.salary'ye özgü değil, ortak bileşen sapması.

**D40. `hr.salary` — Test kapsamı — frontend bileşen testi**  
*Yer:* `frontend/src/lib/components/ScheduledModule.svelte`  
hr.salary sayfasının kullandığı paylaşılan `ScheduledModule.svelte` bileşeni için ayrı bir Vitest dosyası yok (MEMORY/CLAUDE.md'de listelenen 22 frontend test dosyası arasında yer almıyor). Bileşen; onay akışı modal'ı, giriş güncelleme, cari senkron gibi önemli iş mantığı içeriyor ama unit test kapsamı yok. Backend tarafı (test_scheduled_base.py + test_approval_system.py) güçlü olduğu için genel risk orta-düşük.

**D41. `hr.sgk` — Onay executor fallback alan tutarlılığı (approval_executor.py — Model kwarg eksiksizliği)**  
*Yer:* `backend/app/utils/approval_executor.py:179-195 (_handle_scheduled fallback ScheduledDefinition oluşturma)`  
Fallback dalında (pasif tanım bulunamazsa) `ScheduledDefinition(...)` çağrısı `billing_offset_months` alanını set etmiyor (router'daki create_definition ise scheduled_base.py:176'da bu alanı set ediyor). hr.sgk pratikte vendor_id/billing_offset_months kullanmadığı için (yalnız 'recurring' modülünde anlamlı) etkisi düşük, ama fallback yolu (entity_id<=0 veya pasif kayıt silinmişse) tetiklenirse router davranışından sapma oluşur. Diğer scheduled modüllerde de aynı desen — hr.sgk'ye özel değil, paylaşılan kod.

**D42. `hr.shift_schedule` — UI Tasarım Sistemi — semantik renk kullanımı / AA kontrast**  
*Yer:* `frontend/src/routes/dashboard/ik/vardiya-cizelgesi/+page.svelte:282`  
"İzinli / Sil" fırça chip'i seçiliyken bg-red-600 text-white inline stil kullanıyor. CLAUDE.md mini-chip kümelerinin buton sayılmadığı istisnasını tanır, ama tehlike anlamı taşıyan kırmızı tonun teal-700 dengi 700-tonuna çekilmesi istenir; red-600 beyaz üzerinde AA metin eşiği 4.5:1'in sınırında/altında kalabilir. Diğer chip'ler (Seçim modu bg-gray-800, vardiya renk kodları) aynı deseni paylaştığından tutarlılık açısından kabul edilebilir düzeyde, kritik değil.

**D43. `hr.shift_schedule` — Test — RBAC negatif yol genişliği**  
*Yer:* `backend/tests/test_shift_schedule.py:38-48`  
İzin (403) testleri yalnızca GET (view eksik) ve POST tek-hücre (use eksik) için var; DELETE /{id}, POST /bulk ve POST /copy-week için ayrı viewer/no_perm 403 testi yok. Onay-akışı uçtan-uca regresyon testleri (test_approval_system.py::test_shift_schedule_assign_via_approval ve _delete_via_approval) zaten mevcut olduğundan kritik bir boşluk değil; CLAUDE.md'nin RBAC kapsamı maddesine tam uyum için bulk/copy-week/delete'e de 403 testi eklenmesi faydalı olur.

**D44. `hr.shifts` — Hata Yakalama — toast bildirimi**  
*Yer:* `frontend/src/routes/dashboard/ik/vardiyalar/+page.svelte:51-60`  
load() fonksiyonundaki catch bloğu yalnızca console.error('Vardiyalar alınamadı:', e) çağırıyor; kullanıcıya showToast ile bildirim yok. CLAUDE.md kuralı: 'her catch bloğunda console.error ve gerekirse kullanıcı bildirimi olmalıdır'. save/doDelete fonksiyonlarında showToast doğru kullanılmış, yalnızca load() eksik kalmış — sayfa veri çekme hatasında sessizce boş liste gösterebilir.

**D45. `hr.shifts` — Dokümantasyon — Test bölümü eksik**  
*Yer:* `docs/modules/vardiyalar.md:1-58 (hr.shifts bölümü)`  
hr.shifts bölümünde 'Test' alt başlığı yok; aynı dosyada hr.shift_schedule bölümünde (satır 130-133) test dosyası ve kapsamı belgelenmiş. backend/tests/test_shifts.py aslında kapsamlı (izin geçitleri, CRUD, gece/split hesabı, 404, onay regresyonu) ama dokümanda bu referans eksik — modül dokümantasyon şablonunun 'Geliştirme Kuralları/Test' beklentisiyle küçük bir tutarsızlık.

**D46. `hr.withholding` — Test — modül-bazlı uçtan-uca onay regresyon testi (hr.withholding için)**  
*Yer:* `backend/tests/test_approval_system.py:766 (yalnızca test_scheduled_salary_create_via_approval mevcut)`  
8 scheduled modülün paylaştığı _handle_scheduled handler'ı için yalnızca hr.salary üzerinden bir create-via-approval regresyon testi var. hr.withholding (ve hr.sgk, diğer accounting.* modülleri) için ayrı bir regresyon testi yok — handler ortak olduğundan pratik risk düşük, ama CLAUDE.md 'yeni handler için modül-bazlı uçtan-uca onay regresyon testi de eklenmeli' ilkesine tam uyulmamış (paylaşılan handler olduğundan tek modül testi asgari kanıt sayılabilir).

**D47. `messaging (Mesajlaşma)` — UI Tasarım Sistemi — Lucide ikon zorunlu, emoji-as-icon yasak**  
*Yer:* `frontend/src/lib/components/messaging/MessageInput.svelte:206`  
Ek menüsündeki "Emoji" seçeneği ikon olarak doğrudan 😊 karakteri kullanıyor; aynı menüdeki "Dosya" (satır 202) ve "Kamera" (satır 210) seçenekleri inline SVG kullanıyor. Bu hem "emoji-as-icon yasak" kuralına hem de menü-içi tutarlılığa aykırı bir küçük sapma (mesajlaşma sayfası kanonik iskelete uymayan bilinçli istisna sayfası olsa da Lucide/emoji kuralından muaf değildir).

**D48. `messaging (Mesajlaşma)` — Dokümantasyon güncelliği — docs/modules/mesajlasma.md dosya haritası ve endpoint listesi**  
*Yer:* `docs/modules/mesajlasma.md:11-19,27-37; docs/api-haritasi.md:24-33`  
Doküman "Router: conversations.py, messages.py, users.py, read.py" diyor ancak gerçek dosyalar conversations.py, groups.py, msg_operations.py, users.py, _helpers.py (messages.py/read.py yok, groups.py/msg_operations.py dokümante edilmemiş). API endpoint tablosu da eksik: POST /conversations/group, POST/DELETE/PATCH /conversations/{id}/members(...), PATCH /conversations/{id}/admins/{user_id}, PATCH /conversations/{id}/name, POST /conversations/{id}/upload, GET /conversations/{id}/search, GET /online, PATCH /conversations/{id}/mute hiçbiri listede yok. Kodda var, dokümanda yok — dokümansız endpoint durumu.

**D49. `messaging (Mesajlaşma)` — Hassas veri hijyeni — dokümanda düz metin test kullanıcı şifresi**  
*Yer:* `frontend/src/routes/dashboard/mesajlasma/CLAUDE.md:225-286`  
Modül-içi CLAUDE.md 55 test kullanıcısının kullanıcı adı + düz metin şifresini (testuser123, admin123) tablo halinde barındırıyor; bu dosya git'e commit ediliyor. Prod şifresi olmasa da düz metin kimlik bilgisi barındırma alışkanlığı riskli; ayrı bir test-fixture dokümanına/scriptine taşınması önerilir.

**D50. `quality.templates` — UI Tasarım Sistemi — Lucide ikon zorunluluğu (emoji/karakter-as-icon yasak)**  
*Yer:* `frontend/src/lib/components/quality/TemplateBuilder.svelte:153-154,177,264,337,386`  
Yön/silme aksiyonları için Lucide ikon yerine düz Unicode karakterler (▲ ▼ ✕) kullanılmış. CLAUDE.md "emoji/inline SVG yasak — yalnız Lucide" kuralına tam uymuyor (bunlar emoji değil ama ikon-kütüphanesi dışı karakter simgeler); satır-aksiyonu istisnası bu düzeyde kabul edilebilir ama tutarlılık için ChevronUp/ChevronDown/X (lucide-svelte) tercih edilmeliydi — sayfanın kendisi (+page.svelte) zaten Pencil/Trash2/X kullanıyor, TemplateBuilder tutarsız kalıyor.

**D51. `quality.templates` — Dokümantasyon — docs/modules/ altında modül dosyası + ana CLAUDE.md tablosu eksik**  
*Yer:* `docs/modules/ (kalite.md yok); CLAUDE.md "Mevcut Modül Dokümantasyonları" tablosu (satır ~520-560 civarı)`  
Diğer tüm modüllerin (avanslar, krediler, oda-tipleri, vb.) docs/modules/<modül>.md dosyası ve ana CLAUDE.md'nin dokümantasyon tablosunda satırı var; Kalite/Şablonlar için böyle bir docs/modules/kalite.md yok ve ana CLAUDE.md tablosunda 'Kalite' satırı bulunmuyor. Mevcut olan tek doküman backend/app/routers/quality/CLAUDE.md (modül-içi) — iyi durumda ve güncel, ancak CLAUDE.md şablonunun öngördüğü docs/modules/ eşleniği eksik.

**D52. `quality.templates` — Dokümantasyon — logo yükleme/silme endpoint'leri dokümante edilmemiş**  
*Yer:* `backend/app/routers/quality/templates.py:399-495 (POST/DELETE /templates/{id}/logo); docs/api-haritasi.md:246-251; backend/app/routers/quality/CLAUDE.md:73-78`  
POST /api/quality/templates/{id}/logo ve DELETE /api/quality/templates/{id}/logo endpoint'leri kodda mevcut ve çalışıyor (require_permission + audit log dahil) ancak ne docs/api-haritasi.md'de ne de modül-içi CLAUDE.md'nin 'API Endpoints > Şablonlar' listesinde yer alıyor — dokümante edilmemiş ('gölge') endpoint.

**D53. `quality.templates` — Onay akışı — logo mutasyon endpoint'lerinde check_approval çağrılmıyor (gerekçe zayıf)**  
*Yer:* `backend/app/routers/quality/templates.py:399-460 (upload_template_logo), 466-495 (delete_template_logo)`  
CLAUDE.md 'dosya yükleme... özel endpoint hariç tutulabilir' istisnasına dayanarak upload_template_logo check_approval'dan muaf tutulmuş — bu makul. Ancak delete_template_logo bir dosya yükleme değil, template.logo_filename alanını None yapan düz bir state mutasyonudur (PATCH template ile eşdeğer); check_approval çağrılmaması için ayrı bir gerekçe kodda/dokümanda belirtilmemiş. Etkisi düşük (logo kritik onay gerektiren bir alan değil) ama kural harfiyen uygulanmamış.

**D54. `sales.flight (Uçak Rezervasyon)` — Onay akışı — POST endpoint istisna gerekçesi netliği (checklist madde 2)**  
*Yer:* `backend/app/routers/sales/flights.py:53-56`  
`POST /search` bir HTTP POST endpoint'i olduğu için CLAUDE.md'nin 'Tüm POST/PATCH/DELETE check_approval()'dan geçmeli' kuralına literal bakıldığında istisna gibi görünüyor. İnceleme sonucu bunun DB'ye hiçbir yazma yapmayan salt-okunur arama proxy'si olduğu doğrulandı (dosya yükleme/eşleştirme gibi 'özel amaçlı read-only' kategorisine benzer); onay/audit gerektirmemesi teknik olarak doğru ancak router dosyasında veya backend/app/routers/sales/CLAUDE.md'de bu istisnanın gerekçesi açıkça yazılı değil.

**D55. `sales.hotel_reservation (Otel Rezervasyon)` — İzin sistemi — GET endpoint'lerinin 'view' ile korunması**  
*Yer:* `backend/app/routers/sales/reservations/sedna_import.py:34-37`  
`GET /reservations/sedna-status` yalnızca `get_current_user` ile korunuyor (herhangi bir oturum açmış kullanıcı erişebilir), `require_permission("sales.hotel_reservation","view")` değil. Kardeş modüllerde tutarsız bir kalıp var: `finance/checks.py:170` ve `finance/cariler/sedna_import.py:56` aynı tarz status endpoint'inde `require_permission(view)` kullanırken, `stock.py`, `accounting/mizan.py`, `accounting/fis_icmali.py` ve bu modül `get_current_user` kullanıyor. Sızdırılan tek bilgi bir boolean (`configured`) olduğundan risk düşük, ama CLAUDE.md 'her GET view ile korunsun' kuralına harfiyen aykırı ve modüller arası tutarsız.

**D56. `sales.hotel_reservation (Otel Rezervasyon)` — UI tasarım sistemi — EmptyState kullanımı**  
*Yer:* `frontend/src/lib/components/sales/otel-rezervasyon/UploadsHistoryModal.svelte:32`  
Boş durum düz metinle gösteriliyor (`<p class="text-sm text-gray-500 text-center py-6">Henüz yükleme yok.</p>`), `EmptyState.svelte` bileşeni kullanılmamış. CLAUDE.md 'Boş durum: EmptyState.svelte — ikon + mesaj + CTA' kuralına aykırı; ana sayfa (`+page.svelte:923`) bu kuralı doğru uyguluyor, modal içindeki küçük tablo atlanmış.

**D57. `sales.hotel_reservation (Otel Rezervasyon)` — Erişilebilirlik — ikon-only buton aria-label**  
*Yer:* `frontend/src/lib/components/sales/otel-rezervasyon/UploadsHistoryModal.svelte:62-68`  
Silme butonu yalnızca `title="Sil"` içeriyor, `aria-label` yok (`<button onclick={() => onDelete(u)} class="p-1.5 rounded text-red-600 hover:bg-red-50" title="Sil"><Trash2 size={14} /></button>`). CLAUDE.md 'ikon-only buton + Select'e aria-label' kuralına aykırı; kardeş modal `AgencyGroupModal.svelte:72,76` aynı türde butonlarda hem `title` hem `aria-label` kullanıyor (referans doğru uygulama). Ayrıca `p-1.5` dokunma hedefi ~30px, 44px `touch-target` sınıfı kullanılmamış.

**D58. `sales.hotel_reservation (Otel Rezervasyon)` — Dokümantasyon güncelliği**  
*Yer:* `docs/modules/otel-rezervasyon.md:194`  
Doküman 'Grupları Yönet Modal' bölümünde '✏ düzenle / 🗑 sil ikonları' yazıyor (emoji referansı), ama gerçek kod (`AgencyGroupModal.svelte:73,77`) Lucide `Settings2`/`Trash2` bileşenlerini kullanıyor — emoji yok. Doküman kodun önceki (emoji tabanlı) sürümünü yansıtıyor, güncellenmemiş.

**D59. `sales.room_types` — test**  
*Yer:* `x:1`  
test

**D60. `stok.depolar` — UI tasarim sistemi — StatCard zorunlulugu**  
*Yer:* `frontend/src/routes/dashboard/stok/depolar/+page.svelte:32-38`  
Sayfada PageHeader, EmptyState, TableSkeleton kullanilmis (dogru) ancak StatCard hic yok — CLAUDE.md kanonik iskeleti 'PageHeader > StatCard > filtre > icerik' sirasini zorunlu kiliyor. Depo sayisi/toplam tuketim gibi basit bir ozet StatCard ile ustte gosterilebilirdi. Sayfa kucuk ve sabit-listeli oldugundan (43 depo, sayfalama gerektirmiyor) bu dusuk onemde bir sapma; CLAUDE.md'deki 'Bilincli Istisnalar' listesinde stok/depolar'in StatCard'sizligi acikca yer almiyor, yalnizca amber bar rengi istisna olarak belirtiliyor (docs/api-haritasi.md:690).

**D61. `stok.hareketler` — Dokümantasyon — API kataloğu tamlığı**  
*Yer:* `docs/api-haritasi.md:360-371 / backend/app/routers/stock.py:192-344`  
`GET /stok/product-purchases/{product_id}` ve `GET /stok/product-purchases/{product_id}/pdf` endpoint'leri router'da mevcut ve `docs/modules/stok.md`'de anlatılmış, ancak ana `docs/api-haritasi.md` kataloğunda listelenmemiş (kod var, ana katalogda yok — ters-hayalet/eksik doküman girdisi).

**D62. `stok.maliyet` — Test kapsamı — RBAC (madde 11)**  
*Yer:* `backend/tests/test_stock.py:49-50, 123-124`  
RBAC testleri yalnızca `no_perm_user_headers` (hiç izin yok → 403) ile yapılmış. `viewer_user_headers` (can_view var, can_use yok) ile `POST /stok/sedna-import` çağrısının 403 dönmesi ayrıca test edilmemiş — 'view izni olan ama use izni olmayan kullanıcı mutasyona erişemez' senaryosu kapsanmıyor. Ayrıca yalnız `/summary` GET'i 403 için test edilmiş; `cost-by-department`, `monthly-trend`, `by-supplier`, `operational-kpi`, `price-variance`, `product-purchases`, `products`, `movements`, `depots` endpoint'lerinin her biri aynı `require_permission` desenini kullansa da ayrı 403 testi yok (düşük risk, aynı dependency).

**D63. `stok.maliyet` — UI tasarım sistemi — kanonik checkbox stili (madde 9 / CLAUDE.md 'Klavye/Form' ve 'checkbox accent-teal-700')**  
*Yer:* `frontend/src/routes/dashboard/stok/urunler/+page.svelte:56`  
Checkbox `class="w-4 h-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500 cursor-pointer"` kullanıyor. Kanonik referans (`sistem/kullanicilar/+page.svelte:316`) `accent-teal-700` kullanıyor. Burada hem checkbox rengi `text-teal-600` (kural: teal 600 değil 700, AA) hem focus ring `focus:ring-teal-500` (bu kısım aslında doğru — kural focus ring için teal-500 istiyor) karışık uygulanmış; `text-teal-600` kısmı düzeltilip `accent-teal-700` kalıbına çekilmeli.

**D64. `stok.urunler` — UI Tasarım Sistemi — Kontrast (AA, gövde metni text-gray-400 yasak)**  
*Yer:* `frontend/src/routes/dashboard/stok/urunler/+page.svelte:84 ve :105`  
Stok=0 durumunda `current_stock` değeri `text-gray-400` sınıfıyla gösteriliyor (`{p.current_stock > 0 ? 'text-gray-800' : 'text-gray-400'}`). Ölçüldü: gray-400 (#9ca3af) beyaz zemin üzerinde kontrast oranı ≈2.54:1 — WCAG AA eşiği olan 4.5:1'in belirgin şekilde altında. CLAUDE.md UI kuralları tablosu açıkça 'gövde metninde text-gray-300/400 (AA-fail)' der; en açık ton `text-gray-500` (≈4.83:1, AA geçer) olmalı. Önerilen düzeltme: Stok=0 durumunu vurgulamak için `text-gray-400` yerine `text-gray-500` kullanılmalı (veya anlamlıysa `StatusBadge` ile semantik gösterim tercih edilmeli).

**D65. `stok.urunler` — Dokümantasyon — merkezi API haritası tam kapsam (madde 10)**  
*Yer:* `docs/api-haritasi.md:360-372 (backend/app/routers/stock.py:192-344)`  
`GET /product-purchases/{product_id}` ve `GET /product-purchases/{product_id}/pdf` endpoint'leri kodda mevcut ve `docs/modules/stok.md` içinde (satır 51-52) doğru belgelenmiş, ama ana `docs/api-haritasi.md`'deki Stok bölümünde (360-372. satırlar) listelenmemiş — kodda olup merkezi haritada eksik ('hayalet olmayan ama eksik dokümante') iki endpoint. Önerilen düzeltme: `docs/api-haritasi.md` Stok bölümüne `GET /product-purchases/{product_id}` ve `GET /product-purchases/{product_id}/pdf` satırları eklenmeli.

**D66. `system.approval` — Onay akışı entegrasyonu — check_approval() zorunlu / bilinçli istisna gerekçesi dokümante edilmeli**  
*Yer:* `backend/app/routers/approval/workflows.py:178-298; backend/app/routers/approval/requests.py (tüm POST/PATCH/DELETE)`  
system.approval router'ının kendi CRUD'ları (workflow create/update/delete, approve/reject/return/cancel/resubmit) check_approval() çağırmıyor. Bu mantıken doğru bir istisna (onay motorunun kendisi ikinci bir onay katmanına tabi olamaz — sonsuz döngü riski), ancak CLAUDE.md'nin 'Dosya yükleme, toplu işlem, eşleştirme gibi özel endpoint'ler hariç tutulabilir' listesinde bu istisna açıkça yer almıyor. docs/modules/onay-akisi.md içinde de bu istisnanın gerekçesi yazılı değil — okuyan geliştirici eksik/unutulmuş sanabilir.

**D67. `system.approval` — Hata yakalama — boş except: pass yasak (best-effort dışında gerekçelendirilmeli)**  
*Yer:* `backend/app/routers/approval/requests.py:68-69`  
_broadcast_approval_update() içinde `except Exception: pass` kullanılıyor — WS broadcast'in best-effort olması makul bir gerekçe olsa da, aynı modüldeki approval_check.py:_broadcast_approval_created (satır 39-40) aynı best-effort broadcast için `except Exception: logger.debug(..., exc_info=True)` kullanıyor. Bu tutarsızlık; requests.py'deki sessiz pass, olası WS gönderim hatalarını (ör. manager.send_to_all_sync içindeki bir regresyon) hiçbir iz bırakmadan yutar. Öneri: approval_check.py ile aynı desene (logger.debug/exc_info) çekilmeli.

**D68. `system.audit_logs` — Frontend kod temizliği / eksik-bağlı state**  
*Yer:* `frontend/src/routes/dashboard/sistem/audit-loglar/+page.svelte:32,89,109`  
filterUserId state'i tanımlanmış, loadLogs() içinde query param olarak kullanılıyor ve resetFilters() içinde sıfırlanıyor; fakat filters() snippet'inde (satır 131-164) buna bağlı hiçbir input/select yok — kullanıcı bu filtreyi arayüzden hiç ayarlayamıyor. Backend'de test edilen user_id filtresi frontend'den erişilemez durumda; ölü/eksik-bağlı state.

**D69. `system.audit_logs` — UI Tasarım Sistemi — arama kutusu standardı**  
*Yer:* `frontend/src/routes/dashboard/sistem/audit-loglar/+page.svelte:131-164`  
CLAUDE.md kanonik filtre barı tanımında "sol: arama (debounce 300ms + çarpı-temizle)" bekleniyor; sayfada yalnızca Eylem/Varlık Tipi dropdown'ları var, serbest-metin arama yok. ListPage bileşeni search/onSearch prop'unu destekliyor ama bu sayfada kullanılmamış. Fonksiyonel eksiklik değil ama standarttan küçük bir sapma.

**D70. `system.audit_logs` — Test kapsamı — modül-özel RBAC 403 testi**  
*Yer:* `backend/tests/test_ws_push_audit.py:9-84, backend/tests/test_permissions.py:45`  
test_permissions.py PROTECTED_ENDPOINTS listesi audit-logs GET'ini yalnızca kimliksiz erişim (401/403 birleşik) için kapsıyor. test_ws_push_audit.py::TestAuditLogs happy-path + filtre testlerini kapsıyor ama viewer_user_headers/no_perm_user_headers ile modüle özel 403 (izinsiz-rol) testi yok. CLAUDE.md madde 11 'en az happy-path + RBAC (403 yolu)' istiyor; bu modülde RBAC 403 senaryosu eksik (düşük risk çünkü modül salt-view, CRUD yok).

**D71. `system.backup` — Test kapsamı (madde 11)**  
*Yer:* `backend/tests/test_system_backup.py:1-55`  
Test dosyası happy-path (status shape), RBAC 403/401 (viewer/no_perm/unauthorized) ve restore'un erken-dönüş validasyon yollarını (400 geçersiz hash, 404 bilinmeyen commit) kapsıyor — bu iyi. Ancak `run_backup`'ın gerçek başarı yolu (commit+push tetiklenmesi, `changed_files`/`committed`/`pushed` alanlarının doğru hesaplanması) ve `restore_backup`'ın geçerli-commit ileri-commit akışı (checkout+yeniden commit+push, `restored`/`redeploy_needed` alanları) hiç test edilmiyor — dosya docstring'inde bu bilinçli olarak belirtilmiş ("gerçek commit/push/checkout TETİKLENMEZ"). Bu, prod git repo'sunu testte kirletmemek için makul bir tercih, ancak `_git()` helper'ının bir test-repo fixture'ı ile mock'lanarak gerçek başarı yolunun (özellikle `restored` hesaplamasındaki `git diff --cached --quiet` returncode mantığı) doğrulanmaması bir kapsam boşluğu.

**D72. `system.backup` — UI tasarım sistemi — kontrast (madde 9)**  
*Yer:* `frontend/src/routes/dashboard/sistem/yedekleme/+page.svelte:188,200`  
İki adet `text-gray-400` kullanımı var (commit hash'i ve "mevcut" etiketi, 10-11px). CLAUDE.md kuralı gövde metninde en açık tonun `text-gray-500` olmasını, `text-gray-400/300`'ün AA-fail olarak yasak olduğunu belirtiyor. Bu iki kullanım ikincil/dekoratif meta-bilgi (mono hash, durum etiketi) olduğundan şiddetli bir ihlal değil, ancak katı okumada kural ihlalidir; `text-gray-500`'e çekilmesi tutarlılık açısından uygun olur.

**D73. `system.docs` — UI Tasarım Sistemi / Güvenlik — Genişletilebilirlik notu (kritik değil)**  
*Yer:* `backend/app/routers/system_docs.py:122-142 (_walk_source) ve docs/modules/sistem-dokumanlar.md:14`  
system.docs modülü yalnız .md dokümanlarını değil, backend/app ve frontend/src altındaki TÜM .py/.svelte/.ts/.js kaynak kodunu (≈399 dosya) 'system.docs view' iznine sahip HERKESE sunuyor. Bu bilinçli bir tasarım kararı ve dokümante edilmiş (`.env` traversal-güvenli şekilde hariç, sır yok gerekçesi belirtilmiş), path traversal testleri de (`test_raw_path_traversal_blocked`) mevcut. `system.docs` izni system.users'ı görebilen her role otomatik veriliyor (migration e3b7c9d1f2a4) — yani örn. SECRET_KEY/DB parolası gibi değerler koda gömülü DEĞİLSE risk yok, ancak ileride biri yanlışlıkla bir router'a literal secret/token yazarsa bu modül üzerinden geniş bir kullanıcı kitlesine (system.users görebilen tüm roller) ifşa olur. Öneri: kod tabanında literal secret bulunmadığını doğrulayan bir statik tarama (gitleaks/detect-secrets) CI'ye eklenmesi, bu geniş-yetkili kaynak-kod görüntüleme özelliğinin riskini yapısal olarak azaltır.

**D74. `system.error_logs` — UI tasarım sistemi — ConfirmDialog yerine elle Modal**  
*Yer:* `frontend/src/routes/dashboard/sistem/hata-loglar/+page.svelte:234-242`  
Tehlikeli aksiyon (tüm logları silme) onayı kanonik `ConfirmDialog.svelte` yerine elle yazılmış bir `Modal` + iki `Button` ile yapılmış. CLAUDE.md 'Silme/onay diyaloğu: ConfirmDialog.svelte' tek-standart kuralını belirtir; native confirm() kullanılmadığı için kritik bir ihlal değil ama kanonik bileşen (sistem/kullanicilar referansındaki gibi ConfirmDialog) atlanmış — modüller-arası tutarlılık sapması.

**D75. `system.error_logs` — Backend /summary endpoint'i frontend'de kullanılmıyor (kısmi hayalet API)**  
*Yer:* `backend/app/routers/error_logs.py:62-75`  
GET /summary (seviye bazlı sayı özeti) backend'de tanımlı ve docs/api-haritasi.md dışında dokümante edilmemiş (doküman tablosunda da yok), frontend sayfasında (hata-loglar/+page.svelte) hiç çağrılmıyor/StatCard olarak gösterilmiyor. CLAUDE.md tasarım standardı 'Stat Cards → StatCard bileşeni, başlığın hemen altında' beklerken bu sayfada hiç StatCard yok; var olan özet API'si de kullanılmamış durumda.

**D76. `system.modules` — Dokümantasyon — kod ile uyumsuz açıklama**  
*Yer:* `docs/modules/sistem-moduller.md:26`  
Dokümanda 'GET /api/system/modules/ | system.modules:view | Paginated düz liste' yazıyor ancak backend/app/routers/system_modules.py:35-40 içindeki list_modules endpoint'i hiçbir page/page_size query param'ı almıyor ve List[ModuleResponse] döndürüyor (CLAUDE.md'deki {items, total, page, page_size, pages} zarfı yok). Modül sayısı az olduğundan pagination'a ihtiyaç olmayabilir (bilinçli tasarım olabilir), ama doküman metni yanıltıcı — 'Paginated' ifadesi kaldırılmalı ya da gerçek davranış (tam liste, sıralı) yazılmalı.

**D77. `system.modules` — Dosya içi kod düzeni — modül docstring eksik**  
*Yer:* `backend/app/routers/system_modules.py:1; backend/app/models/module.py:1; backend/app/schemas/module.py:1`  
CLAUDE.md 'Dosya İçi Kod Düzeni' bölümü router/model/schema dosyalarının ilk maddesinin modül docstring'i ("""Açıklama...""") olmasını şart koşuyor (örn. system_roles.py:1 bu kurala uyuyor: """Sistem rol yönetimi — CRUD ve izin matrisi."""). Bu üç system.modules dosyasının hiçbirinde docstring yok, doğrudan import ile başlıyor — küçük ama tutarlılık açısından düzeltilmesi gereken bir stil sapması.

**D78. `system.modules` — Frontend UI tasarım sistemi — StatCard/Pagination kullanılmıyor (muhtemelen bilinçli istisna)**  
*Yer:* `frontend/src/routes/dashboard/sistem/moduller/+page.svelte:160-230`  
Kanonik liste sayfası iskeletinde (PageHeader→StatCard→filtre→içerik→Pagination) bu sayfa StatCard, arama/filtre barı ve Pagination içermiyor; doğrudan PageHeader→ağaç-liste gidiyor. Modül sayısı küçük ve sabit (hiyerarşik ağaç, sayfalanacak büyüklükte değil) olduğundan muhtemelen bilinçli/gerekçeli bir istisna (CLAUDE.md'deki 'Bilinçli İstisnalar' ruhuna benzer), ancak CLAUDE.md'de bu sayfa açıkça istisna listesinde yer almıyor. Kritik değil, sadece dokümante edilmesi önerilir (ör. docs/modules/sistem-moduller.md'ye 'Pagination/arama bilinçli olarak yok çünkü modül sayısı azdır' notu eklenebilir).

**D79. `system.roles` — Pagination — CLAUDE.md "İstek ?page=1&page_size=50 / yanıt {items,total,page,page_size,pages}"**  
*Yer:* `backend/app/routers/system_roles.py:24-30 (karşılaştır: backend/app/routers/system_users.py:28-49)`  
GET /api/system/roles/ düz List[RoleResponse] döndürüyor; page/page_size query-param'ı ve {items,total,page,page_size,pages} zarfı yok. Aynı pakette system.users bu formatı uyguluyor (build_user_responses_batch + page_meta). tests/test_system.py:13-16 da bu farkı doğruluyor (roles list, users items/total). Rol sayısı doğası gereği az olduğundan pratik risk düşük, ama CLAUDE.md kuralı istisna tanımlamadan tüm liste endpoint'lerini kapsıyor ve docs/api-haritasi.md:19 bu sapmayı not düşmüyor.

**D80. `system.server (Sunucu İzleme)` — Dosya haritası — CLAUDE.md Proje Yapısı ağacı güncelliği**  
*Yer:* `CLAUDE.md:231-232`  
Ana CLAUDE.md'nin 'Proje Yapısı' ağacındaki routers listesi ("auth, health, system_users, system_roles, system_modules, messages, ...") system_server.py, system_backup.py, system_docs.py gibi sonradan eklenen router dosyalarını içermiyor; RBAC bölümünde 'Sunucu (system.server)' modülü tanımlı olduğu halde dosya haritası güncellenmemiş.

**D81. `system.server (Sunucu İzleme)` — Değişiklik Dokümantasyonu — modül-içi CLAUDE.md**  
*Yer:* `backend/app/routers/system_server.py (modül-içi CLAUDE.md yok)`  
finance/, hr/, sales/, accounting/, quality/ paketlerinin her birinde bir CLAUDE.md dosyası var (backend/app/routers/finance/CLAUDE.md vb.) ama system_server.py için (sistem paketi altında toplu bir dosya da yok) 'neden onay akışından muaf tutuldu', 'neden whitelist yaklaşımı seçildi' gibi mimari kararları kayıt altına alan bir doküman yok. Düşük risk çünkü tek dosyalık bir modül, ama CLAUDE.md 'her değişiklik sonrası ilgili modülün CLAUDE.md dosyası güncellenmeli' kuralına tam uymuyor.

**D82. `system.server (Sunucu İzleme)` — Audit log action isimlendirmesi**  
*Yer:* `backend/app/routers/system_server.py:195-200`  
log_action(db, current_user.id, "restart", "service", ...) çağrısında action="restart" kullanılıyor. CLAUDE.md 'Audit Log Sistemi' bölümünde kaydedilen eylemler login/register/change_password/reset_password/create/update/delete olarak listelenmiş; "restart" bu standart listede yok (yeni bir action türü, dokümante edilmemiş). İşlevsel bir hata değil ama audit log dokümantasyonunun bu genişlemeyi yansıtmaması küçük bir tutarsızlık.

**D83. `system.users` — UI metin tutarlılığı — reset şifre placeholder**  
*Yer:* `frontend/src/routes/dashboard/sistem/kullanicilar/+page.svelte:333`  
Şifre sıfırlama modalındaki placeholder 'En az 6 karakter' yazıyor, ama hem gerçek backend kuralı (8) hem de aynı sayfadaki `handleResetPassword()` (satır 169: `resetPassword.length < 8`) 8 karakter istiyor. Placeholder yanlış bilgi veriyor.

**D84. `system.users` — Dokümantasyon güncelliği — pagination parametreleri**  
*Yer:* `docs/modules/sistem-kullanicilar.md:34 vs backend/app/routers/system_users.py:30`  
Doküman 'Varsayılan page_size=20, max=100' diyor; kodda gerçek değerler `Query(50, ge=1, le=200)` yani varsayılan 50, üst sınır 200. Doküman kod ile senkron değil.
