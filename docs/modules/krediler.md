# Krediler Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `finance.krediler` |
| **Üst modül** | Finans (`finance`) |
| **Frontend rota** | `/dashboard/finans/krediler` |
| **Backend prefix** | `/api/finance/krediler` |
| **İzin kodu** | `finance.krediler` |
| **İzin seviyeleri** | `can_view` (görme), `can_use` (ekleme + düzenleme + silme) |

---

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/krediler/__init__.py` | Alt router'ları birleştirir (`prefix="/krediler"`) + geriye uyumluluk için `_match_credits_to_bank` ihracı |
| `app/routers/finance/krediler/products.py` | Kredi ürünleri CRUD (`GET/POST/PATCH/DELETE /` ve `/{id}`) |
| `app/routers/finance/krediler/payments.py` | Ödeme planı CRUD (`POST /{id}/payments`, `PATCH/DELETE /payments/{id}`) + `_match_credits_to_bank` |
| `app/routers/finance/krediler/kmh.py` | KMH durumu (`GET /{id}/kmh-status`) |
| `app/routers/finance/krediler/summary.py` | Tip bazlı özet + yaklaşan ödemeler (`/summary/by-type`, `/upcoming-payments`) |
| `app/routers/finance/krediler/_helpers.py` | Sunum yardımcıları (`_build_product_response`, `_batch_payment_stats`) |
| `app/services/credit_service.py` | Ürün/ödeme CRUD + BCH/KMH plan üreticileri (`_regenerate_bch_payments`/`_regenerate_kmh_payments`) — router + onay executor ORTAK |
| `app/routers/finance/cc_statements.py` | Kredi kartı ekstre yükleme (PDF) |
| `app/models/credit_product.py` | `CreditProduct` **ve** `CreditPayment` modelleri (ikisi de bu dosyada) |
| `app/models/credit_card_statement.py` | `CreditCardStatement`, `CreditCardTransaction` modelleri |
| `app/utils/cc_statement_parser.py` | PDF ekstre ayrıştırıcı |
| `app/schemas/credit.py` | Pydantic şemalar |
| `app/schemas/credit_card.py` | Kredi kartı Pydantic şemalar |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/routes/dashboard/finans/krediler/+page.svelte` | Ana sayfa — lacivert/altın master-detail + 3 görünüm (aşağıda) |

---

## Yeniden Tasarım — Lacivert/Altın Master-Detail + 3 Görünüm (2026-07-05)

GitHub'a yüklenen tasarım paketinin (`Krediler Yeniden Tasarım.dc.html` + `Krediler Mobil.dc.html`,
claude.ai/design) uygulanması. **Frontend-only** — backend sözleşmesi değişmedi; sayfa mevcut
endpoint'lerden beslenir. [[lacivert-altin-tema]] token yeniden eşlemesini kullanır (`teal-700`=lacivert,
`brass-*`=altın); sayfa kodu `teal-700`/`brass-light` sınıflarıyla yazılır, görsel çıktı lacivert/altındır.

**Düzen — tek beyaz kart içinde (kullanıcı Cariler dersi: tasarım uygulanınca DÜZEN dönüşür):**
1. **Lacivert KPI hero** (`bg-teal-700`) — eyebrow + serif H1 "Kredi Portföyü & Ödeme Planı" + canlı kur/tarih
   + **5 KPI**: Toplam Borç EUR (altın) · TL Krediler · EUR Krediler · Bu Ay Ödenecek · Vadesi Yaklaşan (≤30g, mercan).
   KPI'lar **frontend'de** hesaplanır (ürün listesi + TCMB kuru; ayrı endpoint yok).
