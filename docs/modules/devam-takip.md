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

## Veritabanı (2 tablo)
- `personnel`: id, full_name, employee_code (unique), department, phone, **access_token** (kişisel kimlik), is_active.
- `attendance_logs`: id, personnel_id (FK CASCADE), type (in/out), punched_at, source (phone_qr/manual), recorded_by (manuel ise yönetici FK), note.

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/attendance/kiosk/qr?key=` | KIOSK_KEY | Girişteki ekranın dönen QR'ı (SVG) |
| GET | `/attendance/kiosk-link` | hr.attendance view | Kiosk ekranı linki (KIOSK_KEY dahil) |
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
- **Dönen token:** `HMAC(SECRET, 15sn-pencere)` — 15sn'de değişir, ~30sn geçerli. **Evden basma imkânsız**
  (canlı ekranı taramadan token alınamaz) — asıl tehdit budur, çözülmüştür.
- **Kiosk QR endpoint'i `KIOSK_KEY` ister** (SECRET'ten türetilen, admin-only stabil anahtar) → token uzaktan çekilemez.
  - *Daha sıkı için (v2): kiosk endpoint'ini otel ağına IP-kısıtlamak.*
- **Personel kimliği:** kişisel `access_token` (tahmin edilemez) → çerez. Raw token API yanıtında **dönmez** (yalnızca QR'a gömülür).
- **Debounce:** aynı personel 30sn içinde tekrar basamaz (çift basış / replay sınırı).
- **Komut enjeksiyonu yok** (ORM), **rate limit** (setup/punch IP başına).
- **Bilinen sınır:** Telefonunu/kartını fiziksel olarak veren personel için "buddy-punch" tam engellenemez
  (biyometri olmadan). v2'de basış anı **selfie** ile caydırılabilir.

## Yönetici Paneli (İK → Devam Takip)
4 sekme: **İçeride** (canlı pano), **Personel** (CRUD + QR kart), **Geçmiş** (loglar), **Puantaj** (aylık toplam süre).
Toplam süre **`sa/dk`** olarak gösterilir (ör. `28 dk`, `8 sa 28 dk`) — ondalık saate yuvarlama yok
(28 dk yanlışlıkla "0,5 saat" görünmez). API hem `total_minutes` hem `total_hours` döndürür.
Ek aksiyonlar: "Kiosk Linki", "Elle Giriş/Çıkış" (telefonsuz/unutan için, audit'li).

## Audit Log
- entity_type: `personnel` (CRUD), `attendance` (manuel basış). Eylemler: create/update/delete/manual_punch.

## Geliştirme Kuralları
- Bu modül **onay akışından muaftır** (Sunucu/Yedekleme gibi ops/HR modülü).
- Kiosk QR yenileme `setInterval` kullanır — "polling yasak" kuralının **bilinçli istisnası** (kiosk display, WS ile taşınamaz).
- `segno` (saf-python QR) bağımlılığı eklendi.
