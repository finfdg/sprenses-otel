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
   tablet/TV'de açar. **İki sütun:** SOL'da yalnız **dönen QR**, SAĞ'da **canlı son hareket**
   (kişi adı + departman + GİRİŞ/ÇIKIŞ + saat) ve **saat**. Sağ panel `/attendance/kiosk/recent?limit=1`'i
   **1sn'de bir** yoklar; yeni basış gelince ismi hemen değiştirir, **5sn** sonra otomatik siler
   (her yeni basış 5sn'lik silme zamanlayıcısını sıfırlar). İlk yüklemede yalnız son 5sn'lik basışı
   gösterir (eski kaydı göstermez). Kiosk-display istisnası.
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

### 📱 "Ana Ekrana Ekle" — kişiye özel manifest (kalıcılık)
**Sorun:** Global PWA manifest'i (`/manifest.json`) `start_url:"/"` taşır. Personel `/devam/kur`'u
ana ekrana eklediğinde, modern iOS/Android manifest'i onurlandırıp ikonu **köke (login ekranına)**
açıyordu. Ayrıca tarayıcı verisi/geçmişi silinince `localStorage` (tek kimlik kaynağı) gidiyordu.

**Çözüm — kişiye özel dinamik manifest:**
- Global manifest `app.html`'den kaldırıldı; **root layout** onu **yalnızca `/devam` DIŞINDA** ekler
  (`{#if !isDevam}`). Böylece yönetim PWA'sı korunur, `/devam` ondan etkilenmez.
- `/devam/kur` sayfası **kendi manifest'ini** verir: `GET /api/attendance/pdks-manifest?t=<token>` →
  `start_url:"/devam/kur?t=<token>"`, `scope:"/devam"`, `display:"standalone"`, ad = personelin adı.
- Sonuç: ana ekran ikonu **doğrudan kişisel basış sayfasını** (token'lı, standalone) açar — login'e
  gitmez. **start_url token taşıdığından**, tarayıcı geçmişi/verisi silinse bile ikon kimliği geri
  yükler (`?t=` → `localStorage`'a yeniden yazılır). Kur sayfası URL'de token yoksa `localStorage`'a düşer.
- Tüm uygulama SPA (`ssr=false`) olduğundan manifest linkleri istemci tarafında enjekte edilir
  (kurulum kullanıcı eylemi yüklemeden sonra olduğu için sorun değil).
- **Kalan tek kurtarma gereği:** personel verisini silip ana ekran ikonunu DA silerse → fiziksel
  QR kartı tekrar okutur (kimlik kartta gömülü).

## Veritabanı (3 tablo)
- `personnel`: id, full_name, employee_code (unique, **sicil no**), department, **title** (görev/ünvan), phone, **access_token** (kişisel kimlik), is_active.
- `attendance_logs`: id, personnel_id (FK CASCADE), type (in/out), punched_at, source (phone_qr/manual), recorded_by (manuel ise yönetici FK), note, **edited_at** (düzenlendiyse → mavi), **deleted_at** (soft delete → soluk gösterilir, aktif hesaplara girmez).
- `attendance_settings`: tek satır (id=1). **refresh_sec** (kiosk QR ekranda ne sıklıkta değişir, sn), updated_at.
  Panelden düzenlenir (2-120sn). Token güvenlik geçerliliği = `refresh_sec + 3` (grace) ile türetilir.

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/attendance/kiosk/qr?key=` | KIOSK_KEY | Girişteki ekranın dönen QR'ı (SVG) |
| GET | `/attendance/kiosk/config?key=` | KIOSK_KEY | Ekran yenileme süresi (`refresh_sec`, `ttl_sec`) |
| GET | `/attendance/kiosk/recent?key=` | KIOSK_KEY | Kiosk sağ paneli — son giriş/çıkış hareketleri (isim/tip/saat) |
| GET | `/attendance/kiosk-link` | hr.attendance view | Kiosk ekranı linki (KIOSK_KEY dahil) |
| GET | `/attendance/settings` | hr.attendance view | QR ayarları (refresh_sec, ttl_sec, min, max) |
| PATCH | `/attendance/settings` | hr.attendance use | QR yenileme süresini değiştir (2-120sn) |
| POST | `/attendance/setup` | public (token) | Kişisel kurulum → kimlik çerezi |
| GET | `/attendance/me` | çerez | Personelin durumu (içeride/dışarıda) |
| POST | `/attendance/punch` | çerez + token | Giriş/çıkış kaydet |
| GET/POST/PATCH/DELETE | `/attendance/personnel[/{id}]` | hr.attendance | Personel CRUD (sicil no + departman + görev) |
| POST | `/attendance/personnel/import` | hr.attendance use | Excel sicil listesi içe aktar (upsert; .xls/.xlsx) |
| GET | `/attendance/personnel/{id}/qr` | hr.attendance view | Kişisel kurulum QR (kart) |
| GET | `/attendance/personnel/cards.pdf` | hr.attendance view | Tüm aktif personel QR kartları (PDF, yazdırılabilir) |
| GET | `/attendance/status` | hr.attendance view | Şu an içeride kim |
| GET | `/attendance/logs` | hr.attendance view | Geçmiş (filtreli) |
| GET | `/attendance/summary?month=` | hr.attendance view | Aylık puantaj (kişi başı saat/gün) |
| POST | `/attendance/manual` | hr.attendance use | Yönetici elle giriş/çıkış (zaman seçilebilir; çift engelli; onay akışına tabi) |
| PATCH | `/attendance/logs/{id}` | hr.attendance use | Kaydı düzenle (tip/zaman/not; çift engelli; audit + onay) |
| DELETE | `/attendance/logs/{id}` | hr.attendance use | Kaydı sil — **soft delete** (deleted_at; soluk kalır); audit + onay |
| GET | `/attendance/logs/{id}/history` | hr.attendance view | Kaydın değişiklik tarihçesi (audit) + bekleyen işlem |
| GET | `/attendance/pending` | hr.attendance view | Bekleyen onay talepleri (ekle/düzenle/sil) + can_cancel |
| POST | `/attendance/pending/{request_id}/cancel` | hr.attendance use | Kendi bekleyen talebini iptal et |

## Güvenlik / Sahtecilik Tasarımı
- **Zaman-damgalı token:** `<unix_ts>.HMAC(SECRET, ts)` — geçerlilik = **`refresh_sec + 3` saniye**
  (knob = QR yenileme süresi; +3sn grace taze QR tarama payı; pencere hizalama yok → süre net). **Bayat ekran
  görüntüsünü** etkisizleştirir: "fotoğrafı kaydet, sonra kullan" çalışmaz (süre sonunda → 400). Kiosk ekranı
  QR'ı tam **`refresh_sec`** sn'de bir yeniler (girilen sayı = ekranda görülen değişim hızı) → kod hep taze.
  - **Panel → Ayarlar** (İK → Devam Takip): yönetici **QR yenileme süresini** (kaç sn'de bir değişsin)
    değiştirir; güvenlik geçerliliği `+3sn` ile türetilir. Düşük = güvenli/sık değişen, yüksek = sakin ekran.
    DB: `attendance_settings.refresh_sec`. Audit: `update / attendance_settings`.
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
Ek aksiyonlar: "Kiosk Linki", "Ayarlar", "Elle Giriş/Çıkış" (telefonsuz/unutan için, audit'li),
**"Excel İçe Aktar"** (sicil listesi) ve **"QR Kartları"** (toplu PDF).

## Sicil İçe Aktarma + Toplu QR Kart
- **Personel = sicil yapısı:** `employee_code` = **sicil no**, ayrıca `department` ve `title` (görev/ünvan).
- **Excel içe aktarma** (`POST /attendance/personnel/import`): `_parse_personnel_excel` başlık satırını otomatik
  bulur ('sicil' geçen), **Sicil No / Ad Soyad / Departman / Görev** kolonlarını TR-normalize başlıkla eşler
  (sıra/boş kolon önemsiz). `.xls` → xlrd 2.x, `.xlsx` → openpyxl. **Upsert** (sicil no anahtar): var olan
  güncellenir + reaktive edilir, yoksa yeni eklenir (`secrets.token_urlsafe` kişisel token üretilir).
  - **`replace=True` (modalda "mevcut personeli sil"):** içe aktarmadan **önce** TÜM personel
    (+ CASCADE ile giriş/çıkış kayıtları) silinir → temiz sicil listesi. **Sıra güvenli:** dosya
    doğrulandıktan (rows boş değil) **sonra** silinir; bozuk dosya veriyi silmez.
  - Personel listesi `page_size` üst sınırı **1000** (231+ personel tek sayfada gelir).
- **Personel listesi sıralama:** sütun başlıkları (`SortableHeader`) tıklanabilir — Ad Soyad / Sicil /
  Departman / Görev / Durum. Cycle: artan→azalan→temizle. **İstemci-taraflı** (liste tek seferde yüklü),
  Türkçe locale + sayısal sicil sıralaması (`localeCompare(..., 'tr', {numeric:true})`).
- **Toplu QR kart** (`GET /attendance/personnel/cards.pdf`): reportlab ile A4'e 2×5 kart/sayfa — her kartta
  kurulum QR'ı (`/devam/kur?t=…`) + ad + sicil + departman + görev. DejaVuSans (TR karakter). Yazdırılıp kesilir.
  Frontend "QR Kartları" butonu PDF'i yeni sekmede açar.

## Elle Giriş/Çıkış — Oluştur / Düzenle / Sil
Telefon basışı (`punch`) son duruma göre **otomatik** giriş/çıkış seçer → çift olamaz. Elle işlemlerde
(oluştur `manual`, düzenle `PATCH logs/{id}`, sil `DELETE logs/{id}`) yönetici tipi/zamanı kendi belirler;
bu yüzden korumalar eklendi:
- **Zaman girişi:** Elle oluştur + düzenlemede `datetime-local` ile **zaman seçilir** (varsayılan: şimdi).
  Naive değer backend'de `_localize()` ile **Europe/Istanbul**'a sabitlenir (tz-aware kolon tutarlılığı).
- **Durum tutarlılığı (`_assert_alternation`):** Hareketin **zaman-komşuları** (önceki/sonraki log) aynı tip
  olamaz → içerideki kişiye tekrar **giriş**, dışarıdakine tekrar **çıkış** **400** ile reddedilir.
  Düzenlemede kaydın **kendisi hariç** tutulur (`exclude_id`). Geriye-tarihli kayıtlarda da doğru.
- **Audit:** create/update/delete → `log_action(... "attendance" ...)` (kim, ne zaman, hangi kayıt).
- **Onay akışı:** Üç işlem de `check_approval(db, "hr.attendance", entity_id, user, action, payload)` çağırır
  (create→entity_id=0, update/delete→log id). hr.attendance için **aktif workflow** + talep edenin **rolü
  requestor** ise **202 → onaya düşer** (payload'da `punched_at` ISO olarak sabitlenir). Onaylanınca
  `approval_executor._handle_attendance` create/update/delete'i uygular. Eşleşen workflow yoksa (ör. admin)
  doğrudan uygulanır. Frontend 202'de "… onaya gönderildi" gösterir. Aynı log için bekleyen onay varsa **409**.

## Geçmiş — Durum Görünürlüğü (onay/düzenleme)
Geçmiş sekmesi kayıtların onay/düzenleme yaşam döngüsünü renkli gösterir:
- **Onay bekleyen** (ekle/düzenle/sil): **amber** satır + "Onay bekliyor · {işlem}" rozeti. Bekleyen **ekleme**ler
  henüz kayıt olmadığından `pendingCreates`'ten **sanal satır** olarak en üstte gösterilir.
- **Düzenlenmiş** (`edited_at`): **mavi** satır + "düzenlendi" rozeti.
- **Silinmiş** (`deleted_at`, soft delete): **soluk** (opacity) satır + üstü çizili + "Silindi" rozeti.
  Kayıt ekrandan **gitmez**; düzenle/sil butonları gizlenir (yalnız tarihçe). Aktif hesaplara
  (içeride / puantaj / kiosk / alternasyon) **dahil edilmez** — backend tüm aktif sorgularda `deleted_at IS NULL` filtreler.
- **Filtre çubuğu:** Tümü / Onay bekleyen / Düzenlenmiş / **Silinmiş** (chip). "Onay bekleyen" sayıyı gösterir.
- **Stat kart "Onay Bekleyen":** `GET /attendance/pending` sayısı (canlı, WS ile tazelenir).
- **İptal:** talep sahibi (`can_cancel`) kendi bekleyen talebini satırdaki **⃠** ile iptal eder
  (`POST /attendance/pending/{id}/cancel` → modül-içi, `system.approval` izni gerekmez).
- **Tarihçe (🕘):** her kayıtta `GET /attendance/logs/{id}/history` → audit zaman çizelgesi
  (oluşturma/düzenleme/silme; kim, ne zaman) + varsa bekleyen işlem. Audit `entity_id=log id` ile
  yazılır (hem doğrudan endpoint hem onay-executor); bu yüzden onaylı değişiklikler de tarihçede görünür.
  **Düzenleme detayı `eski→yeni` farkını gösterir** (`_edit_detail`): yalnızca değişen alanlar
  — `hareket: giriş→çıkış`, `zaman: 10:00→10:30`, `not: 'a'→'b'`. Zaman dk hassasiyetinde + Istanbul'a
  çevrilir (`astimezone(TZ)` — DB UTC tz döndüğü için; aynı düzeltme silme detayında da uygulandı).
- Bekleyen kayıtta düzenle/sil butonları gizlenir (çakışma + 409 önlemi); yalnızca tarihçe + iptal kalır.

## Audit Log
- entity_type: `personnel` (CRUD), `attendance` (manuel basış + kayıt düzenle/sil), `attendance_settings` (QR ayarı).
  Eylemler: create/update/delete/manual_punch.

## Gerçek Zamanlılık (canlı pano)
- Basış (telefon `punch` veya yönetici `manual`) sonrası backend **`attendance_updated`** WS event'i
  yayınlar (`manager.send_to_all_sync`). Yönetici paneli `onWsEvent(WS_EVENT.ATTENDANCE_UPDATED)` ile dinler
  ve **İçeride + Puantaj + (açıksa) Geçmiş**'i sessizce (skeleton flash'sız) tazeler → sayfa yenilemeye gerek yok.
- **Event PII içermez** (yalnızca `{type, action}`). Tüm bağlı kullanıcılara gider ama veri
  `require_permission(hr.attendance)` korumalı uçlardan çekildiği için yetkisiz kullanıcı içeriği göremez.
- Sabit tek kaynak: backend `WSEvent.ATTENDANCE_UPDATED` ↔ frontend `WS_EVENT.ATTENDANCE_UPDATED` (birebir).
- **Onay-tetikli tazeleme:** Elle giriş onaya düştüyse, kayıt **`attendance_updated`** yaymaz (executor
  içinden değil). Onay verilince akış **`approval_status_changed` (`module_code=hr.attendance`)** yayınlar —
  bu event **kayıt commit edildikten SONRA** gider. Panel ayrıca bunu dinler ve `module_code` eşleşince
  tazeler → onay anında yeni kayıt panoda **anlık** belirir. (Onay akışı zaten bu event'i yaydığı için
  executor'a ek broadcast eklemeye gerek kalmadı.)

## Geliştirme Kuralları
- **Onay akışı:** Yalnızca **elle giriş/çıkış** (`POST /attendance/manual`) onaya tabidir (yukarıdaki bölüm).
  Telefon `punch` (self-servis, app-user'a bağlı değil), personel CRUD ve ayarlar onaydan **muaftır**.
  `_HANDLERS["hr.attendance"]` = `_handle_attendance` (create) — `tests/test_approval_system.py` AST testlerinden geçer.
- Kiosk QR yenileme + 15sn'lik ayar-kontrolü `setInterval` kullanır — "polling yasak" kuralının **bilinçli
  istisnası** (kiosk public+oturumsuz display, kimlikli WS taşınamaz). Yönetici panelindeki canlı güncelleme
  ise polling değil, **WS event-driven**'dir (yukarıdaki bölüm).
- `segno` (saf-python QR) bağımlılığı eklendi.
