# Yapay Zeka Asistanı (AI Asistan)

> **DURUM: FAZ 1 + FAZ 2 UYGULANDI (2026-07-07) — okuma + onay-akışlı yazma canlıda.**
>
> **⚠️ ÇALIŞMASI İÇİN GEREKEN TEK ADIM:** `backend/.env`'e geçerli bir
> `ANTHROPIC_API_KEY=...` yaz ve `sudo systemctl restart sprenses-api.service`.
> Anahtar boşsa endpoint 503 döner, arayüz "yanıt veremedim" gösterir (güvenli).

## Sunum: Markdown + Grafik (2026-07-07)

- **Markdown render (güvenli):** Asistan yanıtları `marked` ile render edilir (tablo, kalın,
  liste, başlık). LLM çıktısı olduğundan ÖNCE tüm HTML escape edilir (`&`,`<`,`>`), sonra
  yalnız markdown sözdizimi işlenir → ham `<script>`/HTML geçemez. Sistem promptu modeli
  **tablo** kullanmaya yönlendirir (çok-kalemli veri düz cümle değil tablo olur).
- **Grafik (`grafik_olustur` aracı + `AiChart.svelte`):** Model, karşılaştırma için `tip=bar`,
  trend için `tip=line` ile bir grafik spec'i (`{tip, baslik, para_birimi, seri:[{etiket,deger}]}`)
  döndürür; `/sor` yanıtı `grafikler[]` taşır; frontend hafif **SVG** olarak çizer (harici
  kütüphane YOK — projedeki elle-SVG deseni). Grafik verisi yapısaldır (sayı+etiket) ve Svelte
  ile escape'li render edilir → XSS yok. Grafik tool'u mutasyon yapmaz; veri izin-kontrollü
  okuma araçlarından gelir. Bar etiketleri kompakt (7,6 Mn), tam değer `title`'da.
- **Mobil tablo (kart görünümü):** `<640px`'te markdown tabloları **etiket:değer kart**
  düzenine geçer (projenin tablo→kart standardı). `enhanceTables` action'ı render sonrası
  her `<td>`'ye başlık metnini `data-label` olarak ekler; CSS `::before` ile mobilde
  "Başlık: değer" satırları gösterilir (yatay kaydırma yok). Masaüstü normal tablo. Asistan
  balonu mobilde daha geniş (`max-w-[92%]`), grafik etiketleri de responsive (`w-20 sm:w-28`).

## Dışa Aktarma + Günlük Özet (2026-07-07)

- **Excel/PDF dışa aktar:** Asistan yanıtındaki tablonun altında Excel/PDF butonları.
  Frontend markdown tabloyu (`parseTables`) çıkarır → `POST /api/ai/disa-aktar` →
  backend `utils/ai_export.py` (openpyxl `.xlsx` / reportlab `.pdf`, Türkçe+₺ için DejaVu
  font) dosyayı üretir → blob indirilir. İzin: `ai.asistan` view. Frontend'de export
  kütüphanesi YOK — üretim backend'de.
- **`gunun_ozeti` aracı:** "Bugünün özeti" sorulunca yaklaşan ödemeler + vadesi gelen
  çekler + bugünkü rezervasyon girişleri (her bölüm yalnız izin varsa). `ai_service.compute_digest`
  hem bu tool'u hem sabah bildirim script'ini besler.
- **Sabah proaktif bildirim (systemd timer):** `scripts/ai-daily-digest.py` her sabah
  **08:00 (Europe/Istanbul)** çalışır; finans-görme yetkili kullanıcılara yaklaşan ödeme
  özetini in-app+WS+push bildirim (`create_and_send_notifications_sync`, type `ai_digest`,
  link `/dashboard/asistan`) olarak gönderir. Yaklaşan ödeme yoksa gönderilmez (gürültü yok).
  **Timer birimleri `/etc/systemd/system/sprenses-ai-digest.{service,timer}` — git'te DEĞİL**
  (TZ drop-in gibi); sunucu yeniden kurulursa TEKRAR kurulmalı. Script git'tedir.

## Faz 2 — Uygulanan (2026-07-07): Onay-akışlı yazma

**İki-adımlı güvenli tasarım (öner → onayla → uygula):**
1. **Öner (chat döngüsü):** Claude'a verilen `cari_vade_degistir` / `cek_durum_degistir`
   araçları **ASLA mutasyon yapmaz** — yalnız doğrular ve bir öneri döndürür
   (`ai_service._propose_*`). `/sor` yanıtı `bekleyen_islem` alanıyla döner.
