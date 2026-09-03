# Acente Mahsup & Nakit Akım — Basit Tasarım (2026-07-19)

Repo hedefi: `scratchpad/tasarimlar/Sprenses Tasarımlar/` altına kopyalanabilir.

## Dosyalar
- `Acente Mahsup ve Nakit Akim.dc.html` — ana tasarım (masaüstü + <640px mobil düzen aynı dosyada).
  4 sekme: **Doluluk** (günlük/aylık, boş-fazla oda etiketleri, kırmızı "bugün" işareti) ·
  **Acenteler** (Acente Dağılımı — Bireysel/Gruplu, ReservationsPanel deseni) ·
  **Günlük Hareketler** (gün kartları → tıklayınca Aylık Doluluk Etkisi + hareket listesi) ·
  **Nakit Akım** (avans/fatura/mahsup/vadesi geçen KPI'ları, Tahsilat Takvimi, Acente Avans & Mahsup, Vadesi Geçen Alacaklar).
- `Telefon Onizleme.dc.html` — aynı sayfayı iPhone çerçevesinde (390px) gösteren simülasyon; `ios-frame.jsx` gerektirir.
- `support.js` — DC çalışma zamanı (dc.html dosyalarının yanında durmalı).
- `ios-frame.jsx` — iOS cihaz çerçevesi (yalnız telefon önizleme için).

## Notlar
- Tüm veriler deterministik ÖRNEK veridir; gerçek kaynaklar: `/sales/reservations/summary`,
  `/sales/daily-activity/*`, `/sales/acente-mahsup/`.
- Tema: lacivert #1b2b45 · pirinç #bd9a45 · krem zeminler (app.css token eşlemesiyle bire bir).
- Tweaks: kapasite (341 oda), başlangıç görünümü, ileri rezervasyon çizgisi.
