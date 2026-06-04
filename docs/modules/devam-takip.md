# Devam Takip (PDKS) Modülü

Otel personelinin **giriş/çıkış** takibi — girişteki ekranda **dönen karekod**, personel
kendi telefonunun **yerleşik kamerasıyla** okutarak basar.

## Genel Bilgi
- **Modül kodu:** `hr.attendance` (üst modül: `hr`)
- **Admin rota:** `/dashboard/ik/devam-takip` · **İzin:** `hr.attendance` (HR rolleriyle aynı)
- **Public rotalar (dashboard dışı, auth yok):** `/devam/ekran` (kiosk), `/devam/kur` (kurulum), `/devam` (basış)
- **Backend prefix:** `/api/attendance`

## Çalışma Akışı
1. **Kurulum (bir kez):** Yönetici her personel için QR kart üretir (panel → Personel → QR ikonu).
   Personel kartı telefonuyla okutur → `/devam/kur?t=<access_token>` açılır → **kimlik URL'dedir** (`?t=`).
   Personel sayfayı **ana ekrana ekler** (kalıcı kimlikli ikon).
2. **Giriş ekranı:** Yönetici "Kiosk Linki"ni alır (`/devam/ekran?key=<KIOSK_KEY>`), girişteki bir
   tablet/TV'de açar. Ekran ~10sn'de yenilenen **dönen QR** gösterir.
3. **Günlük basış:** Personel **kendi uygulamasını** açar (ana ekrandaki ikon) → **"Tara"** düğmesine basar →
   uygulama-içi kamera girişteki ekranın QR'ını okur → token + `?t=` kimliği `X-Pdks-Token` başlığıyla
   gider → son duruma göre **giriş/çıkış** kaydedilir → "Hoş geldin Ahmet ✅".

### ⚠️ iOS dersi — neden uygulama-içi tarayıcı (native kamera DEĞİL)
iOS Camera uygulaması bir QR'ı okutunca URL'i **izole/geçici bir bağlamda** açar; **her okutma ayrı bağlam**
olduğundan ne çerez ne de localStorage taşınır. Bu yüzden "girişteki ekranı telefonun kendi kamerasıyla
okut → `/devam?k=` bas" akışı iOS'ta **kalıcı çalışmaz** (punch isteği `header=False cookie=False` → 401 →
"Önce kurulum gerekli"). **Çözüm:** kimlik personelin **kendi URL'sinde** (`?t=`) durur ve tarama
**uygulama-içi** (`getUserMedia` + `jsqr`) yapılır → her şey tek, kalıcı bağlamda olur.
- `/devam` (native-scan landing) artık **basış denemez**; kimlik varsa `/devam/kur`'a yönlendirir,
  yoksa "kendi uygulamandaki Tara'yı kullan" talimatı gösterir.
- `/devam/kur?t=...&k=...` ile gelince (yönlendirme) **otomatik basar**.
- **Tanı:** `setup`/`me`/`punch` uçları journald'a `PDKS|...` satırı yazar (kimlik header/çerez/yok, UA,
  personel). Sayfalarda geçici "🔎 tanı kaydı" paneli aynısını ekranda gösterir. Sorun netleşince kaldırılabilir.