2. **Onayla (arayüz):** Frontend `ConfirmDialog` ile öneriyi kullanıcıya gösterir
   ("… vadesi 90 → 45 gün olarak güncellenecek. Onayla ve Uygula").
3. **Uygula (ayrı endpoint):** Onaylanınca `POST /api/ai/uygula` → `ai_service.execute_action()`.

**execute_action güvenlik katmanları (hepsi test edildi — `tests/test_ai_assistant.py`):**
- (1) Bilinen aksiyon (`_WRITE_ACTIONS` registry; keyfi işlem reddedilir)
- (2) Hedef modül **can_use** izni (`user_can`) + endpoint `require_permission("ai.asistan","use")`
- (3) **Payload whitelist** (yalnız `allowed_keys`) + değer doğrulama (negatif vade, geçersiz durum)
- (4) Varlık doğrulama (404 → "kayıt bulunamadı")
- (5) **`check_approval()`** — router endpoint'iyle **BİREBİR** aynı modül/aksiyon/payload
  anahtarları (`finance.cariler`→`{payment_days}`, `finance.checks`→`{new_status}`). Onay
  gerekiyorsa mutasyon YAPILMAZ, talep oluşur; onaylanınca mevcut executor handler uygular.

**Uygulanan yazma aksiyonları (`_WRITE_ACTIONS` registry — `action_type` create/update):**

| action_key | Tür | Modül | Service (router↔executor ORTAK) | Öner aracı |
|---|---|---|---|---|
| `cari_vade` | update | finance.cariler | `vendor_service.apply_vendor_update({payment_days})` | `cari_vade_degistir` |
| `cari_durum` | update | finance.cariler | `vendor_service.apply_vendor_update({status})` — ödeme yasağı | `cari_odeme_yasagi` |
| `cek_durum` | update | finance.checks | `check_service.apply_check_status(new_status)` | `cek_durum_degistir` |
| `avans_ekle` | create | finance.avanslar | `advance_service.create_advance` (tarih coercion) | `avans_ekle` |
| `duzenli_odeme_ekle` | create | accounting.recurring | `ScheduledDefinition` + `scheduled_service.post_create` (executor mirror) | `duzenli_odeme_ekle` |

Hepsi router endpoint'iyle **birebir** aynı modül/aksiyon/payload anahtarlarını kullanır →
onay gerekirse mevcut executor doğru uygular; onay gerekmezse aynı service çağrılır (sapma yok).
Audit: `ai_execute` eylemi. **create** aksiyonlarında `entity_id=0`, onay gerekirse executor
payload'dan üretir (recurring'de UI "Onayda" ön-kaydı yapılmaz — talep Onay modülünde görünür).

**Not (recurring):** cari-bağlı düzenli ödeme (Elektrik→CK vb.) asistandan kurulmaz —
`vendor_id` her zaman None (bağımsız planlı gider). Cari senkronu modülden yapılır.

---

## Faz 1 — Uygulanan Dosyalar (2026-07-07)

| Katman | Dosya | Not |
|---|---|---|
| Config | `backend/app/config.py` | `anthropic_api_key`, `anthropic_model` (varsayılan `claude-opus-4-8`) |
| Servis | `backend/app/services/ai_service.py` | 3 okuma tool'u + Claude tool-use döngüsü; her tool `user_can` izin kontrollü |
| Router | `backend/app/routers/ai_assistant.py` | `POST /api/ai/sor` — `require_permission("ai.asistan","view")` + audit (`ai_query`) |
| Kayıt | `backend/app/main.py` | router `/api/ai` prefix'iyle include |
| Migration | `alembic/.../b8e5c2f1a9d7_add_ai_asistan_module.py` | `ai` + `ai.asistan` modülleri + Admin izni |
| Frontend | `frontend/src/routes/dashboard/asistan/+page.svelte` | Sohbet arayüzü (tasarım sistemi: PageHeader/Button/Lucide/AA) |
| Nav | `frontend/src/lib/config/navigation.ts` + `Sidebar.svelte` | Özel top-level "Asistan" linki + route guard |