2. **Görünüm segmenti** (`SegmentedControl`) + PDF Rapor + Yeni Kredi.
3. **Görünümler:**
   - **Krediler (master-detail):** SOL = aktif krediler **vadeye göre** sıralı (vurgu çubuğu + tip rozeti +
     ilerleme + vade rozeti) + altta "Kapalı" bölümü. SAĞ = seçili kredi detayı (4 KPI + kullandırım→vade
     zaman çizgisi + **Ödeme Planı / Bilgiler** sekmeleri). Mobilde liste↔detay geçişli (geri butonu).
   - **Taksit Takvimi:** tüm aktif kredilerin taksitleri ay ay akordiyon (TL/EUR ayrı toplanır) — `upcoming-payments?days=365&include_paid=true`.
   - **Banka Dağılımı:** banka bazlı EUR konsolide (kalan borç) kartlar + kullandırım→vade çizgi çubukları;
     krediye tıkla → Krediler görünümünde seçilir. **Kural (2026-07-05, kullanıcı kararı):** kredi kartları
     kalan borcu 0 olsa da **limitiyle + "borç yok" rozetiyle** gösterilir (aktif banka imkânı); diğer krediler
     yalnız kalan borcu > 0 ise listelenir. Kart €0 borç kattığından banka toplamını değiştirmez.

**Tip-bazlı detay (Plan sekmesi):** `taksitli/spot/bch/leasing` → ay-ay ödeme planı akordiyonu (ödendi
toggle · taksit sil · + Taksit); `kmh` → çeyreklik KMH görünümü (stat kart + tahakkuk tablosu + hareketler
+ devir); `kredi_karti` → ekstre sürükle-bırak yükleme + ekstre listesi/detayı. **Korunan tüm özellikler:**
ürün CRUD, taksit yönetimi, KMH, kart ekstresi, kapat/yeniden-aç, PDF (`PdfPreviewModal`), onay akışı, WS
`finance_updated` canlı yenileme.

