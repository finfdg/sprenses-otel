# Sprenses Otel ERP — Teknik Denetim Raporu

**Tarih:** 2026-06-21 · **Yöntem:** 15 boyutlu çok-ajanlı denetim (32 ajan, ~2.6M token analiz) + her Kritik/Yüksek bulgunun çekişmeli (adversarial) ikinci-ajan doğrulaması · **Kapsam:** backend 209 dosya/~39k satır, frontend 99 .svelte + 59 .ts/~36k satır, 63 tablo, 80 migration, 1075 backend + 274 frontend test.

> Tüm risk seviyeleri çekişmeli doğrulamadan geçirildi. Doğrulayıcı, ilk denetçinin **abarttığı** riskleri düşürdü (örn. çoğu "Yüksek" → "Orta") ve bir yerde **eksik tartılmış** gerçek bir bug'ı yükseltti. Aşağıdaki "Doğrulanmış Risk" sütunu nihai değerdir.

---

## Genel Skor Tablosu

| # | Boyut | Skor /10 | Olgunluk |
|---|---|:---:|---|
| 1 | Mimari ve Modülerlik | 7.5 | Üst-çeyrek |
| 2 | Kod Kalitesi | 7.5 | Üst-çeyrek |
| 3 | Güvenlik (OWASP Top 10) | 8.5 | Güçlü |
| 4 | Performans | 7.8 | Üst-çeyrek |
| 5 | Stabilite ve Dayanıklılık | 7.5 | Üst-çeyrek |
| 6 | Veritabanı Tasarımı | 7.5 | Üst-çeyrek |
| 7 | API Kalitesi | 7.0 | Sağlam |
| 8 | Frontend ve Mobil | 8.0 | Güçlü |
| 9 | Test Altyapısı (Kapsam) | 7.0 | Sağlam |
| 10 | Test Süreçleri | 7.5 | Üst-çeyrek |
| 11 | **CI/CD ve DevOps** | **5.5** | **Zayıf** |
| 12 | Loglama ve İzleme | 6.5 | Orta |
| 13 | Dokümantasyon | 7.5 | Üst-çeyrek |
| 14 | **Ölçeklenebilirlik** | **5.5** | **Zayıf** |
| 15 | **Teknik Borç ve Yol Haritası** | **5.5** | **Zayıf** |

**Profil:** Ürün/uygulama katmanı (güvenlik, mobil, performans, mimari, finans iş mantığı) gerçekten üst-çeyrek; **operasyon/platform katmanı (CI-gating, DR/yedek, observability, yatay ölçek) enterprise seviyenin altında.** Tek Kritik bulgu — **otomatik veritabanı yedeği yok** — genel notu sınırlayan ana kalemdir.

**En kritik 3 madde (doğrulanmış):**
1. 🔴 **KRİTİK — D15-1:** Otomatik DB yedeği YOK. "Yedekleme" modülü yalnız *kodu* git ile yedekliyor; DB için pg_dump/PITR/snapshot job'u hiç yok.
2. ✅ **ÇÖZÜLDÜ (2026-06-22) — YÜKSEK D2-4:** `approval_executor` router mantığını elle tekrarlıyordu + **gerçek bug**: `product_id` (model kolonu `credit_product_id`) → onaylanan ödeme-güncelleme/ürün-silme'de `AttributeError` 500; BCH/KMH onayında ödeme planı + finance_events üretilmiyordu. → `app/services/credit_service.py` (router + executor ORTAK çağırır) + tarih coercion + 3 regresyon testi (D1-2 ilk dilim).
3. 🟠 **YÜKSEK — D10-1:** En büyük dosya `bank_parser.py` (1044 satır, banka ekstre ayrıştırma) ayrıştırma mantığı hiç test edilmiyor (~%9 kapsam = sadece import). Finansal verinin giriş kapısı.

---

## Önceki Denetimle Karşılaştırma (2026-06-19 → 2026-06-21)

**2026-06-19 kod denetimi:** 6 paralel ajan, **kod-odaklı 6-7 boyut**, ağırlıklı **≈7.8/10** — "üst-çeyrek, kritik bug yok"; listelenen tüm teknik borçlar aynı oturumda **çözüldü**. **2026-06-20 tasarımcı denetimi:** 54 sayfa UI, **≈8.2/10**, sapmalar uygulandı.
**2026-06-21 (bu denetim):** 15 boyut — kod **+ operasyon/platform** (CI/CD, DR, observability, ölçeklenebilirlik). Bu yüzden geniş not (**72/100**) dar nottan (7.8) düşük görünür; bu **regresyon değil, daha geniş mercektir.**