**Okuma tool'ları (izin-kontrollü, `{_error}` → "erişim izniniz yok"):**
`nakit_akim_ozeti` (finance.cash_flow, para-bazlı), `bekleyen_cekler` (finance.checks),
`cari_borc_ozeti` + `cari_detay` (finance.cariler — vade/durum/bakiye), `kredi_durumu`
(finance.krediler), `yaklasan_odemeler` (finance.cash_flow — N günde vadesi gelen giderler),
`rezervasyon_ozeti` (sales.hotel_reservation — adet/oda/geceleme/ciro). Ayrıca `grafik_olustur`
(görsel — bar/line).

**Konuşma sürekliliği (hafıza, 2026-07-07):** `/sor` isteği `gecmis: [{rol, metin}]` alır;
frontend son 12 turu gönderir; `ai_service._seed_messages` bunları modele bağlam olarak ekler
(ilk mesaj user'a normalize, tur başına 6000 karakter sınırı). Böylece "peki en borçlusunun
vadesi ne?" gibi **takip soruları** çalışır. Geçmiş istemciden geldiği için güvenlik: okuma
araçları izin-kontrollü, yazma araçları `execute_action`'da yeniden doğrulanır → sahte geçmiş
en fazla yanıt metnini etkiler, veri/işlem güvenliğini bozamaz.

**Banka bakiyeleri:** `banka_bakiyeleri` (finance.banks) her aktif hesabın **son işlem
bakiyesini** (window function, `banks.py` deseni) para birimine göre toplar (EUR/TRY/USD ayrı).

**Streaming (akan yanıt, 2026-07-07):** `POST /api/ai/sor-stream` — SSE (`text/event-stream`).
`ai_service.answer_question_stream` generator'ı tool turlarını arka planda döndürür, final metni
**token token** yield eder (`{"t":"delta","v":...}` → sonda `{"t":"meta",...}`). Router kendi DB
oturumunu açar (stream süresince yaşamalı); `X-Accel-Buffering: no` ile nginx buffer'lamaz (canlı
doğrulandı: token'lar ~7 sn'ye yayılı geldi). Frontend `fetchRaw` + `ReadableStream` ile tüketir,
boş asistan balonuna deltaları akıtır; meta'da tablo/grafik/bekleyen_işlem uygulanır. Tool işleme
tek kaynakta (`_run_tool_block`) — hem `answer_question` hem stream ORTAK kullanır.

**Panel "Günün Özeti" kartı:** `GET /api/ai/gunun-ozeti` (deterministik, AI çağrısı YOK →
`compute_digest`); Panel'de KPI'ların altında `AiDigestCard.svelte` (yaklaşan ödemeler/çekler/
rezervasyon; `hasPermission('ai.asistan')` ile gösterilir).

**Çoklu para birimi (2026-07-07 düzeltme):** `nakit_akim_ozeti` gelir/gider/net'i **para
birimine göre AYRI** döndürür (EUR/TRY/USD). `finance_events.amount` her zaman kaydın kendi
para birimindedir; `amount_try` çoğu kayıtta NULL. Eski hâli `coalesce(amount_try, amount)`
yapıp hepsini "TRY" etiketliyordu → 250.000 EUR giriş "250.000 TL" görünüyordu. Artık
`GROUP BY currency` ile ayrılır; farklı birimler TOPLANMAZ (kur tahminine gerek yok).

---

## 1. Genel Bilgi

- **Amaç:** Kullanıcıların doğal dilde ("bu ay nakit akışı nasıl?", "en çok borçlu 5 cari kim?",
  "3.500 TL'lik su faturasını düzenli ödemelere ekle") soru sorabildiği, verileri okuyup
  raporlayan **ve** kayıt oluşturma/değiştirme işlemlerini **mevcut onay akışının içinden**
  başlatabilen bir asistan.
- **Modül kodu (öneri):** `ai.asistan`
- **Frontend rota (öneri):** `/dashboard/asistan`
- **Backend prefix (öneri):** `/api/ai`
- **Model:** `claude-opus-4-8` (Anthropic API — adaptif düşünme + prompt caching)
- **Kullanıcı kararı (2026-07-07):** Okuma + yazma + raporlama = tam yetki. **Kritik uyarlama:**
  Tam yetki, güvenlik korumalarını atlayarak DEĞİL, korumaların **içinden** geçerek verilir
  (aşağıda §4).

## 2. Neden "MCP" değil, "Claude API + tool use"

