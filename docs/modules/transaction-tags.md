# İşlem Etiketleme Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `finance.banks` (bankalar modülünün parçası) |
| **Frontend rota** | `/dashboard/finans/bankalar` → "Etiketleme" sekmesi |
| **Backend prefix** | `/api/finance` |
| **İzin kodu** | `finance.banks` |

Banka işlemlerini kategorilere ayırmaya ve cari kodlara eşleştirmeye yarayan modül.
Nakit akım analizinde masraf kategorisi gruplamalarına temel sağlar.

---

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/transaction_tags.py` | Kategori CRUD, etiketleme, otomatik eşleştirme |
| `app/models/transaction_category.py` | `TransactionCategory` modeli |
| `app/models/bank_transaction.py` | `tag_category_id`, `tag_note`, `match_number` alanları |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/routes/dashboard/finans/bankalar/+page.svelte` | Etiketleme arayüzü |

---

## Veritabanı Şeması

### `transaction_categories`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `name` | varchar(100) | Kategori adı (ör. "Kira", "Maaş") |
| `color` | varchar(7) | HEX renk kodu (#4CAF50) |
| `parent_id` | integer FK → self | Üst kategori (hiyerarşik yapı) |
| `is_active` | boolean | |
| `created_at` | timestamptz | |

### `bank_transactions` — Etiket alanları
| Kolon | Tip | Açıklama |
|---|---|---|
| `tag_category_id` | integer FK → transaction_categories | Atanan kategori |
| `tag_note` | text | Serbest metin notu |
| `tag_source` | varchar(20) | `manual`, `auto`, `vendor` |
| `match_number` | varchar(50) | Harici eşleştirme referans numarası |
| `vendor_id` | integer FK → vendors | Eşleştirilen cari |

---

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/tags/categories` | view | Kategori listesi (hiyerarşik) |
| `POST` | `/tags/categories` | use | Yeni kategori oluştur |
| `PATCH` | `/tags/categories/{id}` | use | Kategori güncelle |
| `DELETE` | `/tags/categories/{id}` | use | Kategori sil |
| `GET` | `/tags/untagged-count` | view | Etiketlenmemiş işlem sayısı |
| `PATCH` | `/tags/transactions/{tx_id}` | use | İşlemi etiketle (tekli) |
| `POST` | `/tags/transactions/bulk` | use | Toplu etiketleme |
| `POST` | `/tags/auto-tag` | use | Kurallara göre otomatik etiketle |
| `GET` | `/tags/payment-methods` | view | Ödeme yöntemi listesi |
| `POST` | `/tags/auto-match-vendors` | use | Açıklamadan otomatik cari eşleştir |

---

## Etiketleme Veri Akışı

```
Banka işlemi yüklenir
       ↓
tag_category_id = NULL (etiketlenmemiş)
       ↓
Manuel / otomatik etiketleme
       ↓
tag_category_id = kategori_id
tag_source = "manual" / "auto" / "vendor"
       ↓
finance_event_svc.sync_tag(db, tx_id, ...)
       ↓
finance_events tablosu güncellenir
(category_id, category_name, category_color, vendor_id, tag_note)
```

---

## finance_events Entegrasyonu

```python
finance_event_svc.sync_tag(db, tx_id, category_id, category_name, category_color, vendor_id, tag_note, tag_source)
```

`finance_events` tablosunda `bank` kayıtlarının kategori/cari bilgileri güncellenir.
Bu sayede nakit akım raporunda kategori bazlı gruplama yapılabilir.

---

## Virman / Döviz Satım Karşı Bacak Eşleme — Kur-Duyarlı (2026-07-03 düzeltmesi)

`Virman` ve `Döviz Satım` etiketlerinde karşı banka bacağı otomatik bulunup aynı
`match_number` ile etiketlenir (`transaction_tags._find_pair_counterpart`):

- **Virman:** karşı bacak yalnız **AYNI para birimli** hesaplarda aranır — tutar
  birebir, yoksa ±%2 (en yakın tutarlı aday seçilir).
- **Döviz Satım:** bacaklar **FARKLI para birimli** hesaplardadır (ör. EUR çıkış ↔ TL
  giriş) — ham tutarlar karşılaştırılamaz. İki bacağın **TL değeri** (o günün TCMB
  `forex_selling` kuru; TL bacak ×1) **±%5** içinde eşleşmelidir; aynı birimdeki
  hareketler aday bile olamaz. Kur kaydı yoksa **eşleme yapılmaz** (yanlış eşlemektense
  yalnız seçilen işlem etiketlenir).
- **Neden (canlı hata, 02.07.2026):** eski mantık kur gözetmeden aynı tarihte ±%2 ham
  tutar arıyordu → €36.428,78 döviz satışına, gerçek TL bacağı (₺1.939.941,82) yerine
  aynı EUR hesaba aynı gün gelen €36.781,33'lük acente havalesi (TRAVE) eşlendi (#481).
  TL bacağı ham tutarda hiçbir zaman bulunamazdı. Yanlış kayıt elle düzeltildi (#482).
- Test: `test_transaction_tags.py` — `test_virman_pairs_same_currency_only`,
  `test_doviz_satim_pairs_cross_currency_leg` (canlı vakayı birebir üretir),
  `test_doviz_satim_without_rate_does_not_pair`.

---

## Otomatik Etiketleme Kuralları

`run_auto_tag()` fonksiyonu şu kurallara göre çalışır:

1. **Açıklama eşleşmesi:** İşlem açıklaması bilinen kategorilerle karşılaştırılır
2. **Ödeme yöntemi:** EFT/Havale transferleri vs. POS ödemeleri ayrımı
3. **Cari eşleştirme:** Açıklamadaki cari kodu/adı `vendors` tablosunda aranır

### Döviz Satışı Kuralı (2026-07-13)

`AUTO_TAG_RULES`'ta **"Döviz Satışı"** kuralı (`dvz sat|doviz sat`) **"Kredi" kuralından ÖNCE**
gelir — "Döviz Internet - Mobil **YapiKredi**FX+ Dvz Satis" açıklaması "kredi" desenini de
içerdiğinden döviz satışları yanlışlıkla Kredi etiketleniyordu (canlı bug; Panel T-Hesap'ta
"Kredi" gelir grubu olarak görünüyordu). Mevcut **"Döviz Satım"** kategorisiyle karıştırma:
Döviz Satım = çift-bacak iç transfer (T-Hesap/nakit akımdan HARİÇ), **Döviz Satışı = görünür
kategori** (kullanıcı kararı — döviz bozdurma geliri/gideri T-Hesap'ta başlık olarak izlenir).

### POS Bloke Çözümü — "Pos Bloke Çözme" Çift-Bacak Tespiti (2026-07-18, kullanıcı isteği)

Halkbank POS bloke çözümü ("UBLK/1376/... /POS BLOKE ÇÖZÜM") parayı **bloke POS
hesabından** (2L/2A IBAN'lı hesaplar) **ana hesaba** taşır — gerçek gelir/gider değil,
hesaplar arası virmandır. Kalemler daha önce karışık etiketleniyordu (Pos Aidat Gideri /
POS / Virman) ve Panel T-Hesap ÇIKIŞ toplamını şişiriyordu (canlı: Haziran "Pos Aidat
Gideri" €11.308 görünüyordu; gerçek ücretler yalnız €98).

- **Kelime kuralı YOK** — aynı açıklamayı taşıyan küçük **ücret/aidat bacakları**
  (₺799, €31, ₺3.871 gibi) gerçek giderdir ve eski kurallarında kalır. Yalnız
  **karşı bacağı bulunan** kayıt transfer sayılır: `_tag_pos_bloke_transfers`
  (`auto_tagger.py`, acenta/ücret geçişlerinden ÖNCE koşar) aynı gün + zıt işaretli
  aynı tutar (±0.02) + **farklı hesap** + açıklamasında "pos bloke" olan eşi arar;
  bulursa İKİ bacağı da **"Pos Bloke Çözme"** yapar (`POS_BLOKE_CATEGORY`, purple,
  `MANAGED_CATEGORY_COLORS` → yoksa runtime oluşur).
- **Geç gelen ekstre:** karşı bacak sonraki yüklemeyle gelirse, önceden OTOMATİK
  etiketlenmiş bacak da hizalanır; **manuel etiket asla ezilmez**.
- **Toplam-dışı görünürlük:** `t_account.INFO_CATEGORIES` bu kategoriyi kendi başlığı
  altında GÖSTERİR ama kolon toplamı/net/gerçekleşen sayaçlarına KATMAZ (`in_total=false`
  bayrağı + frontend "toplam dışı" rozeti). Nakit Akım sayfası (`finance.ts
  NO_TOTAL_CATEGORIES`) ve `compute_eur_balances` günlük gelir/gider toplamları da hariç
  tutar; `matching_service._TRANSFER_CATEGORY_NAMES`'e eklendi (eşleştirme adayı olamaz).
- **Geriye dönük düzeltme (2026-07-18):** canlıdaki 8 çift (16 kayıt, May–Tem) yeni
  kategoriye taşındı + FE'ler senkronlandı; 8 eşsiz ücret bacağına dokunulmadı.

Test: `test_auto_tagger.py::TestPosBlokeTransfers` (5) +
`test_cash_flow_taccount.py::TestTAccountInfoCategory` + `finance.test.ts` (groupByMonth).

### Banka Adı Gürültüsü — Yapı Kredi Yanlış Pozitifi (2026-07-18, `_strip_bank_noise`)

FAST/EFT açıklamaları **karşı tarafın bankasını** içerir: "... hesabından **Yapı ve Kredi
Bankası A.Ş.** YALÇIN YAVUZ hesabına giden FAST ödemesi". Bu "kredi" kelimesi ödemenin
niteliğinden değil alıcının bankasından gelir — 18 personel avansı / izin ücreti / kira /
cari ödemesi yanlışlıkla **Kredi** etiketlenmişti (canlı bug, geriye dönük düzeltildi).
Çözüm: hem `auto_tag_transactions` hem `detect_payment_method` kural eşleşmesinden ÖNCE
`_strip_bank_noise()` ile banka adı kalıplarını (`yapi (ve) kredi (bankasi)`, `yapikredi`)
metinden çıkarır. `\b` sınırı sayesinde "ihtiyaç **kredisi**", "kredi kartı" gibi gerçek
kredi ifadeleri etkilenmez; "YapiKrediFX+" bu desene girmez (onu Döviz Satışı kural sırası
kapsıyor). Aynı düzeltmede **Personel** kuralına `avans` ve `yillik izin` anahtar kelimeleri
eklendi (personel avansları ve yıllık izin ödemeleri artık Personel'e düşer — "avans" içeren
tek gelir kaydı da bir avans iadesiydi, Personel tutarlı). Test: `test_auto_tagger.py::TestBankNameNoise`.

### Leasing → "Kredi/Leasing" (2026-07-18, kullanıcı isteği — kategori RENAME)

Panel T-Hesap'ta leasing ödemeleri (QNB Leasing otomatik tahsilatı, Vakıf Leasing taksit
havaleleri — 24 kayıt) "Cari" başlığı altında görünüyordu; kullanıcı bunların **"Kredi"
başlığı "Kredi/Leasing" olarak yeniden adlandırılarak** oraya taşınmasını istedi:

- **Kategori rename (DB):** `transaction_categories` "Kredi" → **"Kredi/Leasing"** (id/renk
  aynı, orange). `finance_events.category_name` denormalize kopyaları güncellendi (104 kayıt).
  Kod artık `auto_tagger.LEASING_CATEGORY` sabitini kullanır; `MANAGED_CATEGORY_COLORS`'a
  eklendi (yoksa runtime oluşturulur — test DB'de de çalışır).
- **Leasing kuralı EN ÖNDE:** `(LEASING_CATEGORY, r"leasing|finansal kiralama")` tüm
  kuralların başında — "Gönderilen havale VAKIF LEASİNG 11. TAKSİT" açıklaması "havale" ile
  **Virman'a**, "QNB Leasing ... TAHSİLATI" ise "tahsilat" ile **Vergi/SGK'ya** düşüyordu.
  Eski `("Kredi", r"kredi|taksit|kmh")` kuralı aynı yerinde, hedefi artık `LEASING_CATEGORY`.
- **Cari eşleşmesi istisnası (`apply_vendor_bank_match`):** leasing şirketi Sedna'da 320'li
  cari olduğundan cari matcher banka bacağını **"Cari"** etiketliyordu (24 kaydın kök nedeni
  buydu). Artık `is_leasing_description()` doğruysa banka bacağı **"Kredi/Leasing"** etiketi
  alır; **eşleşme bağı (match_number/vendor_id) yine kurulur** — yalnız görünen başlık değişir.
- **T-Hesap birleşmesi:** `t_account.SOURCE_LABELS["credit"]` da `"Kredi/Leasing"` yapıldı —
  planlı kredi taksitleri + banka kredi/leasing hareketleri **tek grupta** (Personel
  birleştirmesiyle aynı desen; karma grubun `section`'ı deterministik "finansman").
- **Geriye dönük düzeltme:** 24 leasing kaydı (Cari/Virman/Vergi-SGK'ya dağılmıştı)
  kural motoruyla yeniden etiketlendi; 17'sindeki cari (vendor_id) bağı korundu.
- **"NOLU ÖDEME PLANI" deseni + kredi eşleşmesi bacak etiketi (aynı gün, ikinci bulgu):**
  Halkbank leasing taksiti "HAVALE 2600046701 NOLU ÖDEME PLANI" hiç leasing kelimesi
  taşımaz → `_LEASING_PATTERN`'e `nolu odeme plani` eklendi. Ayrıca **kredi taksitine
  eşleşen HER banka bacağı** (tekil `apply_credit_bank_match` + N-1 grup yolu) artık
  `_tag_scheduled_bank_leg` ile kanonik **"Kredi/Leasing"** etiketi alır — kelime kuralı
  Virman/Cari verse bile kredi kanıtı düzeltir; **manuel etiket korunur**. Canlıdaki 3
  Halkbank kaydı (Mayıs/Haziran/Temmuz, taksitleri "Halk Leasing 2600046701" ürünüyle
  zaten eşleşikti) yeniden etiketlendi. Test: `TestCreditBankLegTagging` (3) +
  `TestLeasingRule::test_halkbank_odeme_plani_tagged`.

Test: `test_auto_tagger.py::TestLeasingRule` (4) +
`test_faz1_matching.py::TestVendorMatcher::test_leasing_bank_leg_tagged_kredi_leasing_not_cari` +
`test_cash_flow_taccount.py::test_credit_and_bank_leasing_merged_under_kredi_leasing`.

### Vergi "Taksit:" Yanlış Pozitifi + Temettü Kuralı (2026-07-18, Sedna denetimi)

2026 işlemlerinin Sedna fiş karşı-hesaplarıyla toplu karşılaştırması (aşağıdaki denetim) iki
kural hatası daha buldu:

1. **"Vergi Tahsilatı … Taksit:1 …" banka formatı** "taksit" kelimesiyle Kredi'ye düşüyordu
   (35 kayıt/₺8,6M: KDV, stopaj, konaklama vergisi, MTV, damga). Çözüm: **spesifik**
   `("Vergi/SGK", r"vergi tahsilat|sgk tahsilat|vergi dairesi")` kuralı Kredi'den ÖNCE;
   genel `vergi|sgk|sgdp|tahsilat` kuralı yerinde kaldı ki "KREDİ TAKSİT TAHSİLATI" gibi
   gerçek kredi hareketleri Kredi'de kalsın (listede aynı kategori iki kez yer alabilir —
   ilk eşleşen kazanır).
2. **Temettü/ortak ödemeleri** ("HAVALE Temettü …", "EFT … ORTAKLARA ÖDENEN …") havale/eft
   kelimesiyle Virman'a düşüyordu (Sedna 331 Ortaklara Borçlar). Çözüm: `("Temettü",
   r"temettu|ortaklara odenen")` kuralı **Virman'dan ÖNCE**; "Temettü" yönetilen kategori
   (purple, yoksa otomatik oluşur).
3. `_strip_bank_noise` genişledi: banka bazı açıklamalarda adın başını kırpıyor
   ("…VE KREDİ BANKASI A.Ş.") → `\bkredi\s+bankasi` alternatifi eklendi.

Test: `test_auto_tagger.py::TestVergiTaksitRule` + `TestTemettuRule` + `TestBankNameNoise`.

### Sedna Karşı-Hesap Denetimi ve Toplu Düzeltme (2026-07-18)

2026-01-01'den itibaren 2.603 banka işlemi Sedna 102.* defter satırlarıyla eşlendi (%89;
tarih+tutar, ±3 gün) ve fişin **karşı-hesap bacağından** muhasebedeki gerçek grup çıkarıldı.
Uygulanan düzeltmeler: 39 yanlış etiket sıfırlanıp düzeltilmiş kural motoruyla yeniden
etiketlendi; 386 etiketsiz işlem Sedna grubuna göre dolduruldu (**tag_source='manual'**,
kural motoru üretmediği için; 82'si güvenli karar olmadığından bilinçli atlandı: karışık 770
gider, kasa hareketi, karışık müşteri tahsilatı). Önemli doğrulama: "Kira Geliri" etiketleri
DOĞRU (ATM/baz istasyonu kiracıları Sedna'da 120 müşteri hesabında); Döviz Satım↔Virman,
KK Borç Ödeme↔Kredi(300), Pos Aidat/Komisyon↔780 farkları bilinçli adlandırmadır, hata değil.
Eşleşmeyen ~280 yerel işlemin 240'ı ≤500₺ banka kesintisi (Sedna toplu işler).

### Acenta Tahsilatı Tespiti (2026-07-13, `_tag_agency_collections`)

Acente ödemelerinin banka açıklaması çoğu zaman kırpık gelir ("TRAVE/020726/278982",
"SEYAHAT ACENT/030726/…") → kelime kuralı yetmez. Etiketsiz **GELİR** işlemleri üç sinyalle
**"Acenta"** kategorisine etiketlenir (auto_tag_transactions içinde, kelime kurallarından ÖNCE):

1. **Sedna tahsilat eşleşmesi:** `sales_collections`'taki acente tahsilatıyla (120.01.* kodu
   veya turizm/travel isim ipuçlu 120.*) tutar + para birimi birebir (kuruş), tarih ±4 gün.
   Döviz tahsilatın TL karşılığı (amount) TRY hesap eşleşmesi için ayrıca indekslenir.
2. **Acente adı token'ı:** `agency_groups` (ad+üyeler) + `reservations.agency` + acente
   tahsilat müşteri adlarından ayırt edici token'lar; ≥2 token veya tek token ≥8 karakter
   (auto_match_vendors kalite kuralı).
3. **Açıklama ipucu:** `seyahat acent|travel|acente|acenta|touristik|reisen`.

Guard'lar (çok-ajanlı inceleme + canlı dry-run sonrası sertleştirildi, 2026-07-13):
- Yalnız `type='income'`; "virman/hesaplar arası" açıklamaları aday olamaz.
- **Transfer görünümlü açıklamada (havale/EFT/FAST/transfer/para gönder) salt-tutar eşleşmesi
  YETMEZ** — isim token'ı veya açıklama ipucu eş-sinyali şart (kendi bankalar-arası
  transferler + misafir FAST ödemeleri tutar çakışmasıyla Acenta'ya düşüyordu).
- **Her tahsilat en çok BİR işlemi etiketler** (tüketilir) — aynı paranın devam-transferi
  ikinci kez etiketlenmez.
- **120.01.* saf acente segmenti DEĞİL** (canlıda Vodafone, TT Mobil, banka ATM-kira,
  gerçek kişi kayıtları var) → banka/telekom/kira/market adlı tahsilat müşterileri blok
  listesiyle (`_AGENCY_NAME_BLOCK`) tamamen elenir; token havuzuna yalnız isim-ipucu-doğrulanmış
  acente adları girer.
- **Jenerik kelimeler token olamaz** (`_AGENCY_TOKEN_SKIP`: işletmeciliği/otel/hotels/group/
  turkiye/bankasi/vodafone…) ve ≥2-token kuralı **aynı acentenin** kümesinden sağlanmalı
  (çapraz-acente kombinasyon eşleşme sayılmaz).
- Bireysel misafir tahsilatları (120.26.*) **bilinçli hariç** (acenta değildir).

Düzeltme davranışı: yanlış otomatik etiket **başka bir kategoriye manuel taşınırsa kalıcıdır**
(kural yalnız `category_id IS NULL` işler). Etiketi tamamen KALDIRMAK (Etiketsiz'e çevirmek)
ise kalıcı değildir — sonraki otomatik koşu (ekstre yüklemesi / Sedna sync / rematch) kurala
uyan işlemi yeniden etiketler; bu, tüm otomatik kurallar için geçerli genel davranıştır.

**Görünen ad = acente adı (2026-07-13, kullanıcı isteği):** Acenta etiketi atılırken eşleşen
acentenin KISA adı (`_short_agency_name` — kurumsal/tür kelimeleri atılır: "PGST ANTALYA
TURİZM SEYAHAT ACENTASI TAŞ…" → "PGST") **`tag_note`'a yazılır** (tutar eşleşmesinde tahsilat
müşterisinden, token eşleşmesinde acente kümesinin adından; salt-ipucu eşleşmesinde de tutar/token
çözümü ayrıca denenir). Panel T-Hesap `_item_name` Acenta kalemlerinde karışık banka açıklaması
("Diğer Diğer TRAVE/020726/278982", "Swift şubeden para yatırma Ref: …") yerine bu adı gösterir;
ad çözülemezse açıklamaya düşer. Mevcut 37 kayıt 2026-07-13'te geriye dönük dolduruldu.

### Banka Havale/EFT Komisyon Tespiti (2026-07-13, `_tag_bank_fees`)

Banka ücret/komisyon kalemleri Etiketsiz kalıyordu; **"Havale Komisyonları"** kategorisine
etiketlenir (yalnız GİDER, kelime kurallarından ÖNCE — "EFT ÜCRETİ" açıklaması Virman'a düşmesin):

1. **Ücret anahtar kelimesi** (`ucret|ucr|bsmv|kkdf|komisyon|masraf|kom`) + tutar tavanı
   (TRY ≤2.500, döviz hesabı ≤100) — tavan üstü "komisyon" içeren gerçek ödemeler (ör. kredi
   kullandırım komisyonu) bu başlığa girmez, eski kurallara düşer.
2. **Yapı Kredi ücret bacağı deseni:** "Diğer Internet - Mobil <karşı taraf>" önekli KÜÇÜK
   gider (TRY ≤250, döviz ≤25) — YK her transferin ücret+BSMV bacağını bu önekle ayrı yazar
   (canlı: ₺15,96+₺0,80 çiftleri). Aynı önekli BÜYÜK tutarlar kart borcu ödemesidir
   (maskeli PAN, ₺10K+) → tavan zorunlu.

İlk canlı koşu (2026-07-13): 198 kalem (~₺10.317) etiketlendi. Mevcut "Komisyon" (25 işlem)
ve boş "Havale Masrafı"/"Pos Aidat Gideri" kategorilerine dokunulmadı.

**Yönetilen kategoriler:** "Döviz Satışı" (cyan), "Acenta" (teal) ve "Havale Komisyonları"
(amber) yoksa `_get_or_create_category` ile otomatik oluşturulur (migration gerekmez, test
DB'de de çalışır; unique(name) yarışı SAVEPOINT'le emilir).

---

## Sedna Karşı-Hesap Köprüsü — `tag_source='sedna'` (2026-07-23)

**Sorun:** "Para Gönder Diğer <kişi adı>" gibi sinyalsiz açıklamalar (personel avansı
EFT'leri, kişi adları cari listesinde olmayan ödemeler) kelime kural motorunun hiçbir
desenine düşmediğinden Panel T-Hesap'ta "Etiketsiz"te kalıyordu — oysa muhasebe bu
ödemelerin fişini Sedna'da çoktan kesmişti (canlı 2026-07-20: 28 personel avansı,
3 cari ödemesi Etiketsiz'te; kullanıcı bulgusu 2026-07-23).

**Çözüm — `app/services/sedna_tag_bridge.py`:** Banka↔Sedna mutabakatı
(`sedna_recon_service.run_reconciliation`) bir banka hareketini Sedna fişiyle
eşlediğinde, fişin **karşı-hesap bacakları** (`sedna_client.fetch_fiche_counter_legs`)
okunur ve ETİKETSİZ hareket hesap prefix'inden kategorize edilir. 2026-07-18 ELLE
yapılan karşı-hesap denetiminin kalıcı otomasyonudur; 2 saatlik cron'un `bank_recon`
adımıyla birlikte koşar (ekstre ne zaman yüklenirse yüklensin, fiş kesildikten en geç
2 saat sonra kalem doğru başlığa iner).

**Prefix → kategori haritası (`PREFIX_CATEGORY` — yalnız kanıtlı sınıflar):**

| Prefix | Kategori | Not |
|---|---|---|
| 335, 196 | Personel | Personele borçlar + personel avansları |
| 320 | Cari | exact eşleşmede `vendor_id` + `tag_note` da atanır |
| 360, 361, 368, 369 | Vergi/SGK | vergi/SGK/taksitlendirme yükümlülükleri |
| 300, 303 | Kredi/Leasing | banka kredileri (`LEASING_CATEGORY` sabiti) |
| 340 | Acenta | tur operatörü avansları |
| 331 | Temettü | ortaklara borçlar |
| 103 | Çek Ödemesi | bağlı çek varsa "Cari: <firma>" notu da yazılır (aşağı bkz) |
| yalnız 102↔102 | Virman / Döviz Satışı | karşı 102 hesabımız FARKLI para birimindeyse Döviz Satışı |

**Temkinlilik kuralları:**
- Karar bacağı = fişin 102-dışı bacaklarından |tutar|ı en büyük olanı; prefix haritada
  yoksa kalem **etiketlenmez** (770 gibi karışık gider hesapları bilinçli dışarıda —
  2026-07-18 denetiminde de o sınıf kullanıcı kararına bırakılmıştı).
- k↔k eşleşme (aynı gün aynı tutar birden çok kalem) banka↔fiş eşlemesini
  ÇAPRAZLAYABİLİR → grup yalnız TÜM fişler AYNI kategoriye çıkıyorsa etiketlenir;
  `vendor_id`/`tag_note` (kişi/firma adı) yalnız birebir (exact) eşleşmede yazılır.
- Manuel/mevcut etiket ASLA ezilmez (yalnız `category_id IS NULL`); "pos bloke"
  açıklamaları atlanır (`_tag_pos_bloke_transfers` alanı). Küme-toplamı (subset)
  eşleşmeleri köprüye girmez (ücret+BSMV bölünmeleri — kelime kurallarının alanı).
- Köprü **best-effort**: hatası mutabakat koşusunu asla düşürmez; Sedna kopuksa
  sessizce atlanır. FE senkronu `_sync_finance_events` ile (T-Hesap başlığı anında).
- `tag_source='sedna'` **makine etiketidir** — CC matcher yeniden-tarama filtresi
  (`_match_cc_to_bank`) bunu 'auto' ile aynı sayar (köprü bir KK ödemesini yanlış
  sınıflarsa matcher düzeltebilir). Manuel etiketleme her zaman üzerine yazabilir.

Test: `tests/test_sedna_tag_bridge.py` (22) + `test_banks_cc_match.py::
test_sedna_tagged_expense_still_matches`.

---

## Çek Ödemesi Başlığı + "Cari: <firma>" Etiketi (2026-07-23, kullanıcı isteği)

**Karar:** "Ödenen çek aynı zamanda bir cari ödemesidir — Çek Ödemesi başlığı altında
gösterip yanına cari ödemesi etiketi basalım." Ödenen çekin banka bacağı
**"Çek Ödemesi"** kategorisine alınır (`CHECK_PAYMENT_CATEGORY` sabiti, indigo) ve
`tag_note`'una **"Cari: <firma adı>"** yazılır; Panel T-Hesap satırında bu not indigo
çip olarak görünür (`CashFlowTAccount.cariChip` — yalnız `"Cari: "` önekli notlar çip
olur, diğer notlar T-Hesap'ta basılmaz).

**Üç yazma noktası:**
1. **Eşleşme anında** — `apply_check_bank_match` (tüm yollar: otomatik matcher, 1-N
   grup, manuel endpoint, öneri-Onayla) `_tag_scheduled_bank_leg(..., tag_note=...)`
   ile etiketler (kredi bacağı deseninin çeke uyarlanması).
2. **Sedna köprüsü** — 103 karşı-hesaplı fişler (üstteki harita); cari notu Sedna'dan
   DEĞİL bizim `checks.bank_transaction_id` FK'mızdan gelir (103 hesap adı bankanın
   çek hesabıdır, cariyi söylemez; btx-özel bilgi olduğundan k↔k çaprazlanma riski yok).
3. **Geriye dönük doldurma** — 2026-07-23'te 104 çek-bağlı bacağın tamamı hizalandı
   (96'sı 18 Tem denetiminde zaten manuel "Çek Ödemesi"ndeydi → yalnız notu eklendi;
   kategorisi farklı 7'si taşındı + not).

**Kurallar:** manuel kategori ezilmez (yalnız not eklenebilir); mevcut `tag_note`
korunur; **`vendor_id` BİLEREK yazılmaz** — cari eşleştiricisi (`_match_vendors_to_bank`)
`btx.vendor_id`'yi sinyal olarak kullanır, çek bacağına cari bağı yazmak açık cari
FE'lerine yanlış otomatik eşleşme (çift temsil) riski doğurur; cari bilgisi salt
görsel etikettir. `_tag_scheduled_bank_leg` artık opsiyonel `tag_note` parametresi
alır (kategori aynıysa bile boş not doldurulur — idempotent re-run).

Test: `test_sedna_tag_bridge.py::TestCheckBankLegTagging` + `test_cek_fisi_tags_cek_odemesi_with_cari_note` + `cashflow.test.ts` tag_note passthrough.

---

## Audit Log Entegrasyonu

| entity_type | Kaydedilen eylem |
|---|---|
| `transaction_tag` | update (tekli/toplu etiketleme) |
| `transaction_category` | create, update, delete |

---

## Geliştirme Kuralları

1. **Hiyerarşi:** Maksimum 2 seviye kategori hiyerarşisi (üst + alt)
2. **Etiket kaynağı:** `tag_source` alanı her zaman set edilmeli (`manual`/`auto`/`vendor`/`sedna` — `sedna` = karşı-hesap köprüsü, makine etiketi sayılır)
3. **Toplu işlem:** 1000+ işlemde toplu etiketleme endpoint'i kullanılmalı
4. **WS broadcast:** Etiketleme sonrası `broadcast_finance_update(background_tasks, "banks", "tag")` tetiklenir
5. **Renk kodu:** Kategoriler için HEX renk kodu zorunludur (frontend badge gösterimi için)
