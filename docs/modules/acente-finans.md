# Acente Finansal Takip

## Amaç

Acente finans hareketlerini farklı ekranlardan elle birleştirme ihtiyacını kaldırır. Seçili yıl
ve ay için her acentede alınan avans, haricen tahsilat, rezervasyon ciro/adedi, vadesi geçen açık
hak ediş ve ay sonunda alınması beklenen hak ediş aynı satırda gösterilir.

- UI: `/dashboard/satis/acente-finans`
- API: `GET /api/sales/acente-finans/?year=2026`
- İzin: `sales.acente_mahsup` (`view`)
- Para birimi: EUR

## Veri Kaynakları

| Kalem | Kaynak | Ay kuralı |
|---|---|---|
| Alınan avans / mahsup | Sedna muhasebe `340.*` hareketleri | Fiş tarihi |
| Haricen tahsilat | Sedna muhasebe `120.*` alacak hareketi | Tahsilat tarihi |
| Rezervasyon | Sedna PMS yerel aynası `reservations` | Çıkış tarihi |
| Açık / vadesi geçen hak ediş | `sales_invoices` + FIFO tahsilat + `receivable_terms` | Fatura tarihi + vade günü |
| İleri hak ediş tahmini | Aktif ileri PMS rezervasyonu + `agency_groups.term_days` | Çıkış tarihi + grup vadesi |

`120-340 VİRMAN` açıklamalı 120 hareketleri haricen tahsilata dahil edilmez; bunlar alınan avansın
faturaya mahsubunun karşı bacağıdır. Dahil edilmesi aynı parayı hem tahsilat hem avans mahsubu
olarak iki kez gösterirdi.

## Ay Sonu Hak Ediş Formülü

```text
Ay sonu alınacak hak ediş
  = açık gerçek faturaların vade ayındaki kalan tutarı
  + ileri rezervasyonların vade ayındaki brüt tutarı
  - ilgili acentanın kullanılmamış 340 avansı (FIFO)
```

API alanları:

- `open_due`: bugün hâlâ açık olan gerçek faturaların kalan tutarı.
- `projected_gross`: henüz faturalanmamış ileri rezervasyonların brüt tahmini.
- `projected_advance`: bu tahmine FIFO mahsup edilen mevcut 340 avansı.
- `projected_due`: `projected_gross - projected_advance`.
- `month_end_receivable`: `open_due + projected_due`.
- `overdue`: `open_due` içindeki, vadesi bugün geçmiş alt küme.

Eşleşmeyen muhasebe hesapları `Diğer / Eşleşmeyen` altında görünür. Bu havuzdaki avanslar farklı
acenteleri birbirine mahsup etmemek için grup dışı rezervasyon tahminlerinden düşülmez.

## Sedna Snapshot'ı

`sales_advance_transactions`, Sedna `AccountingTrans` + `AccountingOwner` kayıtlarının 340 hesaplar
için salt-okunur yerel snapshot'ıdır. Native döviz ve fişteki TL karşılığı birlikte saklanır. Kaynak
başarıyla okunmadan mevcut snapshot silinmez. İlk dağıtımda migration sonrası merkezi Sedna senkronu
bir kez çalıştırılarak tablo doldurulur; devamında satış faturası senkronunun normal parçasıdır.

## Ekran Davranışı

- Yıl, ay (`Tüm Yıl` dahil) ve acente filtresi vardır.
- KPI kartları seçili filtreye göre yeniden hesaplanır.
- Masaüstünde karşılaştırmalı tablo, mobilde acente kartları kullanılır.
- 12 aylık hak ediş planı yıl içindeki dağılımı gösterir ve aya geçiş sağlar.
- Veriler WebSocket yayınlarıyla yenilenir; polling kullanılmaz.
