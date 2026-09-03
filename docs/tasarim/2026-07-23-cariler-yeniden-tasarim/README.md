# Cariler Modülü — Yeniden Tasarım (Sprenses Otel)

`finfdg/sprenses-otel` cariler modülünün lacivert/altın temaya sadık yeniden tasarım prototipleri.
Temsili veriyle çalışır; backend bağlantısı yoktur.

## Dosyalar
- `Cariler Yeniden Tasarim.dc.html` — Masaüstü sürüm (1440px). Sekmeler: Dosya Yükle / Cariler / Aylık Bakiye / Yıllık Ciro / Notlar / Ödeme Planı / Ödeme Talimatı.
- `Cariler Mobil.dc.html` — iPhone çerçeveli mobil sürüm (liste↔detay geçişli).
- `ios-frame.jsx` — Mobil sürümün kullandığı cihaz çerçevesi bileşeni.
- `support.js` — Tasarım bileşeni çalışma zamanı (dc.html dosyalarının açılması için gerekli, yan yana tutulmalı).

## Öne çıkanlar
- Sıralama: cari listesi pilleri (Ad/Bakiye/Borç/Alacak/Gecikmiş), hareket tablosunda 3 aşamalı kolon sıralama, plan/ciro/aylık görünümlerde ayrı sıralamalar.
- Aylık Bakiye: **FIFO Kalan** modu — havale/EFT, kredi kartı ve çek ödemeleri en eski faturadan düşülür; seçilen ayın faturalarından kalanı olan firmalar listelenir (kalanı olmayan gösterilmez). Dönem Sonu Bakiye modu ayrıca mevcuttur.
- Yıllık Ciro: firma bazında 2026 fatura hacmi, aylık dağılım çubukları (altın = zirve ay), pay yüzdesi.
- Vade düzenleme (FIFO yeniden hesaplar), ödeme yasağı onay akışı, notlar, IBAN yönetimi, ödeme talimatı listeleri.

## Not
Cari listesindeki "Gecikmiş" sıralaması backend `sort_by` whitelist'ine eklenmesi önerilen yeni bir anahtardır
(`calculate_overdue_by_vendor` zaten mevcut).
