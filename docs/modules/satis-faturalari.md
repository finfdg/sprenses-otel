# Satış Faturaları Modülü (Otel Oda Satışları + Tahsilat)

## Genel Bilgi
- **Modül kodu:** `finance.sales_invoices`
- **Üst modül:** Finans (`finance`)
- **Frontend rota:** `/dashboard/finans/satis-faturalari`
- **Backend prefix:** `/api/finance/sales-invoices`
- **İzin:** `finance.sales_invoices` (view / use)
- **Kaynak:** Sedna muhasebe (120/Alıcılar), ters SSH tüneli — **cariler'in (320/Satıcılar) aynası**

Otel oda/hizmet satış faturaları ve **tahsil edilip edilmediği** burada takip edilir. Veri Sedna'dan
otomatik çekilir (Topbar'daki merkezi **"Sedna" butonu** → yeni adım). Tahsil durumu, müşteri bazında
tahsilatların faturalara **FIFO** (en eskiden) düşülmesiyle hesaplanır.

## Sedna eşlemesi (2026-06-06 — canlı doğrulandı)
- **Fatura** = `AccountingTrans` 120 **Borç** hareketi, `DocumentType=1` (Hizmet Satış Fatura).
  Fatura no = `DocumentNo` (ör. `SPE2026000000721`), tarih = `AccountingOwner.FicheDate`, tutar = `Debit`.
- **Tahsilat** = 120 **Alacak** hareketi (herhangi belge tipi). Müşteri bazında faturalardan FIFO düşülür.
- **Münferit ↔ Acente:** Münferit (bireysel/walk-in) ≈ `120.03.*` (MÜNFERİT GENEL) veya adında "MÜNFERİT";
  diğer 120 grupları = acente/kurumsal (WEBRES, MAYTATİL TURİZM vb.). `is_munferit` bayrağı.
- **İlk canlı:** 2272 fatura (73,9M ₺) + 129 tahsilat (47M) → **26,9M açık**. Durum: 1153 ödendi, 22 kısmi, 1097 açık.

## Veritabanı
- `sales_invoices` — kesilen faturalar: `customer_code`, `customer_name`, `is_munferit`, `invoice_no`,
  `invoice_date`, `amount` (TL karşılığı), `currency`, **`amount_currency`** (döviz tutarı), `description`, `tx_hash`, `created_at`.
- `sales_collections` — tahsilatlar: `customer_code`, `customer_name`, `collection_date`, `amount` (TL),
  `currency`, **`amount_currency`**, `description`, `tx_hash`.

## Çoklu para birimi (EUR operatörler — 2026-06-06)
Yabancı operatörler (Alltours, Odeon, W2M…) **EUR** çalışır; Sedna 120'de `Debit`/`Credit` TL karşılığı,
`Curr`/`CurrDebit`/`CurrCredit` döviz tutarıdır. Modül her ikisini saklar (`amount`=TL, `amount_currency`=döviz).
- **FIFO `(müşteri, para birimi)` bazında** — EUR avans yalnız EUR faturayı kapatır; kur dalgalanması TL-düzleme
  hatasını engeller (TL FIFO yanlış olurdu).
- **Liste:** fatura tutarı **döviz** olarak gösterilir (`amount`+`currency`), TL karşılığı (`amount_tl`) ayrıca.
- **Özet/Avans:** TL toplamları konsolide; **avans bakiyesi para birimi bazında** (`advance.by_currency` /
  `total_by_currency`: `{TL: x, EUR: y}`). EUR operatörler EUR avansla görünür.
- **Manuel `finance.avanslar` ile kıyas:** Manuel modül EUR girer; artık bu modül de EUR taşıdığından
  Alltours beklenen (manuel) vs gerçekleşen (Sedna EUR) **birebir kıyaslanabilir**.
  Not: büyük operatörler çoğu zaman **net alacaklı** (avans tüketilmiş, bize borçlu) — o an net avans göstermezler.
- Dedup `tx_hash` ile (kod seviyesinde): fatura `sha256(sinv|kod|tarih|no|tutar)`, tahsilat `sha256(scol|kod|tarih|tutar|fis)`.

## FIFO tahsil durumu (`_status_map`)
Her müşteri için: toplam tahsilat havuzu, faturalara **en eskiden** dağıtılır → her fatura için
`collected` + durum:
- **paid** — tamamı tahsil (`collected >= amount`)
- **partial** — kısmi
- **open** — hiç tahsil edilmemiş

Cariler'in net-borç FIFO'sunun aynası; pooled münferit hesabında (tek 120.03 kodu) tahsilat en eski
faturalara uygulanır (doğru muhasebe davranışı).

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/sales-invoices/` | view | Liste (FIFO durum + `by_advance`/`advance_covered` + filtre: `customer_type`, `status`, `start_date`/`end_date`/`search`, paginated) |
| GET | `/sales-invoices/summary` | view | Özet: faturalanan/tahsil/açık + münferit/acente kırılımı + durum sayıları + **`advance`** (kullanılmamış net avans + acente sayısı) |
| GET | `/sales-invoices/advances` | view | **Acente avans bakiyeleri** — net avanslı müşteriler: `received` (yatırılan), `consumed` (faturayla kapanan), `remaining` (kalan). Sıralı (kalan azalan) |
| POST | `/sales-invoices/sedna-import` | use | Sedna'dan içe aktar (tekil; merkezi sync da çağırır). Onaydan muaf, audit'li |

## Acente avansları + tahsil-durumu (tarih-sıralı FIFO — `_compute`)
Acente avansları **ayrı hesapta değil**, doğrudan acentenin 120 hesabına **ALACAK** olarak yazılır; fatura
(120 Borç) kesildikçe avanstan **mahsup** edilir (netleşir). `_compute` müşteri olaylarını **tarih sırasıyla**
işler:
- **Aynı gün önce fatura, sonra tahsilat** → aynı-gün ödeme avans sayılmaz (münferit walk-in = normal tahsilat).
- Tahsilat geldiğinde en eski açık faturaya **backfill** (sonradan = normal tahsilat). Fatura kesildiğinde
  önce mevcut **avans havuzundan** karşılanır → fatura `advance_covered` (`by_advance=True` rozeti: "avansla kapandı").
- Tüm faturalardan **artan tahsilat** = müşterinin **net avans bakiyesi** (`/advances`).
- Canlı: **839.889 ₺ kullanılmamış avans / 12 acente** (ör. TUANA OPTİK 777K yatırmış, 309K faturayla kapanmış, **467,6K kalan**).

**İlişki — `finance.avanslar` (Alınan Avanslar):** O modül **elle/planlama** (beklenen avans). İki sayfa
karşılıklı linklidir. **Otomatik mutabakat** yapıldı: `GET /avanslar/sedna-reconciliation` (avanslar sayfasında
"Sedna Mutabakatı" butonu) — manuel ↔ Sedna isim eşleştirmeli kıyas.

### Acente Avansları sekmesi — 340 + 120 birleşik (2026-06-06 hizalandı)
Acente avanslarının **asıl yeri Sedna `340 "Alınan Sipariş Avansları"`** (ALLTOURS 4,75M € — manuel ile birebir).
Bazı küçük acentelerin avansı ise doğrudan **120 net-alacak** olarak durur (TUANA). "Acente Avansları" sekmesi
artık **ikisini birleştirir**:
- `sales_advances` tablosu (340 hesap özeti: code/name/currency/received/consumed) — sales import'ta **truncate+reload** (canlı 340 çekilir; sync butonu tazeler).
- `_merged_advances(db)`: 340 (asıl, öncelikli) + 120 net-alacak (`_compute`). **340'ta adı geçen 120 kaydı atlanır** (token eşleştirmeli mükerrer önleme; `advances._norm_tokens`).
- Her satır `source` taşır (`340`=Avans hesabı / `120`=Cari net). Özet kartı + liste para birimi bazında (TL/EUR).
- Canlı: **6,2M € + 10M ₺ / 28 kayıt** (ALLTOURS 4,16M €, LAVİNYA 3,43M ₺, TUANA 467K ₺[120]…).

**Manuel `finance.avanslar` ↔ Sedna mutabakatı:** `GET /avanslar/sedna-reconciliation` (avanslar sayfasında
"Sedna Mutabakatı" butonu) — manuel acente avansları **340 ile** isim eşleştirmeli kıyaslanır (Alltours +0 fark).

İçe aktarma servis fonksiyonu `run_sales_invoice_import(db, user, ip)` — merkezi Sedna sync
(`sedna_sync.py:_STEPS`) tarafından da çağrılır. Yeni adımlar gibi tek "Sedna" butonuna bağlı.

## Frontend
- PageHeader + 4 StatCard (Faturalanan / Tahsil / Açık / Acente-Münferit) + filtre barı (tür+durum chip, arama) + tablo (mobilde kart) + Pagination.
- Durum rozeti: paid=yeşil, partial=sarı, open=gri. Münferit/Acente etiketi satırda.
- Veri çekme **yalnız Topbar'daki merkezi Sedna butonundan** (sayfa-içi import butonu yok).

## Audit
- `entity_type=sales_invoice`, `action=create` (içe aktarma özeti loglanır).

## Geliştirme kuralları / kapsam (v1)
- v1: Sedna import + FIFO tahsil durumu + liste/özet. **finance_events/nakit-akım entegrasyonu YOK** (gelir tarafı ileride eklenebilir).
- Vade/ödeme vadesi yok (Sedna `PayDay=0`); "açık" = henüz tahsil edilmemiş.
- **Münferit tahsilatı düşük görünebilir** — walk-in nakit tahsilatları 120 hesabına değil POS/Folio'ya
  işleniyor olabilir; teyit edilmeli (modül 120 defterini sadık yansıtır).
- Test: `tests/test_sales_invoices.py` (import/dedup + FIFO + filtre + merkezi sync).