**KPI hesap kuralı (tasarım mockup'ıyla hizalı):** "Bu Ay Ödenecek" **yalnız gerçek planlı taksitleri**
sayar (`next_payment_amount` dolu); kredi kartının tüm bakiyesini KATMAZ (şişme engeli). "Vadesi Yaklaşan"
planlı taksit tutarını, kartta ise son-ödeme (`end_date`) kalan bakiyesini sayar. EUR konsolidasyon TCMB
`forex_selling` ile; kur yoksa `—` + "bazı kurlar eksik".

**Dar-panel taşma düzeltmesi (2026-07-05, kullanıcı bulgusu):** Dış kart `overflow-hidden` (yuvarlak köşe)
olduğundan, sol menü açıkken daralan detay panelinde **kırılamayan** dizeler (mono para tutarları, tarihler,
tek-kelime banka adları) sığmayıp sert kırpılıyordu ("₺6.340." gibi). Kök çözüm: (1) master-detail yan-yana
**yalnız ≥`lg`** (1024px); altında tam-genişlik liste↔detay (iPad'de detay tam açılır). (2) Detay KPI değeri
uzunluğa göre fontu küçültür (`kpiSize`, kırpma yerine) + `grid-cols-2 xl:grid-cols-4`. (3) Ödeme planı dar
panelde kompakt 3-kolon (Anapara/Faiz alt satırda), tam 6-kolon tablo yalnız `xl`. (4) Bilgiler kartları
`xl`'e kadar tek sütun; sayısal değerlere `min-w-0`. KMH/kart özet ızgaraları da `xl:grid-cols-4`.

**Denetim (4-boyut düşmanca Workflow, 2026-07-05) sonrası uygulanan düzeltmeler:** WCAG AA — veri taşıyan
`text-gray-400` → `gray-500` (en açık gövde tonu kuralı); görünüm 'krediler'e dönünce seçili detay tazelenir
(WS başka görünümdeyken güncellerse bayat plan göstermez); "Yeniden Aç" onayı artık yıkıcı-olmayan (kırmızı
"Sil" yerine); silme/güncelleme catch'lerine `showToast`; zorunlu alanlara kırmızı `*`; takvimde tüm ayları
kapatma engeli kalktı (`calInitialized`); KMH yüklemede skeleton; para-birimi vurgu renkleri tek yorumlu
sabitte (`CUR_BAR`/`CUR_TEXT` — TL=brass token, EUR=tasarıma özel mavi, bilinçli hex istisnası).

---

## Veritabanı Şeması

### `credit_products`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `type` | varchar(30) | Kredi tipi (`bch`, `kmh`, `kredi_karti` vb.) |
| `name` | varchar(200) | Ürün adı |
| `bank_name` | varchar(100) | Banka adı |
| `company` | varchar(200) | Firma |
| `currency` | varchar(5) | Para birimi |
| `total_amount` | numeric(15,2) | Toplam kredi tutarı |
| `remaining_amount` | numeric(15,2) | Kalan tutar |
| `interest_rate` | numeric(6,4) | Faiz oranı (%) |
| `bsmv_rate` | numeric(6,4) | BSMV oranı (%) |
| `commission_rate` | numeric(6,4) | Komisyon oranı (%) |
| `linked_account_id` | integer FK → bank_accounts | KMH bağlı hesap |
| `start_date` | date | Başlangıç tarihi |
| `end_date` | date | Bitiş tarihi |
| `status` | varchar(20) | `active` / `closed` |
| `closed_date` | date | Kapatılma tarihi (`status='closed'` olunca) |
| `details` | text | Türe özgü ek bilgiler |
| `notes` | text | Notlar |
| `created_by` | integer FK → users | |
| `created_at` / `updated_at` | timestamptz | |

### `credit_payments`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `credit_product_id` | integer FK | |
| `installment_no` | integer | Taksit no |
| `due_date` | date | Vade tarihi |
| `amount` | numeric(15,2) | Toplam taksit |
| `principal` | numeric(15,2) | Ana para payı |
| `interest` | numeric(15,2) | Faiz payı |
| `bsmv` | numeric(15,2) | BSMV payı |
| `commission` | numeric(15,2) | Komisyon payı |
| `is_paid` | boolean | Ödendi mi |
| `paid_date` | date | Ödenme tarihi |
| `bank_transaction_id` | integer FK → bank_transactions | Banka eşleşmesi |
| `match_number` | integer | Eşleştirme numarası |
| `notes` | varchar(300) | |
| `created_at` | timestamptz | |

### `credit_card_statements`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `credit_product_id` | integer FK | |
| `ekstre_no` | varchar(100) | Ekstre numarası |
| `kesim_tarihi` | date | Hesap kesim tarihi |
| `son_odeme_tarihi` | date | Son ödeme tarihi |
| `onceki_bakiye` | numeric(15,2) | Önceki dönem bakiyesi |
| `donem_harcama` | numeric(15,2) | Dönem harcama toplamı |
| `faiz_ucret` | numeric(15,2) | Faiz ve ücretler |
| `donem_odeme` | numeric(15,2) | Dönem ödeme |
| `toplam_borc` | numeric(15,2) | Toplam borç |
| `asgari_odeme` | numeric(15,2) | Asgari ödeme tutarı |
| `is_paid` | boolean | Ödendi mi? |
| `paid_amount` | numeric(15,2) | Ödenen tutar |
| `paid_date` | date | Ödeme tarihi |
| `file_name` | varchar(255) | PDF dosya adı |
| `file_url` | varchar(500) | Sunucu dosya yolu |
| `uploaded_by` | integer FK → users | |
| `created_at` | timestamptz | |

---

## API Endpoint'leri

### Kredi/Kart Ürünleri (`/krediler`)
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/krediler/` | view | Ürün listesi (tür filtresi) |
| `POST` | `/krediler/` | use | Yeni kredi/kart ekle |
| `GET` | `/krediler/summary/by-type` | view | Tür bazlı özet (toplam borç, aylık ödeme) |
| `GET` | `/krediler/upcoming-payments` | view | Yaklaşan ödemeler (30 gün) |
| `GET` | `/krediler/{id}` | view | Ürün detayı + ödeme planı |
| `PATCH` | `/krediler/{id}` | use | Ürün güncelle |
| `DELETE` | `/krediler/{id}` | use | Ürün sil |
| `POST` | `/krediler/{id}/payments` | use | Ödeme planı oluştur/güncelle |
| `PATCH` | `/krediler/payments/{id}` | use | Ödeme güncelle (durum, tarih) |
| `DELETE` | `/krediler/payments/{id}` | use | Ödeme sil |
| `POST` | `/krediler/{id}/close` | use | Krediyi kapat (erken tahsil/kapanış) |
| `POST` | `/krediler/{id}/reopen` | use | Kapalı krediyi yeniden aç (geri al) |

### Kredi Kartı Ekstresi (`/krediler/kart`)
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `POST` | `/krediler/kart/auto-upload` | use | PDF ekstre — kart otomatik algıla |
| `POST` | `/krediler/kart/{product_id}/upload` | use | Belirli karta ekstre yükle |
| `GET` | `/krediler/kart/{product_id}/statements` | view | Ekstre listesi |
| `GET` | `/krediler/kart/{product_id}/statements/{id}` | view | Ekstre detayı + işlemler |
| `DELETE` | `/krediler/kart/{product_id}/statements/{id}` | use | Ekstre sil |

---

## Kredi Türleri

| type | Açıklama |
|---|---|
| `kredi` | Banka kredisi — taksitli ödeme planı |
| `kredi_karti` | Kredi kartı — aylık ekstre yükleme |

---

## Ödeme Planı Hesaplama (Kredi)

`_regenerate_bch_payments()` fonksiyonu eşit taksit (annüite) formülüyle ödeme planı oluşturur:

```
M = P × r(1+r)^n / ((1+r)^n - 1)
```
- `P` = Ana para
- `r` = Aylık faiz oranı
- `n` = Taksit sayısı

---

## PDF Ekstre Ayrıştırma (Kredi Kartı)

`app/utils/cc_statement_parser.py`:
- pdfplumber kullanarak metin çıkarımı
- Türkçe banka ekstresi formatlarını tanır
- Kart no son 4 hane, kesim tarihi, son ödeme tarihi, işlem listesi çıkarılır
- Kart otomatik eşleşmesi: `credit_products.details → kart_no_son4`

### Dosya Yükleme Güvenliği
- **MIME doğrulaması:** `%PDF` magic bytes kontrolü
- **Boyut limiti:** Maksimum 25 MB
- **Uzantı kontrolü:** Yalnızca `.pdf`

---

## finance_events Entegrasyonu

### Kredi Ödemesi
```python
finance_event_svc.upsert_credit_payment(db, payment, product)
```

| finance_events alanı | Değer |
|---|---|
| `source_type` | `"credit"` |
| `direction` | `-1` (gider) |
| `amount` | `payment.amount` |
| `currency` | `product.currency` |
| `event_date` | `payment.payment_date` |
| `event_status` | `payment.status` |
| `bank_name` | `product.bank_name` |
| `is_realized` | `True` (paid) veya `False` (pending) |

### Kredi Kartı Ekstresi
```python
finance_event_svc.upsert_cc_statement(db, statement, product)
```

| finance_events alanı | Değer |
|---|---|
| `source_type` | `"cc_payment"` |
| `direction` | `-1` (gider) |
| `amount` | `statement.toplam_borc` |
| `event_date` | `statement.son_odeme_tarihi` |
| `is_realized` | `statement.is_paid` |

---

## Banka Bazlı Görünüm — Kredi Zaman Çizgileri (2026-06-07)

Sayfa üstündeki "Banka Bazlı Kredi Dağılımı" artık **donut grafik değil**, her bankanın kartında
kredileri **zaman çizgisi** olarak gösterir (`creditTimeline()` + `TIER_*` map'leri, +page.svelte):
- **Sol = açılış (`start_date`), sağ = vade (`end_date`)**; arada ilerleme çubuğu.
- **İlerleme** = `(bugün − açılış) / (vade − açılış)` → çubuk **vadeye yaklaştıkça uzar**.
- **Aciliyet kademesi** (`daysToDue`): >90g ince (`h-3px`) · ≤90g · ≤30g · vadesi geçti kalın (`h-8px`)
  → **yaklaştıkça daha kalın + kontrast**. "Bugün" işareti = noktacık.
- **Döviz ayrımı:** **TRY** kredileri teal→amber→turuncu→kırmızı (aciliyet) rampası; **EUR** kredileri
  **mavi** rampa (`TIER_*_EUR`) + mavi tutar + hafif mavi arka plan → döviz kredileri bir bakışta ayrışır.
- **Sıralama:** vadesi yaklaşan kredi **en üstte** (`end_date` artan; vadesizler/KMH-kredi kartı en sonda).
- **Tıklama** → kredinin **ödeme planı popup (Modal)** olarak açılır (`openPlanModal`): başlık (ad/banka/kalan)
  + **sade taksit listesi** — her satır yalnız **tarih · tutar · durum** (Ödendi/Gecikmiş/Bekliyor). Yetkili
  kullanıcı durumu tıklayarak ödendi/ödenmedi yapar (`togglePaymentInModal` → kalan borç tazelenir). Taksit
  kırılımı (anapara/faiz/vergi) ve ay-akordiyonu yok — yalın gösterim.
- Kart başlığında banka adı + kredi sayısı + **toplam (EUR)**; vadesiz (rotatif) krediler "Vadesiz · rotatif".
- Eski donut/`segmentColor`/`computeSegments` kaldırıldı. Salt-frontend değişiklik (backend/test etkilenmez).

## Banka Eşleştirme (Krediler)

`_match_credits_to_bank(db)` (krediler.py):
- Aylık taksit ödemeleri banka işlemleriyle eşleştirilir
- Tutar farkı ≤ %1 ve tarih farkı ≤ 3 gün toleransı
- Gruplanmış ödemeler (faiz+ana para ayrı transferler) de desteklenir

### Faz 1 (2026-07-11) — öneri bandı, N-1 grup izi ve geri alma

- **İki-eşikli bant:** skor ≥ 40 otomatik eşleşir; **20–39 bandındaki** en iyi aday
  "Eşleşme Önerileri" kuyruğuna düşer (`event_matches method='suggestion'`; Nakit Akım
  sayfasındaki panelden Onayla/Reddet).
- **N-1 grup izi:** faiz+vergi ayrı satır grup eşleşmesi artık grubun **TÜM banka
  satırlarına** ortak `match_number` + satır başına `event_matches` izi yazar (eskiden
  yalnız ilk satır iz alıyordu → mutabakatta kanıtsız satır + yarım geri alma).
- **Geri alma:** `POST /cash-flow/unmatch-credit-payment` taksiti açar + anaparayı
  `remaining_amount`'a iade eder; N-1 grupta bağlı TÜM banka satırlarını çözer
  (banka FE'si realized kalır).
- Eşleşme kurulumu ortak `apply_credit_bank_match` uygulayıcısıyla (FOR UPDATE SKIP LOCKED
  yarış-korumalı; grup uygulamasında taksit kilidi). Detay: `docs/modules/nakit-akim.md` "Faz 1".

---

## Kredi Kapatma (Erken Tahsil / Kapanış) — 2026-05-26

Bir kredi erken kapatıldığında (ör. balon ödeme vadesinden önce tahsil edilerek
kapatılması) ileri vadeli ödenmemiş taksitler artık gerçekleşmeyecektir. Bunları
nakit akımdan çıkarmak için kapatma akışı eklendi.

### Veritabanı
- `credit_products.closed_date` (date, nullable) — `status='closed'` olduğunda kapanış
  tarihi. Migration: `c7f9a2b4d6e8_add_credit_closed_date.py`
- `status` değerleri: `active` (varsayılan) ↔ `closed`

### `POST /krediler/{id}/close`
- Body: `{ "closed_date": "YYYY-MM-DD" }` (opsiyonel, varsayılan bugün)
- `status='closed'`, `closed_date` set edilir
- **Ödenmemiş (`is_paid=False`) tüm taksitlerin finance_events kayıtları
  `finance_event_svc.invalidate(db, "credit", payment.id)` ile silinir** → nakit akımdan düşer
- **Ödenmiş taksitlere ve taksit kayıtlarının kendisine DOKUNULMAZ** — iz/geçmiş korunur
- `check_approval` (update action) + audit log + WS broadcast
- Zaten kapalıysa 400 döner

### `POST /krediler/{id}/reopen`
- `status='active'`, `closed_date=None`
- **Ödenmemiş taksitlerin finance_events kayıtları yeniden oluşturulur**
  (`upsert_credit_payment`) → nakit akıma geri döner
- Tam geri-alınabilir (kapatma ↔ açma idempotent)
- Açıksa 400 döner

### Neden taksit kaydı silinmiyor?
- Denetim izi: "kredi hangi planla kapatıldı" sorusu yanıtlanabilir kalır
- Yeniden açma mümkün olur (taksit varsa FE yeniden üretilebilir)
- Kapanış günü için **ayrı bir ödeme kaydı oluşturulmaz** — gerçek kapanış ödemesi
  zaten banka ekstresinde işlem olarak görünür (çift sayım önlenir)

### Kapalı Krediler Tüm Özet/Projeksiyonlardan Hariç (status='active' filtresi)
Kapalı kredinin taksit kayıtları DB'de durduğu için, **aggregate eden tüm endpoint'ler
`CreditProduct.status == 'active'` filtresi uygulamalıdır** — aksi halde kapalı kredi
özet kartlarında / yaklaşan ödemelerde / EUR projeksiyonunda hayalet gibi görünür.
Filtre uygulanan yerler:
- `summary/by-type` (tip bazlı kartlar) — zaten vardı
- `list_products` (banka bazlı dağılım frontend'de bundan türer) — `status` parametresi
- `upcoming-payments` (yaklaşan ödemeler) — **2026-05-26 eklendi**
- `cash_flow/eur_balances.py::all_credit_payments` (EUR bakiye projeksiyonu) — **2026-05-26 eklendi**
- `cash_flow/listing.py` mobile-dashboard "vadesi geçmiş kredi taksitleri" — **2026-05-26 eklendi**

**Kritik:** Yeni bir kredi aggregate'i (toplam borç, taksit sayımı, projeksiyon) eklerken
`CreditPayment`'ı doğrudan sorgulamak yerine `CreditProduct` ile join edip
`status == 'active'` filtresi koymak zorunludur. Test: `TestCloseReopen` içinde
`test_closed_credit_excluded_from_summary` + `_from_upcoming` + `_from_active_list`.

### Frontend
- Kredi detay başlığında **Kapat** butonu (modal: kapanış tarihi seçimi) /
  kapalı kredilerde **Yeniden Aç** butonu
- Kredi listesinde kapalı krediler "Kapalı" rozeti + üstü çizili ad ile gösterilir
- Ödeme planında kapalı kredinin ödenmemiş taksitleri "Kapatıldı" rozetiyle görünür
- İlk uygulama: Halkbank TL Spot Kredi 2 (id=15) 25.05.2026 kapatıldı → 27.07.2026
  vadeli 11.39M TL balon taksiti nakit akımdan çıkarıldı

---

## Ödeme Planı Akordiyon Görünümü — 2026-05-26

Ödeme planı tablosu (kredi kartı ve KMH hariç tüm tipler) artık **ay ay akordiyon**
olarak gruplanır:
- Taksitler `due_date`'in `YYYY-MM` değerine göre gruplanır, kronolojik sıralı
- Her ay başlığı: ay etiketi (ör. "Tem 2026") + ödenen/toplam sayısı + durum rozeti
  (Gecikmiş / Tamam) + ay toplam tutarı
- **Varsayılan açık:** ödenmemiş taksiti olan aylar; tamamı ödenmiş aylar kapalı başlar
- `paymentMonths` (`$derived.by`) gruplama + `expandedMonths` (Set) açık ay takibi
- Uzun ödeme planlarında (BCH/taksitli kredi 12+ ay) okunabilirliği artırır

### Taksit Takvimi — Ay Ay Akordiyon (2026-06-01)
Krediler sayfası üstündeki "Yaklaşan Ödemeler (30 gün)" kutusu artık **Taksit Takvimi** —
tüm aktif kredilerin taksitlerini (**ödenen + kalan**) ay ay akordiyon olarak gösterir:
- `upcoming-payments?days=365&include_paid=true` ile **bu ayın başından** itibaren 12 aylık
  taksitler çekilir (ödenmiş dahil). Endpoint `include_paid` param'ı: `True` iken ödenenler
  de döner + aralık ay başından başlar; `False` (varsayılan) eski davranış (sadece ödenmemiş,
  bugünden itibaren). Yanıta `is_paid` + `paid_date` eklendi.
- `upcomingMonths` (`$derived.by`) — tüm krediler birleşik, `YYYY-MM` bazında gruplanır
- Ay başlığı: ay etiketi + ödenen/toplam sayısı + **para birimi bazında ödenen/kalan toplam**
  ayrı (EUR + TL karışık olabilir → `monthTotalLabel`). Örn: "Kalan: ₺643.372 · Ödenen: ₺1.782.083"
- Ödenen taksit yeşil "Ödendi" rozeti + üstü çizili tutar; gecikmiş kırmızı rozet
- **Varsayılan açık:** bu ay (ilk grup); `expandedUpcomingMonths` (Set) ile takip
- **Neden:** 1 Haziran gibi bu ay ödenen taksitler de takvimde "ödendi" görünmeli, ay
  toplamında ödenen/kalan ayrımı yapılmalı (kullanıcı talebi)

---

## Audit Log Entegrasyonu

| entity_type | Kaydedilen eylem |
|---|---|
| `credit_product` | create, update, delete |
| `credit_payment` | create, update, delete |
| `cc_statement` | create (yükleme), delete |

---

## Geliştirme Kuralları

1. **Kredi silme:** Ödemeler varsa ürün silinemez — önce tüm ödemeler silinmeli
2. **Ödeme planı yenileme:** Faiz veya ana para güncellenmesi durumunda `_regenerate_bch_payments()` otomatik çağrılır
3. **Kart ekstresi:** Aynı kart için aynı kesim tarihli ekstre iki kez yüklenemez (409 conflict)
4. **Para birimi:** Dövizli kredilerde `amount_try` günlük kur güncellenmesi sırasında yeniden hesaplanır
5. **WS broadcast:** `broadcast_finance_update(background_tasks, "credits", ...)` her değişiklikte tetiklenir
6. **Kalan borç otomatik güncelleme:** Taksit "Ödendi" işaretlendiğinde `remaining_amount` otomatik azaltılır, "Geri al" yapıldığında tekrar eklenir
   - **Sadece `principal` (anapara) değeri olan taksitlerde** çalışır — `principal` yoksa bakiyeye dokunulmaz
   - Neden: Taksit tutarı (`amount`) faiz + komisyon + anapara toplamıdır, anapara bilinmeden bakiye doğru düşürülemez
   - Bakiye negatife düşemez (`max(0, ...)`)
   - Frontend'de de anlık güncelleme yapılır (backend commit'i beklemeden kart üzerinde yansır)
   - **Otomatik banka eşleştirmesinde de** (`_match_credits_to_bank`) aynı mantık uygulanır — ekstre yüklenip taksit otomatik eşleştirildiğinde `remaining_amount` anapara kadar düşer

## Banka Bazlı Simit Grafik — EUR Konsolide (2026-04-20)

- Krediler sayfası üstünde özet kartlarının altında **"Banka Bazlı Kredi Dağılımı (EUR)"** bölümü gösterilir
- **Tek banka = tek grafik** — TL / EUR / USD / GBP tüm para birimleri **tek simit grafikte** birleştirilir
- **Konsolidasyon para birimi: EUR** — tüm segmentler TCMB satış kuru ile EUR'a çevrilir
- Sağ üstte güncel `1 € = X ₺` kuru bilgi amaçlı gösterilir
- **Kur kaynağı:** `/finance/exchange-rates/latest` — paralel olarak `loadData()` içinde çekilir
- **Dönüşüm zinciri (`toEur()`):**
  - EUR → olduğu gibi
  - TRY → `amount / eurRate`
  - USD → `(amount * usdRate) / eurRate` (çapraz kur)
  - GBP → `(amount * gbpRate) / eurRate`
  - Kur eksikse `null` — grup header'ında "bazı kurlar eksik" uyarısı gösterilir
- Gruplama anahtarı: `bank_name || company || 'Atanmamış'` (currency anahtara dahil DEĞİL)
- Segment uzunluğu `_eur / totalEur` oranına göre hesaplanır — krediler EUR değerine göre azalan sırada
- `remaining_amount > 0` ve `_eur > 0` olan gruplar gösterilir (kuru yokken toplam 0 ise grup gizlenir)
- Grafik merkezinde toplam **EUR cinsinden** kompakt formatta (ör. `1,2M €`)
- Legend'da her kredi kendi **orijinal para biriminde** gösterilir (TL kredi `1M ₺`, EUR kredi `50K €`)
- **Tooltip:** `<title>` ile segment hover'da orijinal tutar + EUR karşılığı gösterilir
- **Tıklama davranışı:**
  1. Segment veya legend öğesine tıklandığında `scrollToCredit(id, type)` çağrılır
  2. Kredi açık değilse `toggleExpand()` ile açılır
  3. `setTimeout(100ms)` sonrası `scrollIntoView()` ile ilgili karta smooth scroll yapılır
  4. Kart `id="credit-{p.id}"` ile hedeflenir, `scroll-mt-20` ile topbar altında kalmaz
- Listede aktif olarak genişletilmiş kredi, legend'da `bg-gray-100` ile vurgulanır
- **Neden EUR?** — Finans modülünde EUR birincil raporlama para birimi (Nakit Akım, Bankalar da EUR toplam gösterir); TL'nin volatilitesi çoklu para biriminde net büyüklük kıyasını zorlaştırır

---

## Taksit Eşleşmesini Geri Al (2026-07-11, frontend)

Ödeme planında **ödenmiş + banka-eşleşmiş** (`is_paid` + `bank_transaction_id` dolu) taksit
satırının aksiyonlarında ikon-only **Geri Al** butonu (Lucide `Undo2`, `canUse` + ürün kapalı
değilken; yoğun-tablo ikon-only istisnası — mevcut X/durum butonlarıyla aynı düzen).
`ConfirmDialog` onayı ("taksit yeniden Bekliyor durumuna dönecek", danger değil) sonrası
`POST /api/finance/cash-flow/unmatch-credit-payment {payment_id}` çağrılır: taksit açılır,
anapara `remaining_amount`'a iade edilir, N-1 grup eşleşmesindeki bağlı TÜM banka satırları
çözülür. Başarıda toast + `loadData()`. Endpoint izni `finance.cash_flow use` — backend
detayı: `docs/modules/nakit-akim.md` "Geri alma uçları (#10)". Not: bankayla eşleşmiş taksitte
doğru geri alma yolu budur; "Ödendi" rozetine tıklamak yalnız `is_paid`'i çevirir, banka
eşleşmesini ÇÖZMEZ.