- Şu an `.mcp.json`'daki postgres/playwright/github MCP server'ları **geliştirme-zamanı**
  araçlarıdır (Claude Code ajanına DB/tarayıcı erişimi verir). **Son kullanıcı** bunları
  kullanmaz — canlı uygulamada çalışmazlar.
- Uygulama içi asistan, **Anthropic Claude API**'sini **tool use (function calling)** ile
  kullanır: Claude, bizim FastAPI'de tanımladığımız güvenli fonksiyonları (tool) çağırır;
  ham SQL ne kullanıcı ne de Claude tarafından yazılır.

## 3. Mimari

```
Svelte sohbet arayüzü  (frontend .../asistan)
        │  fetch(credentials: "include")   — HttpOnly cookie ile auth (mevcut kural)
        ▼
FastAPI  POST /api/ai/sor   (routers/ai_assistant.py)
        │  require_permission("ai.asistan", "view")   — kapı 1
        │  Anthropic SDK (streaming) — claude-opus-4-8, adaptive thinking
        ▼
Claude API + tool use (agentic loop, backend'de yönetilir)
        │  Claude tool çağırır ──► bizim tool fonksiyonlarımız
        ├─ OKUMA tool'ları → services/ (salt-okuma) → PostgreSQL
        └─ YAZMA tool'ları → check_approval() + require_permission() + audit → services/
```

- Agentic loop **backend'de** döner (Python SDK tool runner veya manuel döngü). Frontend yalnız
  kullanıcı mesajını gönderir ve stream'i gösterir.
- Sistem promptu Türkçe: "Sadece Türkçe yanıt ver, doğru Türkçe karakter kullan…" + kullanıcının
  rolü/izinleri + o anki tarih (İstanbul TZ).

## 4. Güvenlik — "Tam yetki" nasıl güvenli verilir (KRİTİK)

Bu modülün en önemli tasarım kararı. Asistan finansal ERP'ye eriştiği için, tam yetki
**mevcut üç kapıyı atlamadan** verilir:

