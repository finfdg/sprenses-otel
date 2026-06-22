# Uçak Rezervasyon Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| Modül kodu | `sales.flight` |
| Üst modül | `sales` (Satış) |
| Frontend rota | `/dashboard/satis/ucak-rezervasyon` |
| Backend prefix | `/api/sales/flights` (yedek, aktif kullanılmıyor) |
| İzin seviyesi | `view` |
| Veri kaynağı | Travelpayouts (Aviasales) **JS Widget** |
| Veri kalitesi | Aviasales tam arama motoru — 20-30+ uçuş, gerçek zamanlı |
| Maliyet | Ücretsiz |
| Onay süreci | Yok — widget anında çalışır |

> **Güvenlik notu (2026-06-22):** Bu modülün affiliate'i **yalnız bu sayfaya kapsamlı** `tp.media/content`
> Aviasales widget'ıdır (`+page.svelte` içinde mount edilir). `app.html`'de ilk commit'ten beri duran
> **ayrı bir global** Travelpayouts "site doğrulama" script'i (`tp-em.com/NTIzMTU2.js`) vardı; her
> kimlik-doğrulamalı sayfada çalışıp uygulama-içi tıklamaları affiliate linklerine (klook) yönlendiriyor
> ve obfuscated 3rd-party kodu hassas DOM'a sokuyordu → **kaldırıldı**. Bu sayfanın widget'ı etkilenmez.
> Global affiliate/monetizasyon script'i app.html'e **tekrar eklenmemelidir**.

## Yaklaşım — Neden Widget, API Değil

Travelpayouts'un sunduğu seçenekler:

| Yöntem | Sonuç sayısı | Maliyet | Erişim |
|---|---|---|---|
| **Widget (kullanılan)** | 20-30+ uçuş | Ücretsiz | Anında |
| Flight Search API v1 | Gerçek arama | Ücretsiz | **50K MAU şartı** — otel için ulaşılmaz |
| `v3/prices_for_dates` | **1 sonuç/rota/gün** | Ücretsiz | Anında — ama yetersiz |

API yolu denendi:
- v3 ile sadece günlük en ucuz uçuş geliyor (kullanıcı şikayetçi oldu)
- v1 başvuru sayfasında "We only provide access to Projects with MAU starting from 50000" yazıyor
- Amadeus Self-Service yeni kayıt almıyor (Temmuz 2026 kapanış sürecinde)

Widget tüm bu kısıtları aşar — Aviasales'in kendi sitesindeki arama motoruyla aynı kaliteyi verir.

## Dosya Haritası

**Frontend (aktif)**
- `frontend/src/routes/dashboard/satis/ucak-rezervasyon/+page.svelte` — widget host sayfası

**Backend (yedek, kullanılmıyor)**
- `backend/app/utils/travelpayouts_client.py` — eski v3 REST client (ileride dönüş için)
- `backend/app/routers/sales/flights.py` — `/api/sales/flights/*` endpoint'leri (frontend artık çağırmıyor)

## Widget Konfigürasyonu

Frontend'de hardcoded URL:

```typescript
const WIDGET_SRC =
  'https://tp.media/content?' +
  'shmarker=722928' +              // Affiliate marker (komisyon takibi)
  '&promo_id=7879' +               // Search form widget tipi
  '&campaign_id=100' +             // Aviasales kampanyası
  '&locale=tr' +                   // Türkçe arayüz
  '&currency=try' +                // Türk Lirası
  '&color_button=%230d9488' +      // Teal buton (URL-encoded #0d9488)
  '&color_icons=%230d9488' +
  '&color_focused=%230d9488' +
  '&color_button_text=%23ffffff' + // Beyaz buton metni
  '&border_radius=8' +
  '&powered_by=true' +             // "Powered by Aviasales" yazısı
  '&searchUrl=www.aviasales.com';  // Arama sonuçları sayfası
```

Yeni renk/dil/varsayılan istenirse Travelpayouts dashboard'dan custom widget üretilip URL değiştirilir.

## Sayfa Yapısı

1. **Başlık** — Plane ikonu + "Uçak Rezervasyon" + "Aviasales arama motoru" alt başlığı
2. **Bilgi kutusu** — kullanıcıya widget'ın ne yaptığını anlatır (Skyscanner kalitesi vurgusu)
3. **Widget container** — `<div bind:this={widgetEl}>` — `onMount`'ta Travelpayouts script'i bu div'e enjekte edilir
4. **Hata durumu** — script `onerror` → loadFailed = true → kullanıcıya yükleme hatası mesajı
5. **Alt bilgi** — Affiliate ID gösterimi (transparan komisyon yapısı)

## Lifecycle

- **onMount:** Script DOM'a eklenir → tp.media JS'i yüklenir → form widget container'a render olur
- **onDestroy:** Sayfa terk edildiğinde script DOM'dan kaldırılır (memory leak önler)

## İzin Sistemi

`hasPermission('sales.flight', 'view')` kontrolü:
- `false` → "Bu sayfayı görüntüleme yetkiniz yok" mesajı
- `true` → widget yüklenir

Widget tıklayan kullanıcı Aviasales'e gider, orada arama sonuçları görünür ve isterse rezervasyon yapar. Bu sırada **biz seyahat acentası değiliz** — sadece affiliate yönlendirici. TURSAB üyeliği vb. gerekmez.

## Komisyon Akışı

```
Misafir → otel sayfası (widget) → arama formu doldur → submit
       → Aviasales (marker=722928 baked-in) → rezervasyon
       → Aviasales bilet satışını yapar → biz %1.5-3 komisyon kazanırız
       → Travelpayouts dashboard'da rapor görünür
```

## Backend Yedek (kullanılmıyor)

`travelpayouts_client.py` ve `routers/sales/flights.py` kodları korunuyor. İleride:
- Travelpayouts API kısıtları gevşerse
- 50K MAU eşiği geçilirse
- Veya kendi UI özelleştirmesi gerekirse

bu dosyalar üzerinden API tabanlı moda dönülebilir. Frontend page'de `WIDGET_SRC` yerine API çağrısı koymak yeterli (eski versiyon git history'de mevcut).

## Test Edilemeyenler

- Widget render: yalnızca tarayıcıda görülür (SSR shell boş döner — normaldir)
- Komisyon takibi: Travelpayouts dashboard `Performance → Bookings`
- Affiliate ID doğrulaması: widget submit edildiğinde Aviasales URL'inde `marker=722928` parametresi kontrol edilebilir