## Veritabanı (3 tablo)
- `personnel`: id, full_name, employee_code (unique), department, phone, **access_token** (kişisel kimlik), is_active.
- `attendance_logs`: id, personnel_id (FK CASCADE), type (in/out), punched_at, source (phone_qr/manual), recorded_by (manuel ise yönetici FK), note.
- `attendance_settings`: tek satır (id=1). **token_ttl_sec** (kiosk QR geçerlilik süresi, sn), updated_at.
  Panelden düzenlenir (5-120sn). Ekran yenileme süresi `max(2, ttl-3)` ile bundan türetilir.

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/attendance/kiosk/qr?key=` | KIOSK_KEY | Girişteki ekranın dönen QR'ı (SVG) |
| GET | `/attendance/kiosk/config?key=` | KIOSK_KEY | Ekran yenileme süresi (`refresh_sec`, `ttl_sec`) |
| GET | `/attendance/kiosk-link` | hr.attendance view | Kiosk ekranı linki (KIOSK_KEY dahil) |
| GET | `/attendance/settings` | hr.attendance view | QR ayarları (token_ttl_sec, refresh_sec, min, max) |
| PATCH | `/attendance/settings` | hr.attendance use | QR geçerlilik süresini değiştir (5-120sn) |
| POST | `/attendance/setup` | public (token) | Kişisel kurulum → kimlik çerezi |
| GET | `/attendance/me` | çerez | Personelin durumu (içeride/dışarıda) |
| POST | `/attendance/punch` | çerez + token | Giriş/çıkış kaydet |
| GET/POST/PATCH/DELETE | `/attendance/personnel[/{id}]` | hr.attendance | Personel CRUD |
| GET | `/attendance/personnel/{id}/qr` | hr.attendance view | Kişisel kurulum QR (kart) |
| GET | `/attendance/status` | hr.attendance view | Şu an içeride kim |
| GET | `/attendance/logs` | hr.attendance view | Geçmiş (filtreli) |
| GET | `/attendance/summary?month=` | hr.attendance view | Aylık puantaj (kişi başı saat/gün) |
| POST | `/attendance/manual` | hr.attendance use | Yönetici elle giriş/çıkış |

## Güvenlik / Sahtecilik Tasarımı
- **Zaman-damgalı token:** `<unix_ts>.HMAC(SECRET, ts)` — üretiminden **`token_ttl_sec` saniye** geçerli
  (varsayılan **7sn**, panelden 5-120 arası ayarlanır; pencere hizalama yok → süre net). **Bayat ekran
  görüntüsünü** etkisizleştirir: "fotoğrafı kaydet, sonra kullan" çalışmaz (süre sonunda → 400). Kiosk ekranı
  QR'ı `ttl-3` sn'de bir yeniler (ör. 7sn TTL → 4sn) → ekrandaki kod hep taze, meşru tarama kaçmaz.
  - **Panel → Ayarlar** (İK → Devam Takip): yönetici QR geçerlilik süresini değiştirir; ekran yenileme
    otomatik türetilir. DB: `attendance_settings` (tek satır). Audit: `update / attendance_settings`.
  - **Kiosk otomatik uyarlanır:** giriş ekranı ayarı **~15sn'de bir** kontrol eder (`/attendance/kiosk/config`);
    değişince yenileme aralığını **canlı** günceller (sayfa/elle yenileme gerekmez). Kiosk public+oturumsuz
    olduğu için kimlikli WS kullanılamaz → bu hafif kontrol kiosk-display istisnası kapsamındadır.
- **Kiosk QR endpoint'i `KIOSK_KEY` ister** (SECRET'ten türetilen, admin-only stabil anahtar) → güncel token
  **uzaktan çekilemez**. Yani personel **tek başına evden** canlı token'a erişip basamaz.
- **Personel kimliği:** kişisel `access_token` (tahmin edilemez) → kimlik. Raw token API yanıtında **dönmez** (yalnızca QR'a gömülür).
- **Debounce:** aynı personel 30sn içinde tekrar basamaz (çift basış / replay sınırı).
- **Komut enjeksiyonu yok** (ORM), **rate limit** (setup/punch IP başına).

### ⚠️ Bilinen sınır — canlı aktarım (relay) ve buddy-punch
Token **bayat** görüntüyü durdurur ama **canlı aktarımı durdurmaz**. Girişte bir **suç ortağı**,
canlı QR'ı **WhatsApp video / anlık ekran görüntüsü** ile evdeki personele gösterirse (**7sn içinde**),
evdeki personel **basabilir**. Bu, biyometri olmadan her "girişte kod tara" sisteminde olan **buddy-punch**
sınıfı bir zafiyettir. Tek başına bir personel bunu **yapamaz** (canlı token'a erişemez); **iş birliği** gerekir.
- **Uygulandı (2026-06):** QR geçerliliği **15→7sn**'ye düşürüldü → ekran-görüntüsü iletme penceresi daraldı
  (saniyeler içinde iletilip taranması gerekir; pratikte zorlaşır). Canlı videoyu tamamen durdurmaz.
- **En güçlü pratik önlem (uygulanmadı — operasyonel karar):** `punch`'ı **otel ağı IP'sine kısıtlamak**.
  Canlı-video aktarımında bile basış evdeki kişinin IP'sinden geleceği için reddedilir. Gerekli: otelin
  **sabit public IP'si** + personelin **otel Wi-Fi**'sinde basması (hücresel veri değil).
- Ek caydırıcı (uygulanmadı): basış anı **selfie** (denetim izi).
- **Karar (2026-06):** IP-kısıtlama/selfie şimdilik eklenmedi; QR süresi 7sn'ye çekilerek risk azaltıldı.
  İhtiyaç halinde diğer sertleştirmeler eklenebilir.

## Yönetici Paneli (İK → Devam Takip)
4 sekme: **İçeride** (canlı pano), **Personel** (CRUD + QR kart), **Geçmiş** (loglar), **Puantaj** (aylık toplam süre).
Toplam süre **`sa/dk`** olarak gösterilir (ör. `28 dk`, `8 sa 28 dk`) — ondalık saate yuvarlama yok
(28 dk yanlışlıkla "0,5 saat" görünmez). API hem `total_minutes` hem `total_hours` döndürür.
Ek aksiyonlar: "Kiosk Linki", "Elle Giriş/Çıkış" (telefonsuz/unutan için, audit'li).

## Audit Log
- entity_type: `personnel` (CRUD), `attendance` (manuel basış). Eylemler: create/update/delete/manual_punch.

## Gerçek Zamanlılık (canlı pano)
- Basış (telefon `punch` veya yönetici `manual`) sonrası backend **`attendance_updated`** WS event'i
  yayınlar (`manager.send_to_all_sync`). Yönetici paneli `onWsEvent(WS_EVENT.ATTENDANCE_UPDATED)` ile dinler
  ve **İçeride + Puantaj + (açıksa) Geçmiş**'i sessizce (skeleton flash'sız) tazeler → sayfa yenilemeye gerek yok.
- **Event PII içermez** (yalnızca `{type, action}`). Tüm bağlı kullanıcılara gider ama veri
  `require_permission(hr.attendance)` korumalı uçlardan çekildiği için yetkisiz kullanıcı içeriği göremez.
- Sabit tek kaynak: backend `WSEvent.ATTENDANCE_UPDATED` ↔ frontend `WS_EVENT.ATTENDANCE_UPDATED` (birebir).

## Geliştirme Kuralları
- Bu modül **onay akışından muaftır** (Sunucu/Yedekleme gibi ops/HR modülü).
- Kiosk QR yenileme + 15sn'lik ayar-kontrolü `setInterval` kullanır — "polling yasak" kuralının **bilinçli
  istisnası** (kiosk public+oturumsuz display, kimlikli WS taşınamaz). Yönetici panelindeki canlı güncelleme
  ise polling değil, **WS event-driven**'dir (yukarıdaki bölüm).
- `segno` (saf-python QR) bağımlılığı eklendi.
