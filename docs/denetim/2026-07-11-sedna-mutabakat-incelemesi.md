# Sedna Muhasebe İncelemesi + Banka↔Sedna Mutabakat Yapısı Tasarımı (2026-07-11)

**Amaç (kullanıcı hedefi, kendi sözleriyle özet):** "Programdaki işlemler Sedna ile tutarlı olmak zorunda. Sedna verisi sonradan geldiğinde bendeki veriyi Sedna'ya göre güncelle. Banka verilerini ben önce çekebilirim, Sedna'ya sonradan yansır. Sedna girişleri hatalı olabilir — banka ekstresi HER ZAMAN doğru; uyuşmadığında uyarsın, 'Uyuşmayan Veriler' adı altında ayrı bir yerde göstersin. Sedna hesap planı mantığını incele, bende eksik olan varsa ona göre yapı kur — mesela kur farkını Sedna nasıl yapıyor bak."

**Yöntem:** 9 ajanlık Workflow. 6 keşif ajanı **canlı Sedna veritabanını** (SednaPrensesMhs2026, ters tünel, salt-okunur SELECT-guard'lı araçla) ve bizim Postgres'i fiilen sorgulayarak ölçtü; 2 tasarımcı mutabakat motoru + kur farkı yapısını tasarladı; 1 denetçi eksik boyutları çıkardı. Tüm sayılar canlı veriden.

---

## 1. Kullanıcının Varsayımları ÖLÇÜMLE DOĞRULANDI

| Varsayım | Ölçüm (canlı Sedna, 2026) |
|---|---|
| "Banka verisi bende önce oluyor, Sedna sonradan giriyor" | 102 (banka) fişleri: **medyan 3 gün, ortalama 9,3 gün, p90 = 27 gün gecikme** (FicheDate→RecordDate; n=1521). Cari (320) fişleri: medyan 8 gün, %40'ı 8-15 gün bandında. Gecikme yapısal (son 3 ay aynı). |
| "Sedna girişleri hatalı olabilir" | 102 fişlerinin **%36'sı kayıttan sonra değiştirilmiş**, %3,7'si silinmiş (cari fişlerde silme %6,9). 60 günlük 3-hesap örnekleminde: **3 YÖN-TERSİ fiş** (5.000 TL, 1.645.000 TL EFT'ler ters bacaklı; en ağırı 4.275.120 TL banka faiz ÖDEMESİ 642 faiz GELİRİ yazılmış → tek fişte ~8,5M TL sapma) + **1 mükerrer fiş** (13.500 EUR aynı gün çift girilmiş). Sedna'da fiş kontrol/onay alanları fiilen kapalı (ControlUser 1/9608, Approval 0/9608) — ikinci göz yok. |
| "Eşleştirme mümkün olmalı" | (hesap + aynı gün + yönlü tutar) anahtarıyla Sedna satırlarının **%97'si (288/297) birebir eşleşti**; tarih kayması pratikte yok (289 eşleşmenin 288'i aynı gün — FicheDate banka işlem gününü izliyor). Yön kuralı: bizim amount>0 = Sedna 102 Borç. Döviz hesabında tutar CurrDebit/CurrCredit'ten (Debit/Credit TL karşılığı). |
| "Sedna'da gerçekten eksik giriş var" | Sedna kapsama penceresi İÇİNDE hiç girilmemiş işlemler bulundu: kredi taksit tahsilatları, gelen EFT'ler, ortak kâr payı ödemeleri, 680.000 TL virmanın iki bacağı, POS bloke çözümü, YP döviz alışları. Gecikme tek başına açıklamıyor — atlanan fişler mevcut. |

Diğer kritik ölçümler: **dönem kilidi fiilen kapalı** (AccPeriodLock 2016'da kalmış → geçmiş aylar dahil her fiş her an değişebilir; senkron ChangeDate-tabanlı artımlı olmalı); granülarite iki yönlü (banka 1 satır ↔ Sedna N satır: KDV+damga bölmesi; banka N ↔ Sedna 1: ücret+BSMV birleşik); aynı gün+aynı tutar seriler (8× maaş) adet-duyarlı k↔k eşleme gerektirir; DocumentType kullanılmıyor (%95,5 "Muhasebe Fişi") — sınıflandırma Remark metni + hesap prefix'inden.

## 2. Sedna Hesap Planı → Bizim Modül Eşlemesi

9.635 hesap, nokta ayraçlı 4 seviye (leaf segmenti HARF içerebilir: `340.01.01.L001` — parser sayı varsaymamalı). Cari kartı = hesap satırı (ayrı cari tablosu yok; 151 kolonlu Accounting'de vergi no/e-posta/vade hep hesapta). Para birimi hesap bazında `Curr` — **'TRY' değil 'TL'** (çevrim haritası zorunlu).

| Sedna | İçerik | Bizim karşılık |
|---|---|---|
| 100 | Kasalar (para birimli 8 kasa) | — (yok) |
| 101 / 103 | Alınan çekler (para birimi kırılımlı) / Verilen çekler (banka kırılımlı) | checks |
| **102** | **Bankalar — 137 leaf** (2. seviye = para birimi/vade, 3. = banka); her bankada `.0099` ÇEK TAHSİL ara hesabı | bank_accounts (28) |
| 108 | VISA POS geçiş hesapları (TL/EUR/USD/GBP) | — (bilinçli yok; POS yatışını ekstre doğrudan görür) |
| 120 / 320 / 335 | Alıcılar (1.145; acenteler dahil) / Satıcılar (1.456) / Personel (2.533) | sales_invoices, vendors |
| 159 / 340 | Verilen iş avansları / Alınan avanslar (acente başına **para birimi ayrı** hesap: ANEX EUR≠ANEX USD) | advances, sales_advances |
| 300 | Krediler (300.01 TL, 300.02 döviz, 300.04 leasing, **300.10 kredi kartları** kart-kart) | credit_products, cc_statements |
| 646 / 656 | KAMBİYO KARLARI / ZARARLARI — adanmış "KUR FARKI" leaf'leri | — (**yok — kurulacak**) |
| 780 | Banka-bazlı FAİZ-KOMİSYON gider kırılımı (24 leaf) | — (banka masraf mutabakatı için hazır referans) |

**Hesap eşleme fizibilitesi (kritik):** Sedna'da IBAN alanları pratikte boş (102 leaf'lerinde BankIbanNo 3/137; Bank tablosu cari IBAN'ları içeriyor). Güvenilir anahtar: **Remark'a gömülü hesap numarası + banka adı + Curr**. Bu yöntemle bizim 28 hesabın **26'sı güvenle eşlendi**; 2'si Sedna tarafındaki yazım hatası nedeniyle insan onayı ister (Halkbank USD '5300752' hane eksik; Halkbank EUR POS 'A0000895'). Ayrıca YKB kırılım şüphesi: Sedna 102.01.02.0003 '8150 97' 23,5M hareketliyken bizde id=5 hesabı 0 işlemli — eşleme ekranında incelenmeli. `Type` kolonu tutarsız girilmiş → hesap sınıfı koddan (prefix) çıkarılmalı. Kullanılmayan hesaplar Passive işaretlenmemiş.

## 3. Kur Farkı — Sedna Böyle Yapıyor

1. **Ana mekanizma: ay sonu toplu değerleme fişi.** `AccountingOwner.Type=4` fiş tipi YALNIZ kur farkı için kullanılıyor (18/18). Ay sonunda hesap grubu başına ayrı fiş (102-EUR, 102-USD, 120 dövizli alıcılar, 300 ve 400 döviz kredileri, 320 dövizli satıcılar): her dövizli hesaba **tek net TL düzeltme satırı**, karşı bacak 646.01.01.0001 (kar) / 656.01.01.0001 (zarar).
2. **Formül kuruşu kuruşuna doğrulandı:** `düzeltme = döviz bakiye × ay sonu TCMB döviz ALIŞ kuru − mevcut TL bakiye` (örnek: 5.018,71 EUR × 51,699 → 324.607,78 TL, fişle birebir). Değerleme satırında Curr='EUR' ama **Rate=0, CurrDebit=CurrCredit=0** → yalnız TL bacağı düzeltilir, döviz miktarı değişmez (çift bakiye: TL ve döviz paralel izlenir).
3. **İşlem bazlı kur farkı da var:** çek ödemesi farkı (646.01.01.0002) ve acente/tedarikçiyle karşılıklı **KDV'li kur farkı FATURASI** (120+646+391 KDV / 656+191 KDV).
4. **Kur kaynağı:** `dbo.ExchangeRate` — 2009'dan beri günlük otomatik TCMB tablosu. Fiş Rate'leri **TCMB döviz ALIŞ (Buying)** ile birebir. **İki uyumsuzluğumuz kanıtlandı:** (a) bizim `eur_balances` **forex_SELLING** kullanıyor → Sedna TL defter değerleriyle her kıyasta sistematik sapma; (b) tarih semantiği 1 gün kayık: Sedna ExchangeRate(G).Buying = bizim exchange_rates(G−1).forex_buying (Sedna "geçerlilik", biz "yayın" tarihi — tüm Temmuz satırlarında birebir doğrulandı).
5. **Kapsam boşlukları (Sedna tarafında):** 340 avanslar, 100 kasa, 136 değerlenmiyor; Nisan-Haziran değerleme fişleri henüz kesilmemiş (kapanış 1-3 ay gecikiyor) → bizim hesaplayacağımız değerleme öncü gösterge olur.

## 4. Sedna'nın Kendi Mutabakat Altyapısından Alınacak Desenler

- **AccountingMatch** (boş ama model olarak değerli): eşleşme = `DebitId + CreditId + Amount (kısmi) + CurrExchange + ExchangeVoucherId (kur farkı fişi bağı)` — bizim tek int `match_number`'ın üst modeli; kısmi/1-N kapamayı ve kur farkını doğal ifade eder.
- **AccReconciliation/AccReconOwner** (AKTİF — 10.07.2026'da "320 mutabakat haziran" koşusu 196 cari): koşu başlığı + hesap-bazlı snapshot + Status/MailStatus yaşam döngüsü + **karşı tarafa e-posta** akışı — "Uyuşmayan Veriler" ekranının hazır şablonu.
- **SourceDatabase + SourceId + IntGuid damgalama** (PMS→muhasebe senkronunda 3.497 fiş): Sedna kendi senkron problemini kalıcı kaynak-ID ile çözüyor — bizim eksik halkamız da bu (`sedna_rec_id`).
- **Banka ekstresi içe aktarma (DocumentType 24) Sedna'da tanımlı ama HİÇ kullanılmamış** → banka-doğrulamalı mutabakat alanı tamamen bizim sistemin dolduracağı boşluk.
- FinalizedBalance (hesap→normal bakiye yönü) ters-bakiye kontrolü; AccPeriodLock dönem kilidi şablonu (bizde uyarı-modu olarak).
- **Kullanılmayacaklar:** AccountingBalance = kullanıcı-bazlı mizan cache'i (gerçek kaynak her zaman AccountingTrans aggregate'i), AccountingAmounts = boş iç tablo, AccountingCross/AccAdvance = boş.

## 5. Bizim Sistemin "Sedna Sonradan Gelince Güncelle" Boşlukları (tür bazında)

| Veri türü | Bugünkü davranış | Boşluk |
|---|---|---|
| Rezervasyon | **Tam aynalama** (rec_id kalıcı kimlik + pencere içi upsert+sil) — referans model | — |
| Stok | Ürün/depo upsert; hareketler insert-only | Kimlik (sedna_line_id) hazır, süpürme yok |
| Cari | Insert-only + Sinyal A/B kanıtlı süpürme | RecId saklanmıyor (hash tutar içerir → tutar düzeltmesi kimliği koparır); **eşleşmiş/atanmış satırda Sedna sapması SESSİZ**; cari kartı (unvan/vade) güncellenmiyor |
| Çek | Eşleşmemişte tam senkron + drift-heal | **Eşleşmiş çekte her sapma sessizce 'skipped'** (check_import.py:267,290-291); Sedna'dan kaybolan çek sonsuza dek pending |
| Satış faturası/tahsilat | **SAF insert-only** | Sedna tutar düzeltmesi → eski satır kalır + yeni eklenir → FIFO/hakediş/mahsup şişer (en büyük boşluk) |
| Avans | Manuel modül + canlı Sedna-340 karşılaştırma raporu | Rapor pasif (sayfa açılınca), bildirimsiz |
| **Banka ↔ Sedna** | **HİÇ YOK** | Sedna 102 defteri hiç import edilmiyor; tutar uyuşmazlığı hiçbir yerde raporlanmıyor |

"Uyuşmayan veri" kavramına en yakın 3 parça dağınık ve kalıcı değil: cari silme-adayı modalı (yanıtla kaybolur), çek no-anomali endpoint'i (frontend tüketicisi yok), avans mutabakat sekmesi. Kalıcı uyuşmazlık tablosu/ekranı/bildirimi yok — sıfırdan kurulacak.

## 6. Kurulacak Yapı — "Uyuşmayan Veriler" (finance.mutabakat)

### Faz A — Banka↔Sedna mutabakat çekirdeği (P1)
1. **Hesap eşleme:** `bank_accounts.sedna_account_code` + onay bayrağı (migration); Remark-numara skorlamalı öneri servisi; bankalar/mutabakat ekranında insan-onaylı eşleme (26 otomatik + 2 manuel vaka + YKB kırılım kontrolü). TRY↔'TL' çevrimi.
2. **Sedna banka defteri okuyucu:** `fetch_bank_ledger_rows` — çift Deleted filtresi (canlı fiş içinde silinmiş satır var: 32/2476), döviz hesabında CurrDebit/CurrCredit, RecordUser/ChangeDate/Voucher dahil; `fetch_bank_ledger_deleted_rows` (sonradan silinen fişin durumunu geri açmak için).
3. **Nakit-dışı sınıflandırıcı:** Owner.Type=4 VEYA 646/656 bacaklı VEYA (dövizde Rate=0 & CurrDebit=CurrCredit=0) → 'değerleme' — eşleştirme evreninden çıkar, ayrı bilgi sekmesinde. Filtresiz her ay sonu sahte uyuşmazlık yağmuru üretir.
4. **3 geçişli motor (`services/bank_recon_service.py`):** Geçiş 1 = (tarih, yönlü tutar) **adet-duyarlı k↔k** birebir (~%97); Geçiş 2 = ±3 gün penceresi; Geçiş 3 = gün-içi subset-sum k≤4 iki yönlü (KDV+damga / ücret+BSMV). Kalan sınıflandırma: `SEDNA_BEKLIYOR` (hesabın Sedna max(FicheDate)'inden sonraki banka işlemleri — uyuşmazlık DEĞİL; 15 gün eşiğinde uyarıya döner), `SEDNA_EKSIK` (dönem içi girilmemiş), `SEDNA_FAZLA`, `YON_TERSI` (aynı gün+aynı mutlak tutar+zıt işaret — 3 canlı vaka bu desenle otomatik yakalanır), `MUKERRER_SUPHESI` (Sedna adedi > banka adedi). **Motor hiçbir banka satırını değiştirmez — banka her zaman otorite.**
5. **Kalıcı saklama:** `sedna_bank_recon` (sedna_trans_rec_id + bank_transaction_id upsert anahtarı; durum yaşam döngüsü; group_key 1-N grupları; sedna_record_user/change_date "kime sorulacak"; resolved/ignored + not) + `sedna_recon_runs` koşu başlığı (AccReconOwner deseni). Sedna'da sonradan gelen fiş → `SEDNA_BEKLIYOR`→`MUTABIK` otomatik geçiş ("Sedna sonradan gelince güncelle"nin banka ayağı).
6. **UI:** `/dashboard/finans/mutabakat` (modül `finance.mutabakat`, migration+navigation): ListPage iskeleti, StatCard'lar (Mutabık %, Bekleyen, Uyuşmayan, En eski bekleyen), durum filtreli tablo, detay modalında banka satırı vs Sedna fiş bacakları + RecordUser/ChangeDate, sekmeler: Banka↔Sedna | Hesap Eşleme | Değerleme (bilgi) | (Faz C: Cari↔Sedna). **iPad uyumlu** (<md kart kırılımı).
7. **Bildirim + WS:** BroadcastModule.RECON; yeni YON_TERSI/MUKERRER/TUTAR_FARKI + 15 günü aşan bekleyenler → Notification (notified_at ile tekrar-uyarı yok); bildirimde Sedna RecordUser.
8. **Zamanlama:** sedna_sync `_STEPS`'e adım + günlük timer (06:30 İstanbul; diğer cron'larla faz farklı). Pencere: her koşuda 45 gün + haftalık 180 gün derin tarama, Owner.ChangeDate-artımlı (dönem kilidi olmadığından eski aylar değişebilir).
9. **Politika matrisi (docs/modules/sedna-mutabakat.md + kod guard'ı):** (a) bankayla çelişen Sedna → ASLA otomatik düzeltme, yalnız uyuşmazlık+bildirim; (b) bankayla çelişmeyen defter alanı (çek vadesi, unvan, fatura tutarı) → Sedna otorite, otomatik güncelle; (c) banka-kanıtlı kayıtta Sedna sapması → kaydı değiştirme, uyuşmazlık göster; (d) otomatik sınıflandırma onaydan MUAF, kullanıcı resolve/ignore check_approval'lı.

### Faz A ön koşulları (eleştirmen bulguları — motor güvenilirliği)
- **Koşu bütünlüğü:** tünel kopukluğu/kısmi veri → o hesabın durumlarına DOKUNMA (bayat bırak + 'son başarılı koşu' damgası); "0 satır" ile "veri alınamadı" ayrımı. Yoksa ilk haftada sahte uyarı yağmuru güveni bitirir.
- **Banka tarafı tamlık simetrisi:** "banka her zaman doğru" ancak bizdeki kopya tamsa geçerli — hesap başına son ekstre tarihi eşiği + `balance` kolonundan **bakiye-zinciri süreklilik kontrolü** (bugün canlı örnek: çoğu hesap 10.07 iken Halkbank TL 08.07'de kalmış).
- **Çözüm iş akışı durum makinesi:** yeni → bildirildi → düzeltme-bekliyor → otomatik-kapandı (Sedna ChangeDate/Deleted ile) / yoksayıldı; muhasebe ekibine **e-posta iletimi** (SMTP altyapısı hazır; AccReconciliation'ın Mail yaşam döngüsü deseni). Fişlerin %36'sı zaten sonradan değiştiğinden otomatik-kapanış olmazsa ekran çöp listesine döner.
- **Yıl devri (kritik):** DB adı sabit `SednaPrensesMhs2026` — 1 Oca 2027'de ya boş veri ya 916 hatası; Aralık kuyruğu (p90=27 gün) eski DB'ye girilmeye devam eder → Ocak-Şubat **çift-DB penceresi** + yeni DB'ye SELECT izni checklist'i + açılış-devir fişi filtresi tasarlanmalı. (Cari/çek/satış importları da aynı sabitten etkilenir.)

### Faz B — Kur farkı yapısı + Sedna-otorite kimlik (P2)
10. **Kur helper (`fx_service.ledger_rate`):** Sedna-eşdeğer defter kuru = exchange_rates(G−1).forex_buying (1 gün kayma + Buying); raporlama katmanı (selling) ayrı ve belgeli. Mutabakat/değerleme yalnız ledger_rate kullanır.
11. **`event_matches` tablosu (AccountingMatch deseni):** eşleşme = taraf kimlikleri + kısmi tutar + kullanılan kur + fx bağı + method(auto/manual/suggestion) + skor — önceki denetimin "iki-eşikli öneri kuyruğu" ve "kısmi/1-N eşleşme" maddeleriyle AYNI şema (iki kez şema değişmesin).
12. **`fx_differences` tablosu:** çapraz-para eşleşmede kur farkı kaydı (rate_estimate/rate_realized, ± TL = 646/656 eşleniği) — **finance_events'e KALEM YAZILMAZ** (nakit değildir; Sedna'da da değerleme döviz bakiyesine dokunmaz). Önceki denetimin Karar-2 sorusunun cevabı: Sedna'yı yansıla → ayrı katman.
13. **Aylık değerleme raporu:** bizim veriden hesap-bazlı `döviz bakiye × ay sonu ledger_rate − TL değer` ↔ Sedna Type=4 fişleri yan yana (Sedna fişi henüz yoksa 'bekleniyor' — Nis-Haz örneği). Deftere yazma YOK; Faz-2'de kullanıcı kararıyla FE'ye `fx_revaluation` (is_matched doğar, runway'i şişirmez).
14. **Kalıcı Sedna kimliği:** `vendor_transactions/checks/sales_invoices.sedna_rec_id` (sorgular RecId'yi SELECT etsin); import iki aşamalı: önce rec_id ile UPDATE, yoksa hash-dedup ile ekle+damgala. Hash-kopması biter.
15. **Satış faturaları aynalamaya geçer** (rezervasyon deseni: pencere içi rec_id upsert + silme + FIFO cache invalidate) — önceki denetim C4 ile birleşir.
16. **Sessiz sapmalar görünür olur:** eşleşmiş çek/cari kayıtlarında Sedna farkı → `sedna_bank_recon`'a entity_type'lı kayıt (aynı ekran/bildirim; otomatik silme YOK).

### Faz C — Genişleme (P3)
17. Cari↔Sedna mutabakat sekmesi (aynı motor; banka-kanıtı olmadığından temkinli sınıflar; vendors çoklu-hesap: ANEX EUR/USD → tek vendor).
18. Kredi (300.*) + acente avans (340.01.01) Sedna kod eşlemesi; avans mutabakatı kod-öncelikli olur ve bildirime bağlanır.
19. Dönem kilidi **uyarı modu** (bloklamayan) + ters-bakiye kontrolü (FinalizedBalance eşleniği).
20. **"YAPMA" listesi** (docs/modules/sedna-mutabakat.md): çift taraflı defter/fiş üretimi yok; kendi 646/656 planı yok; KDV'li kur farkı faturası kesme yok (muhasebeci işi); 108 POS geçiş modeli yok; DocumentType haritası yapılmaz (kullanılmıyor); AccountingBalance/Amounts senkronu yok.

## 7. Önceki Denetimle İlişki (2026-07-11 nakit akım raporu)

- Bu tasarım **çelişmez, üstüne oturur**: `matching_service` (banka→yerel operasyonel kapama) ile `bank_recon_service` (banka→Sedna defter doğrulaması) ayrı katmanlar; ikisi de matcher orkestratörü/`event_matches` şemasını paylaşır.
- **Karar-2 (kur farkı) CEVAPLANDI:** Sedna modeli yansılanır — ayrı fx katmanı (fx_differences + aylık değerleme raporu), finance_events dışında.
- Kur tipi bulgusu (Buying vs Selling + 1 gün kayma) önceki denetimin D1 (çapraz-para) tasarımının ön koşuludur.
- Satış faturası aynalaması = önceki C4; Sedna sync broadcast'leri = önceki B1 ile birlikte kapanır.

## 8. Kalan Kullanıcı Kararları

1. **EUR raporlamada kur tipi:** ✅ **KARAR VERİLDİ (2026-07-11, kullanıcı onaylı) — ALIŞ kuruna geçildi ve uygulandı.** eur_balances/t_account/runway/_helpers + çek/cari/kredi özetleri + rezervasyon/stok/hakediş servisleri forex_selling'den **forex_buying**'e geçirildi (Sedna TL defter değerleriyle hiza); test fixture'ları forex_buying seed'ler.
2. **Aylık değerleme FE'ye kalem olarak yazılsın mı:** ✅ **KARAR VERİLDİ (2026-07-11) — RAPOR katmanında kalır, finance_events'e kalem YAZILMAZ** (nakit değil — Claude kararı, kullanıcı yetkilendirdi). Faz B değerleme raporu Sedna Type=4 fişleriyle yan yana doğrulama için kullanılacak.
3. Muhasebe ekibine **e-posta iletimi** (uyuşmazlık listesi) açılsın mı, kime? (SMTP hazır.) — **HÂLÂ AÇIK.**

**Durum: Faz A + B + C UYGULANDI (2026-07-11)** — Faz A: `accounting.mutabakat` modülü (motor + Uyuşmayan Veriler sayfası + hesap eşleme + otomatik kapanma + bildirim + sedna_sync adımı); kur alış'a çevrildi. Faz B (migration `e5f6a7b8c9d0`): aylık kur değerlemesi raporu (`GET /fx-revaluation`, salt rapor — FE'ye yazmaz) + `ledger_rate` (Sedna-eşdeğer defter kuru, 1 gün kayma) + `event_matches`/`fx_differences` katmanı (646/656 eşleniği) + kalıcı `sedna_rec_id` kimlikleri (cari/çek/satış) + korunan-kayıt `sedna_diff` sapmaları + satış faturaları tam aynalama. Faz C (migration `f7a8b9c0d1e2`): cari NET bakiye ↔ Sedna 320 mutabakatı (`balance_diff`, `entity_type='vendor_balance'`) + kredi 300 / acente 340 kod eşlemeleri (`credit-mappings`/`agency-mappings`; avans mutabakat raporu kod-öncelikli) + dönem kilidi (uyarı modu — bloklamaz; `finance_period_locks` + `locked_period_new`) + ters-bakiye kontrolü (`negative_balances`, KMH hariç). **Kalan: yıl devri Mhs2027 (yılbaşından önce!), muhasebeye e-posta iletimi kararı; ilk raporun (nakit akım eşleştirme) Faz 0-3'ü ayrıca bekliyor.** Modül dokümanı: `docs/modules/sedna-mutabakat.md`.
