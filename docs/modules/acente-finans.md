# Acente Finansal Takip

## Amaç

Acente finans hareketlerini farklı ekranlardan elle birleştirme ihtiyacını kaldırır. Seçili yıl
için her acentede alınan avans, haricen tahsilat, rezervasyon ciro/adedi, kesilen fatura, vadesi
geçen açık hak ediş ve alınması beklenen hak ediş aynı satırda gösterilir.

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
| Kesilen fatura | Sedna muhasebe `120.*` satış faturaları | Fatura tarihi |
| Açık / vadesi geçen hak ediş | `sales_invoices` + FIFO tahsilat + `receivable_terms` | Fatura tarihi + vade günü |
| İleri hak ediş tahmini | Aktif ileri PMS rezervasyonu + `agency_groups.term_days` | Çıkış tarihi + grup vadesi |

`120-340 VİRMAN` açıklamalı 120 hareketleri haricen tahsilata dahil edilmez; bunlar alınan avansın
faturaya mahsubunun karşı bacağıdır. Dahil edilmesi aynı parayı hem tahsilat hem avans mahsubu
olarak iki kez gösterirdi.

## Hak Ediş Formülü

```text
Ay sonu alınacak hak ediş
  = açık gerçek faturaların, kullanılmamış 340 avansı FIFO mahsup edilmiş net tutarı
  + ileri rezervasyonların vade ayındaki brüt tutarı
  - açık faturalardan artan 340 avansı (FIFO)
```

API alanları:

- `open_due`: bugün hâlâ açık olan gerçek faturaların bekleyen 340 avansı mahsup edilmiş net tutarı.
- `invoiced_amount`: seçili yılda kesilen acente faturalarının brüt EUR karşılığı.
- `projected_gross`: henüz faturalanmamış ileri rezervasyonların brüt tahmini.
- `projected_advance`: bu tahmine FIFO mahsup edilen mevcut 340 avansı.
- `projected_due`: `projected_gross - projected_advance`.
- `month_end_receivable`: `open_due + projected_due`.
- `overdue`: avans mahsubu sonrası kalan `open_due` içindeki, vadesi bugün geçmiş alt küme. Bir
  acentanın kullanılmamış avansı açık faturalarını karşılıyorsa vadesi geçen tutar gösterilmez.

Eşleşmeyen muhasebe hesapları `Diğer / Eşleşmeyen` altında görünür. Bu havuzdaki avanslar farklı
acenteleri birbirine mahsup etmemek için grup dışı rezervasyon tahminlerinden düşülmez.

## Sedna Snapshot'ı

`sales_advance_transactions`, Sedna `AccountingTrans` + `AccountingOwner` kayıtlarının 340 hesaplar
için salt-okunur yerel snapshot'ıdır. Native döviz ve fişteki TL karşılığı birlikte saklanır. Kaynak
başarıyla okunmadan mevcut snapshot silinmez. İlk dağıtımda migration sonrası merkezi Sedna senkronu
bir kez çalıştırılarak tablo doldurulur; devamında satış faturası senkronunun normal parçasıdır.

## Ekran Davranışı

- Yıl ve acente filtresi vardır; ekran doğrudan yıllık toplamları gösterir.
- KPI kartları seçili yıl ve acenteye göre yeniden hesaplanır.
- Masaüstünde karşılaştırmalı tablo, mobilde acente kartları kullanılır.
- Veriler WebSocket yayınlarıyla yenilenir; polling kullanılmaz.

## Grup İçi Üye Kırılımı (2026-08-13)

Tablodaki her satır bir **acente grubudur** (`agency_groups`); satıra tıklayınca grubun altındaki
üyeler açılır. API her grup satırına `members: [{name, totals}]` dizisi ekler (yıllık toplamlar,
aylık kırılım yok). Üye kimliği kaynağa göre değişir — **bilinçli tasarım**, kullanıcı grubun
hangi kaynaklardan beslendiğini görür:

| Kalem | Üye etiketi |
|---|---|
| Rezervasyon + ileri hak ediş tahmini | PMS acente adı (`reservations.agency`) |
| Fatura / tahsilat / açık hak ediş | Sedna 120 cari adı (`customer_name`) |
| Alınan avans / mahsup | Sedna 340 hesap adı (`SalesAdvanceTransaction.name`) |

Aynı üyenin farklı yazımları (ör. PMS `ALLTOURS` ile Sedna `ALLTOURS GMBH`) ayrı satır olarak
listelenir. Üye toplamlarının toplamı grup satırıyla birebir tutar (avans FIFO mahsubu grup
havuzundan yapılır ama net tutarlar fatura/rezervasyon bazında üyeye yazılır) — regresyon:
`tests/test_agency_finance.py::test_member_breakdown_matches_group_totals`. Tamamı sıfır olan
üyeler yanıta eklenmez; `Diğer / Eşleşmeyen` grubunun kırılımı eşleşmeyen kaynakları teşhis için
özellikle kullanışlıdır.
