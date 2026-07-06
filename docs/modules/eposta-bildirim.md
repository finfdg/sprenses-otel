# E-posta Bildirim (SMTP) Modülü

Giden e-posta gönderimi — sistemin `bilgi@sprenses.com` kurumsal kutusundan
(TurkTicaret.net) e-posta göndermesini sağlayan altyapı. Bildirim sisteminin
**opsiyonel 4. kanalı**dır (DB kaydı + WebSocket + Web Push + **E-posta**).

## Genel Bilgi

| Alan | Değer |
|---|---|
| Amaç | Giden bildirim e-postası (SMTP) |
| SMTP sunucu | `smtp.turkticaret.net` (kutu: `bilgi@sprenses.com`) |
| Port | `465` (SSL) veya `587` (STARTTLS) |
| Açma/kapama | `.env` içindeki `SMTP_PASSWORD` — **boşsa özellik tamamen kapalı** (SEDNA_PASSWORD deseni) |
| Bloklama | Gönderim bloklayan I/O'dur → bildirimlerde arka plan thread'inde çalışır |

## Dosya Haritası

| Katman | Dosya | Görev |
|---|---|---|
| Config | `backend/app/config.py` | `smtp_host/port/use_ssl/user/password/from_name` ayarları |
| Helper | `backend/app/utils/mail.py` | `send_email()` + `is_mail_enabled()` |
| Bildirim | `backend/app/utils/notification.py` | `email=True` opt-in → arka planda e-posta (`_build_email_html`, `_build_email_payloads`, `_send_email_background`) |
| Endpoint | `backend/app/routers/notifications.py` | `POST /api/notifications/test-email` (deneme) |
| Frontend | `frontend/src/routes/dashboard/sistem/sunucu/+page.svelte` | "Deneme e-postası gönder" butonu (E-posta SMTP kartı) |
| Test | `backend/tests/test_mail.py` | 15 test (helper + escape + endpoint) |
| Şablon | `backend/.env.example` | SMTP bölümü |

## Ortam Değişkenleri (.env)

```env
SMTP_HOST=smtp.turkticaret.net
SMTP_PORT=465
SMTP_USE_SSL=true          # 465→true (SSL), 587→false (STARTTLS)
SMTP_USER=bilgi@sprenses.com
SMTP_PASSWORD=<kutu şifresi>   # BOŞSA e-posta gönderimi KAPALI
SMTP_FROM_NAME=Sprenses Otel
```

`SMTP_HOST/PORT/USER/FROM_NAME` için config.py'de varsayılan vardır; yalnız
`SMTP_PASSWORD` zorunludur (o da güvenlik gereği koda değil `.env`'e yazılır).

## Kullanım

### 1. Tek e-posta gönder (düşük seviye)
```python
from app.utils.mail import send_email

send_email(
    to="ornek@sprenses.com",
    subject="Konu",
    body_html="<b>Merhaba</b>",
    body_text="Merhaba",   # opsiyonel düz-metin yedeği
)  # -> True/False (SMTP kapalıysa False)
```

### 2. Bildirimi e-postayla da gönder (önerilen yol)
Mevcut bildirim akışına `email=True` eklemek yeterli — DB + WS + Push + e-posta
hepsi tek çağrıda gider, e-posta arka plan thread'inde (bloklamaz):
```python
from app.utils.notification import create_and_send_notifications_sync

create_and_send_notifications_sync(
    db, user_ids=[5, 8],
    type="onay_talebi",
    title="Yeni onay talebi",
    body="Bir harcama onayınızı bekliyor.",
    link="/dashboard/finans/onay",
    email=True,          # <-- e-posta kanalını aç
)
```
- `email=False` (varsayılan) → mevcut davranış aynen korunur; e-posta gönderilmez.
- `email=True` ama SMTP kapalıysa → e-posta payload'ı hiç üretilmez (no-op, sorgu yok).
- E-posta gövdesi `_build_email_html` ile **HTML-escape** edilir (başlık/gövde kullanıcı
  içeriği olabilir → stored/e-posta XSS'e karşı). Göreli `link` mutlak URL'ye çevrilir
  (`https://sprenses.com/...`), butona dönüşür.

### 3. Yapılandırmayı doğrula (deneme e-postası)
```
GET  /api/notifications/test-email/recipients   → [{id, name, email}, ...] (aktif kullanıcılar)
POST /api/notifications/test-email               → body { "user_id": <int|null> }
```
- İzin: `system.server` **use** (yönetici). Arayüzde **Sistem → Sunucu** sayfasındaki
  "E-posta (SMTP)" kartına (alıcı seçici + buton) bağlıdır.
- **Alıcı seçimi:**
  - `user_id` **verilirse** → o kullanıcının **tanımlı e-posta adresine** gider →
    o adresin gerçekten teslim aldığını da test eder (geçersizse `550` → 502).
  - `user_id` **verilmezse/null** → **sistem kutusuna** (`settings.smtp_user` =
    `bilgi@sprenses.com`) gider. Bu her zaman var olan güvenli öz-testtir; kullanıcı
    hesap e-postası (ör. `admin@sprenses.com`) gerçek bir posta kutusu olmayabilir →
    `550 Recipient address rejected`.
- E-posta gövdesinde "Test eden: <ad> (<e-posta>)" bilgisi yer alır (kimin test ettiği).
- SMTP kapalıysa **503**, kullanıcı yoksa **404**, gönderim başarısızsa **502**,
  başarılıysa `{ "success": true, "sent_to": "<alıcı e-postası>" }` (senkron — gerçek
  sonuç döner, böylece şifre/port/alıcı hatası anında görülür).

## Kurulum Adımları (canlıya alma)

1. Sunucudaki `backend/.env` dosyasına `SMTP_PASSWORD=<kutu şifresi>` ekle
   (ve gerekiyorsa diğer SMTP_* satırlarını — varsayılanlar TurkTicaret için doğru).
2. `sudo systemctl restart sprenses-api.service`
3. Yönetici hesabıyla `POST /api/notifications/test-email` çağır → gelen kutunu kontrol et.
4. Çalışıyorsa, e-posta ile bildirilmesi istenen olaylarda ilgili
   `create_and_send_notifications*` çağrısına `email=True` ekle.

## Geliştirme Kuralları / Kararlar

- **Güvenlik:** SMTP şifresi **yalnız `.env`'de** (kod default'u yok — CLAUDE.md güvenlik
  kuralı). `SMTP_USE_SSL=true` → `SMTP_SSL` (465); `false` → `starttls()` (587). Her iki
  yolda `ssl.create_default_context()` ile sertifika doğrulaması yapılır.
- **Bloklama yok:** SMTP el sıkışması saniyeler sürebilir → bildirim akışında e-posta
  **arka plan thread'inde** gönderilir (push ile aynı desen). `send_email()` doğrudan
  endpoint içinde çağrılırsa (deneme endpoint'i) 20 sn timeout ile bloklar — bu bilinçli,
  çünkü deneme senkron sonuç ister.
- **Kapalıyken sıfır maliyet:** `is_mail_enabled()` false ise e-posta için kullanıcı
  sorgusu bile yapılmaz.
- **Opt-in:** Hiçbir mevcut bildirim otomatik e-posta göndermez; her çağrı `email=True`
  ile açıkça istemelidir → gelen kutusu spam'lenmez.
- **Sessiz hata yok:** Gönderim hataları `logger.error/debug` ile loglanır.
