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
| GET | `/stok/products` | stok.urunler view | Ürün listesi (paginated, `search`, `in_stock`; değer azalan) |
| GET | `/stok/movements` | stok.hareketler view | Hareket listesi (paginated, `direction`, `depot`, `search`, tarih) |
| GET | `/stok/depots` | stok.depolar view | Depo listesi + toplam tüketim |
| POST | `/stok/sedna-import` | stok.maliyet use | Sedna'dan içe aktar (tekil; merkezi sync de çağırır) |

## Frontend
- **Maliyet Analizi** (`/maliyet`): 4 StatCard (anlık stok değeri / toplam alım / toplam tüketim /
  depo sayısı) + **departman tüketim çubukları** (hero) + aylık alım-tüketim trendi + tedarikçi çubukları.
- **Ürünler & Stok** (`/urunler`): arama + "stokta olanlar" filtresi + tablo (kod/ad/stok/maliyet/değer).
- **Hareketler** (`/hareketler`): yön filtresi (alış/tüketim/çıkış/sayım) + arama + tablo (renkli tip rozeti).
- **Depolar** (`/depolar`): departman listesi + toplam tüketim çubuğu (maliyet merkezi sıralı).

## Audit
- `entity_type=stock`, `action=create` (içe aktarma özeti loglanır).

## Geliştirme kuralları / kapsam
- **Erişim sınırı:** Sedna `btadmin` yalnızca **muhasebe DB'sine** (Mhs2026) erişir; PMS/bordro/anket
  DB'leri kapalı. Stok verisi muhasebe stok modülündendir (F&B + malzeme + demirbaş hareketleri).
- **Maliyet odaklı v1:** tüketim/alım kırılımı + anlık değer. İleride: kritik-stok uyarısı, ürün
  bazında maliyet trendi, depo-içi anlık stok dökümü.
- Test: `tests/test_stock.py` (import/dedup + summary + departman + trend + tedarikçi + filtre + izin).
