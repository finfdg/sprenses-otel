# Stok / Depo Maliyet Modülü

## Genel Bilgi
- **Üst modül:** Stok (yeni ana menü) — `stok`
- **Alt modüller:** `stok.maliyet`, `stok.urunler`, `stok.hareketler`, `stok.depolar`
- **Frontend rota:** `/dashboard/stok/{maliyet|urunler|hareketler|depolar}`
- **Backend prefix:** `/api/stok`
- **Kaynak:** Sedna muhasebe (Mhs2026), ters SSH tüneli — **salt-okunur içe aktarma**

Otelin stok/depo hareketlerinden **maliyet analizi** çıkarır: departman tüketim maliyeti,
aylık alım/tüketim trendi, tedarikçi bazında alım, anlık stok değeri. Veri Sedna'dan otomatik
çekilir (Topbar'daki merkezi **"Sedna" butonu** → `stock` adımı).

## Sedna eşlemesi (2026-06-07 — canlı doğrulandı)
- **Depolar/departmanlar** = `Store` (StoreCode→code, Remark→name). Bunlar **maliyet merkezi**
  (002 ANA MUTFAK, 003 BARLAR & RESTAURANT, 008 TEKNİK, 005 HOUSEKEEPING…). 43 depo.
- **Ürün kartları** = `Product` (RecId, Code, Remark=ad, CurrencyCode, StockType). 5.243 ürün.
  **Anlık stok** = ürünün son `StockTrans.StockQuantity` (yürüyen bakiye), **son maliyet** = `Cost`.
  `current_value = current_stock × last_cost`.
- **Hareketler** = `StockOwner` (başlık: Type, Dates, ConsumptionDepot, CurrentId=tedarikçi) +
  `StockTrans` (satır: CardId=ürün, Quantity, Cost, NetAmount, depotlar). 21.879 hareket.
- **Hareket tipleri** (`StockOwner.Type` → `TYPE_MAP`): **12=Alış**, 25=Alış(Faturalı), 10=Devir,
  13=Bedelsiz → yön **in**; **29=Tüketim** → yön **consume** (`ConsumptionDepot`=departman); 20/21=Çıkış
  → **out**; 40=Sayım → **count**. Yön tüketim/alım kırılımının temelidir.
- **İlk canlı:** 134,9M ₺ alım · 27,8M ₺ tüketim · 7,38M ₺ anlık stok değeri (970/5243 üründe stok).
  Departman tüketimi: ANA MUTFAK 11,5M · TEKNİK 6,8M · BARLAR 4,7M · PERSONEL MUTFAĞI 1,25M…

## Veritabanı (3 tablo)
- `stock_depots` — depo/departman (`code` unique, `name`, `no_consumption`, `is_expense`).
- `stock_products` — ürün kartı (`sedna_id` unique, `code`, `name`, `currency`, `current_stock`,
  `last_cost`, `current_value`).
- `stock_movements` — hareket (`sedna_line_id` unique=dedup, `date`, `period` YYYY-MM, `type_code`,
  `type_label`, `direction` in/out/consume/count, `product_*`, `entry/exit/cons_depot`, `quantity`,
  `unit_cost`, `net_amount`, `supplier_*`, `doc_no`).

## İçe aktarma (`run_stock_import`)
- `fetch_stock_depots/products/movements` (sedna_client) → upsert. Depolar `code`, ürünler `sedna_id`
  ile upsert; hareketler `sedna_line_id` ile **dedup** (hareketler değişmez → yalnız yeniler eklenir,
  `bulk_insert_mappings`). Ürünün `current_value` import'ta hesaplanır.
- **Onaydan muaf** (operasyonel içe-aktarma), audit'li (`entity_type=stock`), `stok.maliyet` use.
- Merkezi Sedna sync'in adımı (`sedna_sync.py:_STEPS` → `stock`). Tekil: `POST /stok/sedna-import`.

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/stok/summary` | stok.maliyet view | Özet: stok değeri, ürün/depo sayısı, toplam alım/tüketim, son dönem |
| GET | `/stok/cost-by-department` | stok.maliyet view | Departman (ConsumptionDepot) bazında tüketim maliyeti (adlarla) |
| GET | `/stok/monthly-trend` | stok.maliyet view | Aylık alım vs tüketim (sezon analizi) |
| GET | `/stok/by-supplier?limit=` | stok.maliyet view | Tedarikçi bazında alım maliyeti |
| GET | `/stok/price-variance?limit=` | stok.maliyet view | Fiyat hareketi (`items`, medyan↔son alış, **birim=net÷miktar**) + anomaliler (`anomalies`). `items` **işaretli azalan sıralı** (artan üstte/azalan altta), **%0 hariç**. `limit=0` → cap yok (tüm hareketler) |
| GET | `/stok/product-purchases/{product_id}?limit=` | stok.maliyet view | Bir ürünün **TÜM** stok hareketleri (giriş/alış/devir/açılış/bedelsiz + çıkış/transfer + tüketim) — her hareket tür + depo akışıyla; medyan yalnız `direction='in'` üzerinden |
| GET | `/stok/product-purchases/{product_id}/pdf` | stok.maliyet view | Aynı veriyi **renkli** PDF olarak (modal "Yazdır" — reportlab + `pdf_fonts` ₺, tür bazlı satır rengi) |
| GET | `/stok/products` | stok.urunler view | Ürün listesi (paginated, `search`, `in_stock`; değer azalan) |
| GET | `/stok/movements` | stok.hareketler view | Hareket listesi (paginated, `direction`, `depot`, `search`, tarih) |
| GET | `/stok/depots` | stok.depolar view | Depo listesi + toplam tüketim |
| POST | `/stok/sedna-import` | stok.maliyet use | Sedna'dan içe aktar (tekil; merkezi sync de çağırır) |

## Frontend
- **Maliyet Analizi** (`/maliyet`): 4 StatCard (anlık stok değeri / toplam alım / toplam tüketim /
  depo sayısı) + **departman tüketim çubukları** (hero) + aylık alım-tüketim trendi + tedarikçi çubukları +
  **Satın Alma Fiyat Hareketi** (medyan↔son alış) + birim/miktar anomalileri.
  - **Sıralama + kapsam:** fiyat listesi `?limit=0` ile **tüm hareketleri** (cap yok) çeker,
    **işaretli azalan** sıralıdır (fiyatı en çok artan en üstte → en çok azalan en altta). Fiyatı
    değişmeyen (%0) ürünler varsayılan GİZLİ → liste artan→azalan okunaklı kalır. Başlıkta
    **"%0 göster/gizle" toggle** butonu (Eye/EyeOff) ile fiyatı değişmeyen ürünler de gösterilir
    (canlı: 1642 üründen 1036'sı %0, 606 gerçek hareket). Frontend `?include_zero=true&limit=0` ile
    **tümünü tek istekte** çeker, toggle client-side filtreler (`shownVariance`); %0 satırı gri.
    `max-h-72 overflow-y-auto` ile kaydırılır.
  - **Fiyat/anomali satırına tıklayınca** o ürünün **TÜM stok hareketleri** modalda açılır (max-w-4xl).
    **Görünüm geçişi**: **Gövde** (varsayılan) ↔ **Liste** (renkli tablo).
  - **Stok Hareket Gövdesi (`trunk` $derived — 2026-06-29):** Hareketleri bir **ağaç gövdesi** olarak
    gösterir: **kök = ilk dönem devir/açılışı** (en altta), gövde **yukarı doğru kronolojik büyür** (en
    güncel üstte, ↑ ok). **Sol dal = giriş (yeşil)**, **sağ dal = çıkış/transfer (amber)** — her hareket
    merkezdeki kahverengi gövde çizgisine bir nokta ile bağlanır. **Her dönem sonunda HALKA (DÖNEM SONU):**
    o anki **sayımda kalan** (yürüyen bakiye, mavi çip/depo) + **TÜKETİM** (kırmızı, depo bazında).
    **İŞ KURALI — Tüketim "kaydedilen hareket" olarak gösterilmez, sayım farkından okunur:**
    `önceki sayım + giren − çıkan − bu dönem sonu sayımı`. Veri bunu birebir doğrular: yürüyen bakiye
    pasında **Devir/Açılış = fiziksel sayım (RESET)**; bir dönemin kapanış bakiyesi = **bir sonraki ayın
    Devir/Açılış değeri** (ör. TEREYAĞ DÖKME Şub kapanış ANA DEPO=32 = Mar devri; Mar kapanış
    002=31/001=22/004=13 = Nis devirleri — birebir tutar). Halkadaki TÜKETİM rakamı bu sayım-farkına eşit
    (ay-sonu `consume` postingiyle de örtüşür).
  - **Alış'ın deposu (önemli):** Alış (`direction=in`, non-opening) hareketlerinin bir kısmı Sedna'da
    **depo etiketsiz** gelir (canlı: 6780 alıştan 1750'si boş). Etiketsiz alış **hub deposuna** (en çok
    transfer çıkışı yapan = ANA DEPO) yazılır — çünkü mutabakat bunu gerektirir: `8 + 36(alış) − 12(transfer)
    = 32` = sonraki ay ANA DEPO devri. Etiketli alış kendi deposuna gider.
  - **Açık/son dönem:** en üstteki (en güncel) dönem henüz kapanmamışsa "sayımda kalan" = **canlı yürüyen
    bakiye**, TÜKETİM henüz yoksa boş kalır (ay-sonu postingi gelince dolar).
  - **KÖK yalnız İLK dönemin açılışıdır (bug kaydı, 2026-06-29):** Sonraki ayların Devir/Açılış'ları
    kökte gösterilmez (devreden sayımı tekrar ederler). `rootDone` bayrağı **ilk dönem değişiminde**
    set edilir — yalnız non-opening harekette DEĞİL. Neden kritik: `get_product_purchases` boş postingleri
    (`qty=0 ∧ net=0`) eler; bazı üründe (ör. SOS BULYON TAVUK) erken ayların tek hareketi sıfır-tüketim
    postingidir → elenince ardışık "yalnız-devir" aylar oluşur → eski mantıkta her ayın açılışı köke
    eklenip **mükerrer depo** yaratıyordu → `{#each r.openings (o.depot)}` Svelte 5 **client**'ta
    `each_key_duplicate` fırlatıyor (SSR dup-key kontrol etmez → derleme/SSR sessiz) → modal skeleton'da
    **donuyordu**. Ek güvenlik: modal içeriği `<svelte:boundary>` ile sarıldı (render hatası → "Liste'ye
    geç" düşüşü, sonsuz skeleton yerine).
  - **Depo bazında yürüyen bakiye (kalan):** Hareketler kronolojik işlenir; **Devir/Açılış = sayım anlık
    değeri (RESET)**, alış/bedelsiz/transfer-giriş ekler, transfer-çıkış/tüketim çıkarır. Her tüketim/
    transfer/giriş altında **ilgili depo(lar)daki kalan** yazılır (`runBal` $derived, frontend). **Negatif
    kalan amber ile işaretlenir** → Sedna veri tutarsızlığını ifşa eder (canlı: Ana Depo 16.03'te 320
    açılışla 3.200 transfer → −2.880, 31.03 bedelsiz girişle 0'a düzelir). Tüketim kalanı bir sonraki
    ayın devir/sayım değeriyle birebir tutar (Bar/Restaurant doğrulandı). Boş posting (miktar=0 ∧ net=0)
    elenir. **"Yazdır"** PDF'i renkli yapıda (kalan kolonu PDF'te yok — modal-only). Modalda **"Yazdır"** butonu PDF'i
    `api.fetchRaw` ile **blob** olarak çeker → **gizli iframe + `contentWindow.print()`** ile yazdırma
    diyaloğunu tetikler (masaüstünde direkt yazıcıya gider). iOS Safari iframe-print'i yoksayarsa
    fallback: PDF yeni sekmede açılır (Paylaş → Yazdır). Banka talimatları (`talimatlar`) print deseniyle
    aynı. PDF reportlab + `pdf_fonts` (₺ destekli), tablo modal ile birebir (net÷miktar birim, sıra no).
    **NOT:** PDF yanıtında ürün adı HTTP header'ına KONULMAZ (header latin-1; "CİLA" gibi İ/Ş içeren ad
    `UnicodeEncodeError` → 500 verir). Ad yalnız PDF gövdesinde. Regresyon: `test_cost_control.py::
    test_product_purchases_pdf_turkish_name`.
  - **Birim fiyat tek baz = net ÷ miktar (gerçek ödenen)** — hem panel (`_price_variance_rows`) hem
    detay modalı Sedna'nın `Cost` (unit_cost) alanını **kullanmaz**. Neden: `Cost` bazen hatalı/0
    (ör. NAR'da 30.05 satırında Cost=359,48 ama net/miktar=6210÷46=135 → eski panel bunu %193,5 sahte
    sıçrama gösteriyordu); net tutar ise daima doğru. net÷miktar'a geçiş bu sahte sıçramaları eledi
    (NAR artık %8,4 ile listede değil). Anomali tespiti (>3× medyan) korunur: miktar paydası yanlış
    girilince net÷miktar da sapar → gerçek birim/miktar tutarsızlıkları yine `anomalies`'e düşer.
    Test: `test_cost_control.py::test_price_variance` / `test_price_anomaly_split` (seed `quantity=1,
    net_amount=unit_cost` → net÷miktar=unit_cost, davranış birebir).
- **Ürünler & Stok** (`/urunler`): arama + "stokta olanlar" filtresi + tablo (kod/ad/stok/maliyet/değer).
- **Hareketler** (`/hareketler`): yön filtresi (alış/tüketim/çıkış/sayım) + arama + tablo (renkli tip rozeti).
- **Depolar** (`/depolar`): departman listesi + toplam tüketim çubuğu (maliyet merkezi sıralı).

## Audit
- `entity_type=stock`, `action=create` (içe aktarma özeti loglanır).

## Geliştirme kuralları / kapsam
- **Erişim sınırı:** Sedna `btadmin` login'i **muhasebe DB'sini** (`SednaPrensesMhs2026`) okur; stok bu DB'den
  beslenir. (Not: aynı login 2026-06-07'den beri **önbüro/PMS DB'sini** de [`SednaPrenses`] okur — otel
  rezervasyon canlı doluluk senkronu için; bkz. `docs/modules/otel-rezervasyon.md`. Bordro/anket DB'leri kapalı.)
  Stok verisi muhasebe stok modülündendir (F&B + malzeme + demirbaş hareketleri).
- **Maliyet odaklı v1:** tüketim/alım kırılımı + anlık değer. İleride: kritik-stok uyarısı, ürün
  bazında maliyet trendi, depo-içi anlık stok dökümü.
- Test: `tests/test_stock.py` (import/dedup + summary + departman + trend + tedarikçi + filtre + izin).