**Karşılaştırılabilir boyutlar (06-19'da puanlananlar):**

| Boyut | 06-19 | 06-21 | Δ | Yorum |
|---|:---:|:---:|:---:|---|
| Güvenlik | 8.5 | 8.5 | → | Sabit. `/docs prod'da açık` sanılan madde bu turda **public 404** doğrulandı (gerçek açık değil) |
| Performans | 7.5 | 7.8 | ▲ | 06-19 düzeltmeleri (FIFO TTL cache, upload `to_thread`, GZip, mobile N+1) koddan doğrulandı — **kalıcı** |
| Mobil & UI | 7.5 | 8.0 | ▲ | 06-20 tasarımcı sapmaları (SegmentedControl, StatCard delta, touch-target) uygulanmış |
| Dokümantasyon | 7.0 | 7.5 | ▲ | `api-haritasi.md` + `docs/modules` tablosu senkron çıktı |
| Modülerlik | 8.0 | 7.5 | ▽ | Regresyon değil — service-katmanı yokluğu + executor-paritesi **daha derin** denetlendi |
| Stabilite | 8.0 | 7.5 | ▽ | retry-yokluğu + sahte health bu turda ayrıca tartıldı (yeni mercek) |
| Test & CI | 8.0 | Test 7-7.5 / **CI/CD 5.5** | ▽ | 06-19 birleşikti; bu tur **CI/CD'yi ayırdı** → gate/SAST/rollback/DR boşluğu yüzeye çıktı |

> **Nicel kanıt — kod katmanı korundu:** 06-21'de yalnız bu 7 karşılaştırılabilir boyutun ortalaması **≈7.7** — yani 06-19'un 7.8'iyle neredeyse aynı. Dar mercekte skor sabit; **72/100'e çeken, ilk kez ayrı puanlanan operasyon boyutlarıdır.**

**06-19'da hiç puanlanmamış (yeni mercek) boyutlar:** API 7.0 · DB Tasarımı 7.5 · Test Süreçleri 7.5 · **Loglama/İzleme 6.5** · **Ölçeklenebilirlik 5.5** · **Teknik Borç/Yol Haritası 5.5**. Zayıf notlar buradan geliyor.

**Önceki turdan bu yana — durum değişimi:**

| Madde | 06-19 durumu | 06-21 durumu |
|---|---|---|
| `/api/auth/register` kaldırma | Çözüldü | ✅ Hâlâ kaldırılmış (kod+doküman tutarlı) |
| sales_invoices TTL cache + SQL pagination | Çözüldü | ✅ Doğrulandı, çalışıyor |
| Upload parse `asyncio.to_thread` | Çözüldü | ✅ banks/checks/cariler/reservations'da mevcut |
| GZip + matching_service ayrıştırma | Çözüldü | ✅ Doğrulandı |
| Mobil touch-target (Button.svelte) | Çözüldü | ✅ Korundu (D8 = 8.0) |
| `/docs` prod erişimi (açık nokta) | İzlemede | ✅ Public **404** (kapalı/zaten kapalıydı) |
| **Otomatik DB yedeği** | *Kapsam dışıydı (DR boyutu yoktu)* | 🔴 **YENİ KRİTİK — D15-1** |
| **approval_executor `product_id` bug** | *Risk sınıfı işaretliydi, bu bug bulunmamıştı* | 🟠 **YENİ YÜKSEK — D2-4** |
| **bank_parser iç ayrıştırma testi** | *Parser-çevresi test eklendi, iç mantık değil* | 🟠 **YENİ YÜKSEK — D10-1** |
| **CI gate / SAST / observability / ölçek** | *Ayrı puanlanmadı* | 🟠 **YENİ ZAYIF boyutlar (5.5-6.5)** |

**Özet:** 06-19/06-20'de işaretlenen hiçbir madde **geri gelmedi** — kod katmanı sağlamlığını korudu, hatta perf/mobil/doküman iyileşti. Bu denetimin değeri, daha önce **hiç bakılmamış operasyon/platform katmanını** ölçmesi: tek Kritik (DB yedeği) ve iki Yüksek tam da bu yeni mercekten çıktı.

---

## 1. Mimari ve Modülerlik — 7.5/10

**Mevcut Durum:** Gerçek anlamda modüler: domain'ler net paketlere ayrılmış (`finance/cariler`, `krediler`, `cash_flow` + `_helpers`), runtime'da **hiç circular dependency yok** (AST 2-cycle taraması temiz; `utils/models/schemas/middleware` katmanları `routers`'tan import etmiyor — doğru katman yönü). Fabrika desenleri güçlü. Ana borç: resmi bir **service katmanı yok** — iş mantığı kısmen `utils/`, kısmen doğrudan router'larda; onay executor'ı her router'ın mutasyon mantığını elle ikinci kez yazıyor.

**Güçlü Yönler:**
- `create_scheduled_router` (scheduled_base.py:87-450) 8 muhasebe/İK modülünü tek dosyadan üretiyor; frontend aynası `ScheduledModule.svelte` (1217 satır) 8 sayfayı 14 satırlık tüketicilerle besliyor.
- `lib/config/navigation.ts` sidebar + route-guard izin haritasını tek kaynaktan veriyor.
- `finance_event_service.py` (494) merkezi olay deposu — domain'ler birbirine değil bu servise bağlı.
- Onay katmanı için 3 AST regresyon testi (import çözümü, model-alan geçerliliği, "her `check_approval` çağıranın handler'ı var").

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D1-1 | Service katmanı yok; router'lar kardeş router'lardan import ediyor | Orta | yonetim.py:22-23 (`from app.routers.stock import compute_operational_kpi`), sedna_sync.py:26-27 |
| D1-2 | `approval_executor` router mantığını elle tekrarlıyor (998 satır, ~20 handler) | Orta ✓ *(Yüksek→Orta: test+modul-denetci ile aktif yönetiliyor)* | approval_executor.py:122-213 |
| D1-3 | Monolitik büyük dosyalar (SRP) | Orta | otel-rezervasyon 2232, cariler 1995, bank_parser 1044, banks.py 843 |
| D1-4 | Backend↔frontend sabit eşleşmesi elle; otomatik parite testi yok | Düşük | constants.py ↔ realtime.ts |
| D1-5 | `utils/` hem saf yardımcı hem ağır servis barındırıyor; sınır belirsiz | Düşük | utils/ altında finance_event_service/matching_service ↔ pdf_fonts/file_validation |

**Risk Seviyesi:** Orta (yapısal, veri-kaybı riski yok).
**Öncelik:** D1-2 + D1-1 + D1-5 tek "service katmanı oluştur" epiğinde birleştirilebilir → en yüksek mimari getiri. Sonra D1-3 (büyük dosya bölme), D1-4 (parite testi, ucuz).

> **✅ Uygulama Durumu (2026-06-22):**
> - **D1-1 (TAM kapandı):** `app/services/` katmanı kuruldu — `stock_service` (run_stock_import/compute_operational_kpi/compute_price_variance/anomalies), `reservation_service` (run_reservation_import/_currency_to_eur_factors/_window_start), `sales_invoice_service` (FIFO `_compute`/`_compute_cached`/`_invalidate_compute_cache`/`_merged_advances` + cache); `_norm_tokens` → `utils/text_match.py`. Hepsi **byte-aynı** (AST taşıma scripti) taşındı. `yonetim.py`/`sedna_sync.py`/`daily_activity.py`/`advances.py`/`conftest.py` service/utils'ten import ediyor → **4 paketler-arası router→router import'unun TAMAMI kapatıldı.** (Aynı-paket `sedna_sync→sales_invoices.run_sales_invoice_import` bilinçli istisna.) 21+ ölü import temizlendi.
> - **D1-5:** CLAUDE.md'ye "router router'dan import etmez" + `utils/`(teknik) vs `services/`(domain) ayrım kuralı eklendi; proje yapısı + finance/CLAUDE.md güncellendi.
> - **D1-4 (tamam):** `tests/test_constants_parity.py` — backend `constants.py` ↔ frontend `realtime.ts` WS event + broadcast modül parite testi (26 event + 13 modül senkron).
> - **Doğrulama:** 1152 passed / 4 skipped (iki turda da), app temiz yükleniyor, service katmanı router import etmiyor (tek yön), canlıya alındı.
> - **Kalan:** **D1-2 tamamı** (~20 executor handler ↔ router ortak service) ve **D1-3** (god-component bölme) ayrı odaklı pass'ler.

---

## 2. Kod Kalitesi — 7.5/10

**Mevcut Durum:** Disiplinli ve okunabilir: **boş catch bloğu yok**, TODO/FIXME borcu neredeyse sıfır (39k satırda 2), naming kuralı (İngilizce tanımlayıcı + Türkçe kullanıcı metni) tutarlı, sihirli-string yerine `constants.py`. En büyük backend dosyaları "büyük ama iyi ayrıştırılmış" (god-function değil). Asıl borç frontend god-component'lerde ve elle tekrarlanan yardımcılarda.

**Güçlü Yönler:**
- ASCII-Türkçe (kullanici/duzenle) **hiçbir** tanımlayıcıda yok; Türkçe/İngilizce karışıklığı tespit edilmedi.
- `bank_parser.py` (1044) 25+ küçük fonksiyon; `approval_executor.py` (998) handler-dispatch tablosu — refactor gerektirmez.
- Frontend'de hiç `catch {}` yok; backend `except: pass`'ler dar/bilinçli.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D2-4 | `approval_executor` handler'ları router endpoint mantığını elle tekrarlıyor — **gerçek bug bulundu** | **Yüksek ✓** | executor.py:383/434 `product_id` ≠ model `credit_product_id` → AttributeError 500; :400-419 BCH/KMH ödeme planı + finance_events üretmiyor |
| D2-1 | Frontend god-component'ler | Orta | cariler 1995 (48 fn), otel-rezervasyon 2232 (~128 fn) |
| D2-2 | `formatDate` 11+ sayfada elle ve **tutarsız** tekrar tanımlanıyor | Orta | cariler:306, cekler:105 (locale'e bağlı!), audit-loglar:67 |
| D2-5 | Yaygın `any` kullanımı (381 adet) — frontend tip güvenliği zayıf | Orta | krediler(8), yonetim(6), butce(5) `$state<any[]>` |
| D2-3 | Yerel `formatCurrency` finance.ts helper'ını tekrarlıyor | Düşük | bankalar:424, cariler:297 |
| D2-6 | `math.ceil(total/page_size)` 23 endpoint'te elle; `paginate()` helper yok | Düşük | checks.py:684 vb. |

**Risk Seviyesi:** Çoğu Orta/Düşük (kalite). D2-4 Yüksek (üretim verisi).
**Öncelik:** D2-4 (önce `product_id`→`credit_product_id` bug'ını düzelt, sonra service-katmanı ile kökten çöz) → D2-1 → D2-2 → D2-5 → D2-3/D2-6.

> **✅ Uygulama Durumu (2026-06-22, D1-2 ilk dilim):** **D2-4 ÇÖZÜLDÜ** — `app/services/credit_service.py` oluşturuldu; `finance.krediler` router endpoint'leri (`products.py`/`payments.py`) ve onay executor handler'ı (`_handle_finance_krediler`) artık **AYNI** service fonksiyonlarını çağırıyor (tek kaynak → router↔executor sapması yapısal olarak imkansız). Düzeltilen bug'lar: (1) `payment.product_id`→`credit_product_id` (AttributeError/500), (2) onayda BCH/KMH ödeme planı + finance_events üretimi, (3) payload JSON tarih→string coercion (`_coerce_date`). BCH/KMH regeneratörler `_helpers.py`→service taşındı. **3 regresyon testi** (BCH plan üretimi, payment update, product delete — onay yoluyla). Davranış router ile birebir, canlıya alındı. **D1-2 deseni** kademeli uygulanıyor. **Tamamlanan dilimler (≈13 modül birleşti):**
1. **krediler** (`credit_service`) — `product_id` crash + eksik BCH/KMH plan (3 test)
2. **cariler** (`vendor_service`) — vade/durum + FE sync; regresyon testi yoktu → 2 eklendi
3. **çekler** (`check_service`) — durum + **iptal kademesi** (cari+banka unmatch); 1 test
4. **scheduled** (`scheduled_service`) — **8 modül** (vergi/recurring/kira×2/temettü/maaş/stopaj/sgk) tek serviste; **gerçek bug**: executor `create` `sync_recurring_from_vendors`'u atlıyordu → onaylı cari-bağlı düzenli ödeme senkronlanmıyordu (+ fallback `vendor_id` eksikti)
5. **quality_templates** (`quality_service`) — bölüm/alan/atama kaydetme; router (`_save_sections` Pydantic) + executor (`_save_template_sections` dict) **iki kopyaydı ve drift etmişti** (options çift-serileştirme) → tek dict-tabanlı service

6. **system×3** (`system_service`) — **3 gerçek drift**: roles update'te izin cache invalidate eksik (onaylı izin bayat kalıyordu); users update'te devre-dışı→oturum kapatma eksik; roles/modules delete executor SOFT vs router HARD+guard
7. **avanslar** (`advance_service`) — CRUD + FE (neutral refactor)
8. **banks** (`bank_account_service`) — hesap CRUD (neutral)
9. **departmanlar** (`department_service`) — **drift**: executor guard'sız SOFT delete vs router guard'lı HARD → birleştirildi

**Toplam 10 handler / ≈19 modül birleşti; 9+ gerçek drift/bug kapatıldı. 1158 test yeşil, hepsi canlıda.** `app/services/` 13 modül.

**Kalan 6 handler (dikkatli iş gerektiriyor — sonraki turda):**
- **butce** — budget'te **gerçek upsert drift'i**: router kompozit-anahtar `_upsert_budget` (dept+kategori+yıl+ay), executor id-bazlı insert → **çift bütçe riski**. Dikkatli birleştirme gerekir.
- **hr×3** (attendance/shifts/shift_schedule) — executor ISO-string parse eder, router typed (datetime/time/date) alır → service'te coercion gerekir (credit_service._coerce_date kalıbı).
- **room_types** (delete rezervasyon-guard) + **quality_forms** (saf CRUD) — basit, hızlı.

---

## 3. Güvenlik (OWASP Top 10 2021) — 8.5/10

**Mevcut Durum:** Üst-çeyrek olgunluk. Erişim kontrolü (her mutasyonda `require_permission`, mesaj IDOR `_get_membership` ile kapalı, her istekte rol+oturum yeniden doğrulanıyor), kimlik (JWT yalnız HttpOnly+secure+samesite cookie, bcrypt) ve enjeksiyon savunması (ORM parametrik; Sedna ham SQL girdileri **istisnasız** doğrulanmış) sağlam. **Önemli düzeltme:** önceki turlarda "açık nokta" sayılan `/docs prod'da açık` bu denetimde nginx sınırında **public 404** çıktı (yalnız localhost) — gerçek bir açık değil.

**OWASP madde-madde:** A01 Erişim=GÜÇLÜ · A02 Kripto=GÜÇLÜ/ORTA (eski jose/passlib) · A03 Injection=GÜÇLÜ (gerçek SQLi yok) · A04 Tasarım=İYİ · A05 Yapılandırma=İYİ · A06 Bileşenler=ORTA · A07 Auth=İYİ (sahtelenemez IP rate-limit) · A08 Bütünlük=İYİ · A09 Loglama=İYİ · A10 SSRF=YOK.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D3-1 | WebSocket handshake'inde Origin kontrolü yok → CSWSH ile online kullanıcı listesi sızabilir | Orta | ws.py:228-247 (Origin yok) + :296-302 (online_users isim/ID) |
| D3-2 | `python-jose 3.3.0` + `passlib 1.7.4` — bakımı durmuş/CVE'li | Orta | requirements.txt:8-9 (CVE-2024-33663/33664; algorithms=[HS256] sabit olduğundan ilki etkisiz) |
| D3-3 | access_token 24 saat — çalınan token uzun geçerli, idle/absolute timeout yok | Düşük | config.py:11 (1440 dk) |
| D3-4 | samesite=lax (strict değil); ek CSRF katmanı yok | Düşük | auth.py:30,145 |
| D3-5 | nginx'te kaldırılmış `/api/auth/register` için ölü location bloğu | Düşük | sprenses.conf:48-55 |
| D3-6 | WEBP logo magic-byte eksik doğruluyor (yalnız RIFF, offset-8 WEBP atlanıyor) | Düşük | templates.py:475 |

**Risk Seviyesi:** Hiçbiri Kritik/Yüksek değil. Tek somut runtime-istismar vektörü D3-1 (bilgi sızıntısı).
**Öncelik:** D3-1 (WS Origin) → D3-2 (PyJWT'ye geç) → D3-3 → D3-4/5/6 (sertleştirme + temizlik).

---

## 4. Performans — 7.8/10

**Mevcut Durum:** Olgun; önceki N+1/cache iyileştirmeleri uygulanmış. Liste endpoint'leri **gerçek SQL seviyesinde** sayfalama (count + offset/limit), sıcak listelerde batched IN-lookup + joinedload ile N+1 engellenmiş, GZip + Sedna okuma yollarında TTL cache, DB pool sağlam (25+10, pre_ping, recycle), CPU-yoğun parse `asyncio.to_thread`. Senkron `def` endpoint'ler FastAPI threadpool'unda → event-loop kilitlenmiyor. Kalan darboğazlar mimari/operasyonel.

**Güçlü Yönler:** Her yerde gerçek SQL pagination (Python slice yok); `mobile_dashboard_summary` subquery+JOIN ile tek sorgu; finance_events 5 hedefli index; Sedna fetch'leri sync `def` (event-loop bloke olmaz) + upload parse `to_thread`.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D4-1 | Tek uvicorn worker — tüm yük tek process/GIL | Orta ✓ *(Yüksek→Orta: systemd Restart=always, düşük eşzamanlılık)* | sprenses-api.service:13 `--workers 1` |
| D4-2 | `quality/forms` liste GET'i **GET'te yazma + N+1** (şablon başına SELECT+commit) | Orta | quality/forms/crud.py:43-69 |
| D4-3 | Sedna `sync-all` tek istekte 7 ağır sorguyu sıralı çalıştırıyor (retry yok) | Orta | sedna_sync.py:104-145 (180s+180s+...) |
| D4-4 | Sıcak nakit-akım sorgusu için `(is_matched, event_date)` composite index yok | Düşük | listing.py:83-89 ↔ finance_event.py:116-122 |
| D4-5 | Sedna fetch'leri tüm sonucu `fetchall()` ile belleğe alıyor | Düşük | sedna_client.py:228/282/305, stok hareketleri LIMIT'siz |

**Risk Seviyesi:** Orta tavanı. **Öncelik:** D4-1 (worker) → D4-2 (GET'te yazma, kolay düzeltme) → D4-3 (sync-all'ı arka plana al + retry) → D4-4 (composite index) → D4-5 (veri büyüdükçe).

---

## 5. Stabilite ve Dayanıklılık — 7.5/10

**Mevcut Durum:** Harici servis kesintilerinde doğru **graceful degradation** (Sedna kapalı→503, uygulama ayakta). Transaction yönetimi olgun: onay→uygula atomik (handler'larda commit yok, hata→rollback), banka upload SAVEPOINT izolasyonlu, `finance_event_service` hata re-raise, kritik tablolarda DB-seviye UNIQUE çift-sayımı engelliyor. Ana zayıflık: **hiçbir harici çağrıda retry yok**, health DB sağlığını kontrol etmiyor.

**Güçlü Yönler:** Onay executor'da sıfır `db.commit()` → kısmi kalıcılık imkansız; banka upload her matcher ayrı `begin_nested()`; finance_events/vendor_tx/checks UNIQUE = concurrent çift-import'a son savunma; push webpush timeout=10s.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D5-1 | **Hiçbir harici çağrıda retry yok** — geçici ağ hatası kalıcı başarısızlık | Orta | sedna_client.py:181, tcmb.py:100/115/199 |
| D5-2 | Health endpoint DB/Sedna kontrol etmiyor — sahte 'ok' | Orta | health.py:7-8 |
| D5-3 | Cari Sedna import'unda satır-bazlı SAVEPOINT yok (çek'in aksine) | Düşük | cariler/sedna_import.py:155-176 |
| D5-4 | Global handler'da en-dış `except: pass` + DB log yazımı patlarsa sessiz | Düşük | main.py:177-178, :169 |
| D5-5 | `update_amount_try` sessiz hata yutuyor (return 0) → TL bakiye sessizce eksik | Düşük | finance_event_service.py:488-490 |

**Risk Seviyesi:** Orta. Veri-kaybı/çift-sayım riski düşük (atomiklik + DB constraint olgun); eksik olan **dayanıklılık katmanı (retry) + gözlemlenebilirlik (health)**.
**Öncelik:** D5-1 (retry) → D5-2 (health DB ping) → D5-3/D5-5 → D5-4. **Öneri:** harici-servis-kesintisi (chaos) testi ekle (monkeypatch ile SednaUnavailable → 503 + ayakta kalma).

---

## 6. Veritabanı Tasarımı — 7.5/10

**Mevcut Durum:** Şema olgun: 63 tablonun tamamı PK'lı, tek-head temiz migration zinciri, 80 migration'ın hepsinde downgrade, **tüm para alanları Numeric** (float drift yok), büyüyen tablolarda hedefli composite index'ler, `/migration` skill'i autogenerate'i zorunlu manuel incelemeye tabi tutuyor. Eksikler: indekssiz FK'ler, `sales_invoices/sales_collections` tx_hash'inde DB UNIQUE yok, CHECK kısıtları neredeyse tamamen uygulama katmanında.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D6-2 | `sales_invoices`/`sales_collections` tx_hash'inde DB UNIQUE yok — dedup yalnız uygulamada + tüm hash'ler belleğe | Orta ✓ *(Yüksek→Orta: tek manuel-tetikleme yolu, deterministik hash)* | sales_invoice.py:30-33/69-72 (yalnız Index); sales_invoices.py:227 |
| D6-1 | 40 indekssiz FK; birkaçı sıcak yol | Orta | scheduled_entries.definition_id, bank_transactions.statement_id, reservations.upload_id (17k satır), role_module_permissions.module_id |
| D6-3 | `reservations.upload_id` = SET NULL + indekssiz → 17k satırda silmede seq scan | Orta | reservation.py:70-71 |
| D6-4 | DB-seviyesi CHECK kısıtları neredeyse yok (yalnız 3) | Orta | finance_events.direction/amount CHECK'siz |
| D6-5 | Alembic `compare_type`/`compare_server_default` ayarlı değil → tip/default değişimi kaçar | Düşük | env.py:44,56 |
| D6-6 | Sınırsız büyüyen log/event tablolarında retention/arşiv yok | Düşük | audit_logs/error_logs/finance_events |

**Risk Seviyesi:** Orta. **Öncelik:** D6-2 (DB UNIQUE — finansal dedup) → D6-1+D6-3 (tek migration ile sıcak FK index'leri) → D6-4 (finance_events CHECK) → D6-5/D6-6.

---

## 7. API Kalitesi — 7.0/10

**Mevcut Durum:** 327 endpoint genelinde isimlendirme örnek-niteliğinde tutarlı (REST + çoğul kaynak, tamamı ASCII, kebab-case), create POST'ları istisnasız 201, onay 202'si tek noktadan, HTTPException `detail` her yerde string. Ana eksikler **sözleşme/dokümantasyon** katmanında: API versiyonlama yok, response_model %11, tanımlı `PaginatedResponse` ölü kod, 422 için Türkçe handler yok.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D7-2 | OpenAPI zayıf: response_model 37/327; `/docs` prod'da açık (app sınırında) | Orta | main.py:82; banks/cariler response_model=0 |
| D7-1 | API versiyonlama yok (`/api/v*` yok, version=1.0.0) | Orta | main.py:82,182-211 |
| D7-3 | `PaginatedResponse` tanımlı ama hiç kullanılmıyor (ölü kod) | Orta | pagination.py:9 |
| D7-5 | 422 için özel handler yok — İngilizce Pydantic dizisi, Türkçe `{detail}` sözleşmesinden sapıyor | Düşük | main.py:140 (yalnız Exception handler) |
| D7-4 | DELETE status kodları tutarsız (204 vs 200+body) | Düşük | 18×204, 20×200 |
| D7-6 | `api-haritasi.md:259` drift: belge `/api/uploads`, gerçek `/uploads` | Düşük | files.py:60 |

**Risk Seviyesi:** Orta — işlevsel olarak sağlam, enterprise API-sözleşmesi olgunluğuna (response_model + versiyonlama + tipli pagination) ulaşmamış.
**Öncelik:** D7-2 → D7-1 → D7-3 → D7-5 → D7-4 → D7-6.

---

## 8. Frontend ve Mobil — 8.0/10

**Mevcut Durum:** Projenin gerçekten güçlü olduğu alan. `Button.svelte`'e gömülü `touch-target` (44px, `pointer:coarse`), off-canvas hamburger + backdrop, `viewport-fit=cover` + safe-area, iOS 16px anti-zoom, `prefers-reduced-motion`, dvh fallback, **tam PWA** (manifest + offline-fallback'lı SW + push). 14+ sayfada `<md`'de tablo→kart. Eksikler ikincil.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D8-1 | Gerçek-cihaz / e2e mobil test altyapısı yok | Orta | package.json (Playwright/Cypress yok); ci.yml yalnız vitest |
| D8-2 | Yoğun finansal tablolarda (krediler) mobil kart yok ve dokümante istisna listesinde değil | Düşük | krediler:1110-1352 yalnız overflow-x-auto |
| D8-3 | Özel PWA "Uygulamayı Yükle" akışı yok (yalnız tarayıcı-native) | Düşük | `beforeinstallprompt` handler yok |
| D8-4 | Login sayfasında Lucide yerine 6 inline SVG | Düşük | +page.svelte:94-165 |

**Risk Seviyesi:** Düşük. Çekirdek mobil deneyim üst-çeyrek.
**Öncelik:** D8-1 (Playwright viewport-regresyon smoke) → D8-2 (karar dokümante et) → D8-3/D8-4.

---

## 9. Test Altyapısı (Kapsam) — 7.0/10

**Mevcut Durum:** Backend üst-çeyrek: 1075 test/54 dosya, **52 dosya TestClient + gerçek PostgreSQL** (SAVEPOINT izolasyon) — sağlam integration katmanı. Kritik finans akışları (per-currency FIFO, finance_events, onay→uygula regresyonları, KMH, occupancy) iyi kapsanmış. Üç somut boşluk: (1) dosya parser'ları test edilmiyor, (2) frontend 53 sayfa 0 test + E2E yok, (3) CI'da güvenlik/dependency taraması ve frontend coverage eşiği yok. ~%66 satır kapsamı.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D9-1 | Dosya parser'ları (bank/cc/check/vendor) doğrudan unit-test edilmiyor | Orta ✓ *(Yüksek→Orta: reservation_parser TAM test edilmiş — kalıp mevcut)* | bank_parser.py testsiz; test_cc_statements.py:3 "parser hariç" |
| D9-2 | Frontend 53 sayfa 0 test; E2E/tarayıcı testi tamamen yok | Orta ✓ *(Yüksek→Orta: sunum katmanı, iş mantığı backend'de test edili)* | `find src/routes -name '*.test.*'` = 0 |
| D9-3 | `auto_tagger` regex-eşleme motoru test edilmiyor | Orta | auto_tagger.py:315 satır, testlerde hiç çağrılmıyor |
| D9-4 | CI'da güvenlik/dependency taraması + frontend coverage eşiği yok | Orta | ci.yml (bandit/pip-audit/dependabot yok) |
| D9-5 | `sedna_client.py` saf kısımları test edilmiyor (fetch sınırında mock) | Düşük | test_sedna_sync.py:54-63 |

**Risk Seviyesi:** Orta. **Öncelik:** D9-2 ≈ D9-1 → D9-3 (ucuz, yüksek getiri) → D9-4 → D9-5. (D9-1/D9-3'ün saf yardımcıları fixture'sız → hızlı kazanım.)

---

## 10. Test Süreçleri — 7.5/10

**Mevcut Durum:** Olgun ve disiplinli. **Dört izin-matrisi fixture'ı tam tanımlı** (viewer/use/no_perm/factory), 25 dosyada kullanımda; SAVEPOINT izolasyon; Sedna pymssql doğru mock'lanmış (`sedna_configured` patch + `sys.modules` enjeksiyonu); 14 uçtan-uca onay regresyonu + 3 AST testi; CI %60 eşik. Boşluklar: en büyük dosya bank_parser %9, tcmb %0, gerçek-format rezervasyon testi CI'da sessizce atlanıyor, frontend WS/sayfa testi yok, ağ-engeli yok.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D10-1 | `bank_parser.py` ayrıştırma mantığı hiç test edilmiyor (%9) | **Yüksek ✓** | parse_excel/parse_pdf tests/'te çağrılmıyor; .xlsx/.pdf fixture yok |
| D10-2 | Gerçek-format rezervasyon regresyon testi CI'da sessizce atlanıyor | Orta | test_reservations.py:12-13 (skipif `/home/ec2-user/uploads/2025berk.xls` — runner'da yok) |
| D10-3 | TCMB döviz çekimi (tcmb.py + cron) tamamen test edilmemiş (%0) | Orta | tcmb.py %0 |
| D10-4 | Frontend sayfa/WS store testi yok, vitest coverage eşiği tanımsız | Orta | websocket.svelte.ts testsiz; vitest.config coverage yok |
| D10-5 | Testlerde harici HTTP için açık ağ-engeli yok (davranışsal kontrole bağlı) | Düşük | conftest.py'de socket/httpx guard yok; webpush hiç mock'lanmıyor |
| D10-6 | CI'da güvenlik taraması yok | Orta | ci.yml (D9-4/D11-3 ile aynı) |

**Risk Seviyesi:** Orta. **Test kullanıcıları/rolleri eksiği YOK** — istenen 4 fixture'ın tamamı var. **Öncelik:** D10-1 → D10-2/D10-3 → D10-5 → D10-4/D10-6.

---

## 11. CI/CD ve DevOps — 5.5/10 ⚠️

**Mevcut Durum:** Tek GitHub Actions workflow her push/PR'da pytest (kapsam %60) + vitest çalıştırıyor — cache, concurrency iptali, pinli bağımlılıklar, migration-zincirinden test DB ile sağlam temel. Ama pipeline test-only ve **yapısal boşluk**: özel repo + ücretsiz plan → branch protection devre dışı → CI merge'i GATE edemiyor. Deploy tamamen manuel (CD yok), rollback yok, Stop-hook her tur master'a doğrudan push.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D11-1 | CI merge'i gate edemiyor — branch protection yok (HTTP 403), master'a doğrudan push | Orta ✓ *(Yüksek→Orta: manuel deploy kapısı, tek geliştirici)* | son 100 commit'in 96'sı "Otomatik yedek" |
| D11-3 | Güvenlik taraması yok (Dependabot/CodeQL/pip-audit/npm audit) | Orta ✓ *(Yüksek→Orta: meta-bulgu, aktif açık değil)* | .github/dependabot.yml yok |
| D11-5 | Rollback stratejisi yok — 0 git tag, build prod'da yerinde üretiliyor | Orta ✓ *(Yüksek→Orta/kısmen: `set -e` bozuk build'i durdurur, git kurtarma var)* | deploy-frontend.sh:13-15 |
| D11-6 | Deploy akışında migration adımı yok — şema-kod uyumsuzluğu riski | Orta | deploy.md yalnız `systemctl restart` |
| D11-2 | CI'da type-check (svelte-check) + lint/format (ruff/black/mypy) yok | Orta | package.json'da `check` var ama CI çağırmıyor |
| D11-4 | Kapsam raporu artifact/PR'a yansımıyor | Düşük | yalnız `term-missing` |
| D11-7 | CI Ubuntu, prod Amazon Linux 2023 — C-uzantı (lxml/pdfplumber) farkı | Düşük | ci.yml:23,72 |

**Risk Seviyesi:** Bu boyutun toplam etkisi **Yüksek** (zayıf nokta). **Öncelik:** D11-1 (gate) → D11-3 (SAST/dependabot) → D11-5/D11-6 (rollback + deploy migration) → D11-2 → D11-4/D11-7.

---

## 12. Loglama ve İzleme — 6.5/10

**Mevcut Durum:** Temel altyapı sağlam: `audit_logs` (4 index, 47 router'da `log_action`), `error_logs` (global handler traceback+IP+user), RotatingFileHandler, psutil sunucu izleme. **Kurumsal seviyede değil:** harici APM/error-tracking (Sentry), Prometheus/Grafana, structured/JSON log, korelasyon ID, request-timing/slow-query yok. Frontend merkezi istemci-hata yakalama tamamen eksik. `login_failed` audit'e hiç yazılmıyor.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D12-3 | Başarısız giriş (`login_failed`) audit_logs'a yazılmıyor | Orta ✓ *(Yüksek→Orta: rate-limit aktif, gözlemlenebilirlik boşluğu)* | auth.py:51-53 yalnız logger.warning |
| D12-1 | Harici/merkezi hata-izleme + APM yok (Sentry/OTel/Prometheus) | Orta | requirements.txt'te hiçbiri yok |
| D12-2 | Frontend istemci-hata yakalama tamamen eksik (`hooks.client.ts` yok) | Orta | window.onerror→backend yok |
| D12-4 | audit_logs/error_logs retention/temizleme yok — sınırsız büyüme | Orta | retention/cron yok |
| D12-5 | Request-timing/slow-query/p95 metriği hiç toplanmıyor | Orta | süre ölçen middleware yok |
| D12-7 | error_logs yalnız ERROR; WARNING/CRITICAL/4xx görünmez | Düşük | main.py:153 sabit 'ERROR' |
| D12-6 | Yapısal (JSON) log + korelasyon/request ID yok | Düşük | düz metin LOG_FORMAT |

**Risk Seviyesi:** Orta (boyut zayıf — temel var, kurumsal katman yok). **Öncelik:** D12-3 (ucuz, güvenlik izi) → D12-4 (retention) → D12-1+D12-2 birlikte (Sentry/@sentry-sveltekit tek hamlede backend+frontend) → D12-5 → D12-7/D12-6.

---

## 13. Dokümantasyon — 7.5/10

**Mevcut Durum:** Üst-çeyrek: `api-haritasi.md` gerçekten exhaustive ve güncel (attendance 28 endpoint, stok, yönetim, backup, server, KMH koddaki dekoratörlerle birebir), `docs/modules/` tablosu diskle **%100 senkron** (38=38, kırık link yok), CLAUDE.md çekirdek mimari/güvenlik iddiaları koddan doğrulandı. Drift CLAUDE.md'nin **nicel/envanter** bölümlerinde yoğunlaşıyor. En kritik yapısal eksik: kod-doküman tutarlılığını yakalayan **hiçbir otomatik test/CI adımı yok**.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D13-1 | Kod-doküman drift için OTOMATİK tespit yok | Orta | ci.yml + tests/'te doc-kod karşılaştırma yok |
| D13-6 | `api-haritasi.md:255` WS'i `?token=JWT` ile belgeliyor — kod cookie auth (güvenlik-yanıltıcı) | Orta | ws.py:230-265 query_params okunmuyor |
| D13-7 | CLAUDE.md test-DB kurulumu kendi içinde çelişiyor (eski pg_dump vs yeni alembic) | Orta | CLAUDE.md:352 ↔ :473-482 |
| D13-3 | CLAUDE.md models/ envanteri 7+ model ailesi atlıyor (Personnel/Shift/Stock/SalesInvoice/AgencyGroup/PaymentInstruction) | Orta | CLAUDE.md:240-244 |
| D13-2 | Test sayısı/kapsam eski (1170+ iddia/gerçek 1075; %60/gerçek %66) | Düşük | CLAUDE.md:261 |
| D13-4 | Test-dosya listesi 54'ün 32'sini içermiyor | Düşük | — |
| D13-5 | Kaldırılmış `banks_cc_match` router'ı hâlâ referanslı (yalnız stale .pyc) | Düşük | CLAUDE.md:236 |
| D13-8 | `payment_instructions` ve `system.server` için dedicated docs/modules dosyası yok | Düşük | — |
| D13-9 | `ui-kurallari.md` SegmentedControl'ü listelemiyor (yalnız değişiklik günlüğünde) | Düşük | — |

**Risk Seviyesi:** Düşük-Orta. **Öncelik:** D13-1 (kök neden — hafif pytest ile gelecek drift'i kilitle) → D13-6/D13-7 (yanıltıcı içerik) → D13-3/D13-5 → kalan envanter tazeleme.

---

## 14. Ölçeklenebilirlik — 5.5/10 ⚠️

**Mevcut Durum:** Mimari ~25-50 eş zamanlı kullanıcı için bilinçli ve sağlam. Ama **yatay ölçekleme için tasarlanmamış**: tek uvicorn worker + tüm gerçek-zaman/oturum/cache durumu süreç-içi bellekte. 10x kullanıcı tek-süreç + tek EC2 (2 çekirdek/3.7GB) sınırına çarpar. Modül sayısının 2 katı **sorunsuz** (fabrika + tek-kaynak navigasyon). Tüm bulgular bugün `--workers 1` tarafından maskeleniyor.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D14-1 | WebSocket manager süreç-içi bellekte — çok-worker'da broadcast bölünür | Orta ✓ *(Yüksek→Orta: latent, tek-worker maskeliyor)* | manager.py:14-23, send_to_all:139-142 |
| D14-2 | Tek EC2 + tek worker — SPOF + dikey tavan | Orta ✓ *(Yüksek→Orta/kısmen: sync def→threadpool, event-loop bloke değil)* | service:13, nproc=2/3.7GB, swap=0 |
| D14-3 | audit_logs/finance_events için partition/arşiv/retention yok | Orta | partition yok |
| D14-4 | Dosya yüklemeleri yerel diske — çok-instance'ta paylaşılmaz | Orta | files.py:20 yerel `uploads/` |
| D14-5 | Süreç-içi cache'ler (modül/compute/rate-limit) worker'lar arası tutarsız | Orta | auth.py:19, sales_invoices.py:163, rate_limit.py:22 |
| D14-6 | WS bağlantı başına çok sayıda kısa-ömürlü DB oturumu — pool/threadpool baskısı | Orta | ws.py 9× to_thread |
| D14-7 | `send_to_all` izin-bazlı hedeflemesiz — her mutasyon herkese | Düşük | finance_broadcast.py:35-40 |

**Risk Seviyesi:** Boyut zayıf (gelecek tavanı). **Öncelik (yatay-ölçek yol haritası):** 1) Redis → WS pub/sub (D14-1) + rate-limit (D14-5) + cache invalidation; 2) Yüklemeler→S3/EFS (D14-4); 3) cache→Redis-koordineli; 4) ALB + ≥2 instance (D14-2); 5) audit/finance partition (D14-3). **Not:** oturum durumu zaten DB'de (bellek-içi değil) — yatay ölçek için bu artı.

---

## 15. Teknik Borç ve Yol Haritası — 5.5/10 ⚠️

**Mevcut Durum:** Uygulama katmanı olgun ve iyi test edilmiş; **operasyonel/altyapı olgunluğu enterprise seviyenin çok altında.** Otomatik DB yedeği YOK, sistem tek worker + in-memory durumla tek sunucuya kilitli, observability/APM yok, IaC/staging/e2e yok. Kod borcu düşük (2 TODO), platform borcu yüksek.

**Tespit Edilen Sorunlar:**

| ID | Sorun | Doğrulanmış Risk | Kanıt |
|---|---|:---:|---|
| D15-1 | **Otomatik DB yedeği YOK** — tek-disk PostgreSQL, DR sıfır | **🔴 KRİTİK ✓** | system_backup.py yalnız git/kod yedekliyor; pg_dump/PITR/snapshot/cron job yok; archive_mode=off |
| D15-2 | Tek worker + in-memory durum → yatay/dikey ölçek imkansız | Orta ✓ | service:13, manager.py:16-18, rate_limit.py:22 |
| D15-3 | Observability/APM yok + health DB kontrol etmiyor | Orta ✓ *(kısmen: LB health'e bağlı değil, pool_pre_ping var)* | requirements.txt; health.py:6-8 sabit ok |
| D15-4 | E2e yok + kritik parser/executor için ayrı birim testi yok | Orta ✓ *(kısmen: approval_executor ASLINDA iyi test edilmiş — finding yanılmış)* | 0 spec; bank_parser/cc_parser/sedna_client testsiz |
| D15-6 | Sedna istemcisinde retry/circuit-breaker yok | Orta | sedna_client.py:166-188 |
| D15-5 | IaC/Dockerfile/staging yok — dağıtım elle, ortam kopyalanamaz | Orta | *.tf/Dockerfile yok; ENVIRONMENT ayrımı yok |
| D15-7 | En büyük dosyalar (2232/1995/1625) bakım borcu | Orta | — |
| D15-8 | Güvenlik sertleştirme: 24s token, SAST yok | Orta | config.py:11; ci.yml |

**Risk Seviyesi:** Bir Kritik + çok sayıda Orta → boyut zayıf.
**Öncelik:** D15-1 (derhal) → D15-3 (gerçek health + Sentry) → D15-4 (parser testleri) → D15-2 (Redis + çok-worker) → D15-5/6/7/8.

---

# Ek Çıktılar

## 1. Risk Matrisi

| Olasılık ↓ / Etki → | Düşük | Orta | Yüksek/Kritik |
|---|---|---|---|
| **Yüksek olasılık** | D2-2 (tarih tutarsızlık), D7-4/5/6, D13-* (drift), D2-5 (any) | D4-2 (GET'te yazma), D5-1 (retry yok), D12-3 (login_failed), D6-1 (indekssiz FK) | — |
| **Orta olasılık** | D3-3/4/5/6, D5-3/4/5, D6-5/6, D8-2/3/4, D9-5 | D3-1 (CSWSH), D3-2 (eski jose), D4-1/3 (worker/sync-all), D6-2/3/4, D7-1/2/3, D9-1/2/3/4, D10-2/3, D11-2/4/6/7, D12-1/2/4/5, D13-1/6/7, D15-5/6/8 | **D2-4 (executor product_id bug)**, **D10-1 (bank_parser testsiz)** |
| **Düşük olasılık** | D1-4/5 | D1-1/2, D1-3, D11-1/3/5, D14-* (yatay ölçek), D15-2/3/4 | **D15-1 (DB yedeği — Kritik)** |

> **Yorum:** Tek **Kritik** (D15-1) düşük olasılık/felaket etki kadranında — ama gerçekleşirse geri dönüşü yok, bu yüzden 1 numara. İki **Yüksek** (D2-4, D10-1) orta-olasılık/yüksek-etki — finansal veri doğruluğuna dokunuyor. Yatay-ölçek bulguları (D14-*) bugün düşük olasılık (tek worker maskeliyor) ama büyümede kaçınılmaz.

## 2. Eksik Test Senaryoları Listesi

**Backend — Parser'lar (fixture gerektirir, D9-1/D10-1):**
1. `bank_parser.parse_pdf` — her banka formatı (Vakıfbank özel parser dahil): tutar/işaret/tarih/IBAN doğru mu
2. `bank_parser.parse_excel` — Excel ekstre → ParsedTransaction
3. `parse_turkish_number`/`parse_english_number`/`_detect_number_format` — `1.234,56` vs `1,234.56` (fixture'sız, hızlı)
4. `_repair_balance_gaps`/`_balance_chain_score` — eksik bakiye onarımı, yanlış sıra tespiti
5. `cc_statement_parser` — kredi kartı PDF (bilerek atlanmış)
6. `check_parser` / `vendor_parser` — çek + cari parse

**Backend — auto_tagger (çoğu fixture'sız, D9-3):**
7. `detect_payment_method` — havale/EFT/POS/çek/nakit (parametrize tablo)
8. `auto_tag_transactions` — kategori atama (overwrite=True/False)
9. `_extract_vendor_keywords` + `auto_match_vendors` — eşleştirme doğruluğu + yanlış-pozitif yok

**Backend — diğer:**
10. `sedna_client` saf kısımlar — row→dict, CP1254 decode, `320` prefix SQL (mock cursor, D9-5)
11. `tcmb.parse_tcmb_xml` — sabit XML → USD/EUR forex_buying/selling + EUR/USD parite (D10-3)
12. Harici-servis-kesintisi (chaos): Sedna down→503 + ayakta kalma; TCMB 404/timeout→graceful (D5)

**Frontend — Sayfa/E2E (şu an %0, D9-2):**
13. E2E smoke: login → dashboard (HttpOnly cookie auth)
14. E2E: CRUD akışı (avans/kullanicilar) ekle→düzenle→sil + ConfirmDialog
15. E2E: onay-akışı oluştur → talep → onayla→uygula
16. Bileşen-render: cariler/krediler kritik alt-akışları (MoneyInput, FIFO/eşleştirme)
17. WebSocket event-driven güncelleme (mock WS): online durum/yeni mesaj

## 3. Eksik Test Kullanıcıları ve Roller

**EKSİK YOK** — istenen dört fixture tam tanımlı ve aktif (conftest.py):
- `viewer_user_headers` (:331, tüm modüller can_view) · `use_user_headers` (:341, view+use) · `no_perm_user_headers` (:351) · `make_user_with_perms` factory (:360)
- Dinamik rol+kullanıcı üretimi `_create_user_and_login` (:265) ile her test izole; `_disable_admin_approval_workflows` sigortası mevcut.

**İyileştirme önerisi (eksik değil):** `make_user_with_perms` yalnız 3 dosyada kullanılıyor — modül-spesifik izin (bir modülde view, diğerinde use yok) senaryoları yaygınlaştırılabilir. **Edge-case fixture yok:** `is_active=False` kullanıcı, rolü silinmiş/`role_id=NULL` kullanıcı.

## 4. Eksik Mock Veri Setleri

1. **Banka ekstre örnek dosyaları** (`tests/fixtures/bank_statements/*.xlsx,*.pdf`) — HİÇ YOK; `bank_parser` için sıfır fixture (en kritik).
2. **TCMB XML örnek fixture + httpx mock** — YOK; tcmb.py %0.
3. **webpush mock** (`app.utils.push.send_push_to_user` / `pywebpush.webpush`) — YOK; yalnız "abonelik yok" yan etkisiyle dolaylı atlanıyor.
4. **Gerçek-format rezervasyon XLS fixture** — repoda commit'li DEĞİL; `/home/ec2-user/uploads/2025berk.xls`'e bağlı skipif ile CI'da atlanıyor → küçültülmüş PII-temiz kopya commit'lenmeli.
5. **Travelpayouts/Aviasales mock** — token-VARSA gerçek API yolunu test eden mock yok.
6. **Frontend WebSocket mock** — `websocket.svelte.ts` için test/mock yok.

**Mock'u DOĞRU olan (eksik değil):** Sedna pymssql — `sedna_configured` patch + `sys.modules['pymssql']` enjeksiyonu. Bu katman sağlam.

## 5. Dokümantasyon Drift Raporu

| # | Doküman:satır | Drift | Düzeltme |
|---|---|---|---|
| 1 | CLAUDE.md:261 | "1170+ test, %60 kapsam" → gerçek 1075 / %66 | "1075+ test, ~%66" |
| 2 | CLAUDE.md:240-244 | models/ yorumu 7+ model ailesi atlıyor (Personnel/Shift/Stock/SalesInvoice/AgencyGroup/PaymentInstruction) | Ekle veya "klasöre bak" notuna indir |
| 3 | CLAUDE.md tests/ | 54 dosyanın 32'si listede yok | Kategori özeti + `ls backend/tests/` |
| 4 | CLAUDE.md:236 | `banks_cc_match` router referansı → kaynak yok (yalnız stale .pyc) | Referansı kaldır + .pyc sil |
| 5 | api-haritasi.md:255 | WS `?token=JWT` → kod cookie auth (güvenlik-yanıltıcı) | "auth: HttpOnly cookie + auth-mesaj fallback" |
| 6 | CLAUDE.md:473-482 | Eski pg_dump test-DB kurulumu ↔ :352 yeni alembic (çelişki) | `scripts/setup-test-db.sh` ile hizala |
| 7 | docs/modules/ | `payment_instructions` + `system.server` için dedicated dosya yok | İki modül dokümanı oluştur |
| 8 | ui-kurallari.md | SegmentedControl + StatCard delta kanonik spec'te yok | Paylaşılan bileşen listesine ekle |

**Drift OTOMATİK yakalanmıyor** (ci.yml + tests/'te kod-doküman testi yok). **Temiz çıkanlar:** docs/modules tablosu↔disk (38=38), api-haritasi attendance/stok/yönetim/backup/server bölümleri, frontend vitest envanteri (274/22).

## 6. Güvenlik Açıkları Listesi

| Önem | Açık | Konum | Aksiyon |
|---|---|---|---|
| Orta | CSWSH — WS Origin kontrolü yok | ws.py:228-247 | Origin'i cors_origins ile karşılaştır, eşleşmezse `close(4403)` |
| Orta | Eski kripto bileşenleri (python-jose 3.3.0, passlib 1.7.4) | requirements.txt:8-9 | PyJWT'ye + modern bcrypt sarmalayıcıya geç |
| Orta | Login başarısızlığı kalıcı audit'te yok | auth.py:51-53 | `log_action('login_failed', ...)` + commit |
| Orta | SAST/dependency taraması yok | ci.yml | pip-audit + bandit + Dependabot |
| Düşük | access_token 24 saat, refresh yok | config.py:11 | 60-120 dk + sliding/refresh |
| Düşük | samesite=lax (strict değil) | auth.py:30,145 | strict + sunucu Origin kontrolü |
| Düşük | WEBP magic-byte eksik (offset-8 WEBP atlanıyor) | templates.py:475 | `content[8:12]==b'WEBP'` + file_validation'a taşı |
| Düşük | Ölü nginx register location | sprenses.conf:48-55 | Bloğu kaldır |
| Düşük | Frontend istemci-hata yakalama yok | hooks.client.ts yok | window.onerror→backend / Sentry |

**Doğrulanan güçlü duruş:** Gerçek SQLi yok (Sedna ham SQL girdileri istisnasız doğrulanmış), IDOR kapalı, RBAC her mutasyonda, JWT yalnız HttpOnly cookie, `/docs` public **404** (app sınırında localhost-only), path traversal korumalı.

## 7. Performans İyileştirme Listesi

| Öncelik | İyileştirme | Konum | Beklenen Etki |
|---|---|---|---|
| 1 | `quality/forms` GET'te yazma + N+1'i kaldır (job'a/tek sorguya al) | quality/forms/crud.py:43-69 | Her liste açılışında yazma transaction'ı + N+1 yok |
| 2 | Sedna `sync-all`'ı arka plana al (BackgroundTask → 202) + kısa retry | sedna_sync.py:104-145 | Nginx 504 riski yok, geçici kopmaya dayanıklı |
| 3 | `(is_matched, event_date)` composite/partial index | finance_event.py | Sıcak nakit-akım sorgusu hızlanır (büyümede) |
| 4 | Çok-worker (`--workers 2-4`) — *önce* D14-1/5 çözülmeli | service:13 | 2 çekirdek tam kullanım |
| 5 | Sedna fetch'lerinde `fetchmany`/sunucu-cursor + stok'ta tarih alt-sınırı | sedna_client.py:228 vb. | Büyük import'ta bellek tepesi yok |
| 6 | İzin-bazlı WS broadcast hedefleme | finance_broadcast.py:35-40 | 500 kullanıcıda gereksiz WS yazımı yok |
| 7 | Request-timing + slow-query log middleware | main.py | Performans regresyonu görünür |

## 8. Önceliklendirilmiş Teknik Borç Listesi

| Sıra | Borç | Risk | Efor | Kanıt |
|:---:|---|:---:|:---:|---|
| 1 | **Otomatik DB yedeği yok (DR sıfır)** | Kritik | Düşük | D15-1 |
| 2 | **`approval_executor` `product_id` bug + router drift** | Yüksek | Orta | D2-4 |
| 3 | **bank_parser ayrıştırma testsiz (%9)** | Yüksek | Orta | D10-1 |
| 4 | CI gate edemiyor + SAST/dependency taraması yok | Orta | Düşük-Orta | D11-1/3 |
| 5 | Observability/APM + gerçek health check yok | Orta | Orta | D15-3, D12-1 |
| 6 | Harici çağrılarda retry yok (Sedna/TCMB) | Orta | Düşük | D5-1, D15-6 |
| 7 | sales_invoices/collections DB UNIQUE yok + indekssiz sıcak FK'ler | Orta | Düşük | D6-2/1/3 |
| 8 | Service katmanı yok (router→router import) | Orta | Yüksek | D1-1/2 |
| 9 | E2E test yok + frontend sayfa %0 kapsam | Orta | Orta | D9-2 |
| 10 | Yatay ölçek engelleri (in-memory WS/cache/dosya) | Orta | Yüksek | D14-1/4/5 |
| 11 | API versiyonlama + response_model + retention | Orta | Orta | D7-1/2, D6-6, D12-4 |
| 12 | Büyük dosyalar (2232/1995) + doküman drift otomasyonu | Orta-Düşük | Orta | D2-1, D13-1 |

## 9. 30-60-90 Günlük İyileştirme Planı

**İlk 30 gün — "Kanamayı durdur" (Kritik + Yüksek + ucuz güvenlik):**
- 🔴 **Otomatik DB yedeği:** `pg_dump -Fc` günlük + off-site (S3, SSE) systemd timer + ilk **restore tatbikatı** (D15-1)
- 🟠 `approval_executor` `product_id`→`credit_product_id` bug'ını düzelt + BCH/KMH ödeme planı/finance_events handler'ını tamamla + regresyon testi (D2-4)
- 🟠 `bank_parser` saf yardımcıları (TR/EN sayı, format tespiti, bakiye-zinciri) için fixture'sız unit testler — hızlı kazanım (D10-1)
- CI'a `pip-audit` + `bandit` + `.github/dependabot.yml` + `svelte-check` adımı (D11-2/3)
- `health.py`'ye DB ping (gerçek readiness) (D5-2/D15-3)
- `login_failed` audit (D12-3) · prod'da `/docs` kapat veya nginx 404 (sertleştirme)

**İlk 60 gün — "Görünürlük + dayanıklılık":**
- Sentry (`@sentry-sveltekit` + `sentry-sdk[fastapi]`) → backend+frontend merkezi hata + alerting (D12-1/2)
- Sedna/TCMB'ye sınırlı retry/circuit-breaker (D5-1/D15-6)
- `sales_invoices/collections` DB UNIQUE + sıcak FK index'leri (tek migration, D6-2/1/3)
- Deploy akışına `alembic upgrade head` + atomik build-swap + ilk `git tag` rollback noktası (D11-5/6)
- Playwright ile 4-5 kritik akış E2E smoke + mobil viewport regresyon (D9-2/D8-1)
- `quality/forms` GET'te yazma/N+1 düzelt + Sedna sync-all arka plana (D4-2/3)

**İlk 90 gün — "Enterprise temel":**
- Redis: WS pub/sub + rate-limit + cache invalidation → çok-worker güvenli (D14-1/5)
- audit_logs/finance_events retention + aylık partition planı (D12-4/D14-3)
- Service katmanı çıkarımı (router→service→model; executor tek-kaynak) (D1-1/2)
- IaC (Dockerfile + compose) + staging ortamı + `ENVIRONMENT` ayrımı (D15-5)
- Yüklemeleri S3/EFS'e taşı (yatay ölçek için) (D14-4)
- En büyük 2 sayfayı (otel-rezervasyon, cariler) alt-bileşenlere böl (D2-1)
- Kod-doküman drift için otomatik pytest (D13-1)

**Enterprise için eksik parçalar:** Otomatik DB yedek + DR tatbikatı · Observability/APM/trace · gerçek readiness/liveness · E2E · SAST/dependency-scan · API versiyonlama · secret manager · IaC + Dockerfile · staging · yatay ölçek/HA (Redis) · blue-green/canary · refresh token.

## 10. Genel Proje Notu

# 72 / 100

**Gerekçe:** Ürün/uygulama katmanı **gerçekten üst-çeyrek** (güvenlik 8.5, mobil 8, performans 7.8, mimari/kalite/stabilite/DB ~7.5; finans iş mantığı 1075 testle, %66 kapsam, CI %60 eşik). Bu, çoğu KOBİ ERP'sinin üzerinde bir mühendislik disiplini. **Ancak** operasyon/platform katmanı (CI-gating, DR/yedek, observability, yatay ölçek) enterprise seviyenin altında ve **tek Kritik bulgu — otomatik DB yedeği yokluğu** — bir ERP için pazarlık konusu değil; notu tek başına sınırlıyor.

- **DB yedeği + iki Yüksek (D2-4 bug, D10-1 parser test) 30 günde kapatılırsa → ~78/100.**
- **90 günlük plan (observability + Redis + IaC + staging) tamamlanırsa → ~85/100 (enterprise eşiği).**

**Tek cümlede:** Güçlü bir ürün, zayıf bir platform sarmalında — kod kalitesi sizi yarı yola getirmiş; kalan yol mühendislik değil, **operasyonel olgunluk** (yedek, gözlemlenebilirlik, gate'li dağıtım, ölçek).

---

*Bu rapor 15 boyutta paralel uzman denetçilerle üretildi; her Kritik/Yüksek bulgu bağımsız bir ikinci ajanla koddan teyit edildi (çekişmeli doğrulama). "Doğrulanmış Risk" sütunları ve ✓ işaretli notlar bu ikinci geçişin sonucudur.*
