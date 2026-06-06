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
  `invoice_date`, `amount`, `currency`, `description`, `tx_hash` (dedup), `created_at`.
- `sales_collections` — tahsilatlar: `customer_code`, `collection_date`, `amount`, `description`, `tx_hash`.
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
| GET | `/sales-invoices/` | view | Liste (FIFO durum + filtre: `customer_type` munferit/agency, `status` paid/partial/open, `start_date`/`end_date`/`search`, paginated) |
| GET | `/sales-invoices/summary` | view | Özet: toplam faturalanan/tahsil/açık + münferit/acente kırılımı + durum sayıları |
| POST | `/sales-invoices/sedna-import` | use | Sedna'dan içe aktar (tekil; merkezi sync da çağırır). Onaydan muaf, audit'li |

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