1. **İzin sistemi (RBAC) — veri sızıntısını engeller.**
   - Her tool çağrısı, **isteği yapan kullanıcının** `can_view`/`can_use` izinlerine tabidir.
   - Tool fonksiyonu, ilgili modül için `hasPermission` benzeri bir kontrol yapar; kullanıcı
     göremediği bir modülün (ör. cari bakiye) verisini asistana **sordurtamaz**. Aksi halde
     düşük yetkili bir personel, asistan üzerinden yetkisiz veri çekebilir.
   - Tool'lar `current_user`'ı parametre olarak alır (Claude'dan gelmez — sunucu enjekte eder).

2. **Onay akışı — yetkisiz mutasyonu engeller.**
   - YAZMA tool'ları asla doğrudan `INSERT/UPDATE/DELETE` yapmaz. Bunun yerine ilgili
     **domain service**'i (ör. `scheduled_service`, `vendor_service`) `check_approval()` ile
     çağırır — tıpkı router endpoint'lerinin yaptığı gibi.
   - Onay gereken bir işlemse endpoint 202 mantığıyla **onay talebi oluşturulur**; asistan
     kullanıcıya "Talebiniz onaya gönderildi" der. Asistan, onay akışını **atlatamaz**.
   - Bu, CLAUDE.md'deki "Tüm POST/PATCH/DELETE onay kontrolünden geçmelidir" kuralını
     asistan için de zorunlu kılar.

3. **Audit — izlenebilirlik.**
   - Her yazma tool'u `log_action(...)` ile audit'e yazılır; `entity_type` ör.
     `ai_assistant_action`, details'te asistanın çağırdığı tool + parametreler.
   - Ayrıca ham AI konuşmaları (soru/cevap) ayrı bir tabloda saklanabilir (ör. `ai_conversations`)
     — sorumluluk ve hata ayıklama için.

**Prompt injection savunması:** Kullanıcı mesajı ve DB'den dönen veriler **güvenilmez** kabul
edilir. Model, yalnız tanımlı tool'ları çağırabilir (keyfi SQL yok); yazma tool'ları her hâlükârda
onay+izin+audit'ten geçtiği için, kötü niyetli bir prompt bile korumaların ötesine geçemez.

## 5. Tool Listesi (öneri — fazlı)

### Faz 1 — Okuma (düşük risk)
| Tool | Ne yapar | Bağlı service |
|---|---|---|
| `nakit_akim_ozeti(donem)` | Aylık/haftalık nakit giriş-çıkış özeti | cash_flow |
| `bekleyen_cekler()` | Vadesi yaklaşan/bekleyen çekler | check_service |
| `cari_bakiye(arama)` | Cari bakiye/borç sorgusu (izin kontrollü) | vendor_service |
| `doluluk_ozeti(tarih)` | Rezervasyon/doluluk özeti | reservation_service |
| `bekleyen_onaylar()` | Kullanıcının bekleyen onay taleplerini listeler | approval |

### Faz 2 — Yazma (onay akışının içinden)
| Tool | Ne yapar | Koruma |
|---|---|---|
| `duzenli_odeme_ekle(...)` | Düzenli ödeme tanımı oluşturur | `check_approval("accounting.recurring", 0, user, "create", data)` |
| `cari_vade_guncelle(...)` | Cari vade/durum günceller | `check_approval("finance.cariler", id, user, "update", data)` |
| `cek_durum_guncelle(...)` | Çek durumunu günceller | `check_approval("finance.checks", id, user, "update", data)` |

> Her yazma tool'u, ilgili router endpoint'iyle **aynı service fonksiyonunu** çağırır (CLAUDE.md
> D1-2 deseni) → sapma/çift-bakım riski olmaz.

## 6. Maliyet Tahmini (kaba)

- `claude-opus-4-8`: girdi **$5 / 1M token**, çıktı **$25 / 1M token**.
- Sistem promptu + tool tanımları (~5K token) **prompt caching** ile ~%90 ucuzlar (cache read ≈ 0.1×).
- Tipik bir soru (birkaç tool round-trip dâhil): kabaca **~$0.03–0.10**.
- Aylık 500 soru → **~$15–50/ay**; 2.000 soru → **~$60–200/ay**. Kullanım arttıkça lineer artar.
- Maliyet kontrolü: caching zorunlu, gereksiz uzun bağlam gönderme, `effort` ayarı, günlük/kullanıcı
  başı kota.

## 7. Frontend (tasarım sistemi zorunlu)

- Referans: iki-panel sohbet deseni (mevcut **Mesajlaşma** modülüne benzer autogrow input),
  ama tek panel yeterli olabilir.
- Bileşenler: `PageHeader`, `Button`, `MoneyInput` (gerekirse), Lucide ikonlar, AA kontrast,
  `showToast` hata yönetimi. Native `confirm()` yasak → `ConfirmDialog`.
- Streaming: token token yanıt gösterimi (WebSocket veya SSE/stream fetch). Polling yasak.
- Yazma işlemi öncesi **kullanıcı onayı**: asistan "şu kaydı ekleyeceğim, onaylıyor musun?"
  diye `ConfirmDialog` gösterir; kullanıcı onaylayınca tool çalışır (çift güvenlik).

## 8. Uygulama Fazları

1. **Faz 0 — Altyapı:** `.env`'e `ANTHROPIC_API_KEY`, `pip install anthropic`, `config.py`'ye
   ayar, `ai.asistan` modülü + RBAC izinleri, `services/ai_service.py` iskeleti.
2. **Faz 1 — Okuma prototipi:** 3–4 okuma tool'u + `/api/ai/sor` (streaming) + basit sohbet sayfası.
   İzin kontrolü + audit. Canlıda dene.
3. **Faz 2 — Yazma:** onay-akışlı yazma tool'ları (service'leri yeniden kullanarak) +
   ConfirmDialog akışı + regresyon testleri.
4. **Faz 3 — Sertleştirme:** kota/rate limit, konuşma saklama, maliyet paneli, prompt injection
   testleri, doküman + `CLAUDE.md` modül listesi güncelleme.

## 9. Açık Riskler / Kararlar

- **Halüsinasyon:** Model, veriyi tool sonucundan almalı; "veriyi uydurma, yalnız tool sonucuna
  dayan" talimatı + kritik rakamlarda tool zorunluluğu.
- **Maliyet kayması:** Kullanım artarsa aylık fatura büyür → kota + izleme şart.
- **İzin kapsamı:** Asistanın erişebileceği tool seti, kullanıcının izinleriyle **dinamik**
  daraltılmalı (yetkisi olmayan modülün tool'u hiç sunulmamalı).
- **Onaylı yazma UX'i:** Asistan üzerinden başlatılan işlem onaya düşünce, kullanıcı bunu Onay
  modülünde de görebilmeli (mevcut akışla tutarlı).
```

