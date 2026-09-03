# Sprenses · Otel Yönetimi — Tasarımlar

Bu klasör tüm tasarımların **son hâlini** içerir (Temmuz 2026). Commit için hazırdır.

## İçerik

**Masaüstü**
- `Panel Yeniden Tasarım.dc.html` — genel yönetim paneli (KPI, T hesap cetveli, nakit koruma, onay kutusu)
- `Cariler Yeniden Tasarım.dc.html` — tedarikçi cari modülü: liste + ekstre + notlar (ekle/düzenle/sil/tik) + firma bilgileri (iletişim & IBAN)
- `Acente Mahsup & Nakit Akım.dc.html` — birleşik modül: rezervasyon + alınan avanslar + satış faturaları + nakit akım. Avans mahsubu, acenteye göre vadeli tahsilat, €11M yıl sonu ciro hedefi (mevcut rezervasyon + ek tahmin) ve runway projeksiyonu
- `Krediler Yeniden Tasarım.dc.html` — kredi portföyü (TL+EUR, EUR konsolide): master-detail + amortisman ödeme planı, taksit takvimi ay-akordiyonu, banka bazlı kredi zaman çizgileri; 6 kredi tipi, BSMV/komisyon, balon ödeme, erken kapama
- `Nakit Akım T-Hesap.dc.html` — **etkileşimli T hesap cetveli**: dönem sekmeleri (günlük/haftalık/aylık/yıllık) + tarih gezgini, Bekleyen/Gerçekleşen segmenti, sütun başlığına basınca kategori ↔ tarih (gün başlıkları) görünümü, faaliyet/finansman neti. GitHub'daki `CashFlowTAccount.svelte` temel alındı
- `Nakit Akım Yeniden Tasarım.dc.html` — önceki tasarım keşif kanvası (şelale / liste / faaliyet-finansman yönleri)
- `Nakit Koruma.dc.html` — ödeme erteleme + canlı runway projeksiyonu
- `Otel Rezervasyon Yeniden Tasarım.dc.html` — rezervasyon yönetimi

**Mobil**
- `Panel Mobil.dc.html`
- `Krediler Mobil.dc.html` — mobil kredi portföyü: hero özet, kredi listesi + drill-in detay (ödeme planı/amortisman), taksit takvimi, banka zaman çizgileri (iOS çerçevesi)
- `Nakit Akım Mobil.dc.html` — mobil T hesap: dönem/tarih gezgini, Bekleyen/Gerçekleşen segmenti, kategori ↔ tarih görünümü (iOS çerçevesi)
- `Otel Rezervasyon Mobil.dc.html`

**Runtime / bağımlılıklar**
- `support.js` — Design Component runtime (tüm `.dc.html` dosyaları buna bağlı)
- `ios-frame.jsx` — mobil prototiplerin iOS çerçevesi
- `index.html` — tüm tasarımlara bağlantı veren giriş sayfası

## Çalıştırma

`.dc.html` dosyaları tarayıcıda doğrudan `support.js` ile açılır. En sağlıklısı klasörü basit bir sunucuyla servis etmek:

```
python3 -m http.server
```

Ardından tarayıcıda `index.html` açılır.
