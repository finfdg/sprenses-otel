# Yapay Zeka Asistanı (AI Asistan) — TASARIM / ÖNERİ

> **DURUM: PLAN — henüz uygulanmadı (2026-07-07).** Bu doküman bir tasarım önerisidir;
> kod yazılmadan önce gözden geçirilip onaylanmalıdır. Uygulandığında bu başlık
> "Uygulandı" olarak güncellenecek ve modül `CLAUDE.md`'deki modül listesine eklenecektir.

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

