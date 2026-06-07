# Yönetim Paneli + Maliyet Kontrol

## Genel Bilgi
- **Modüller:** `yonetim` (üst), `yonetim.panel` · ve **Maliyet Kontrol** = `stok.maliyet` (yeniden tasarım)
- **Frontend:** `/dashboard/yonetim` (sidebar'da Panel'in altında, standalone) · `/dashboard/stok/maliyet`
- **Backend:** `/api/yonetim` (`app/routers/yonetim.py`) · `/api/stok/operational-kpi`, `/price-variance`
- **Kaynak:** Sedna stok (TRY maliyet) + rezervasyon (geceleme/doluluk) + finans modülleri — **füzyon**

Otelcilikte gerçek maliyet kontrolü operasyon (satın alma→depo→tüketim) ile doluluğun
(geceleme/pax) füzyonuyla anlam kazanır. Bu modül **all-inclusive otelin can damarı KPI'larını**
hesaplar: kişi başı F&B maliyeti, CPOR, stok devir hızı, fiyat sapması + üst düzey GM paneli.

## Operasyonel KPI füzyonu (`app/utils/occupancy.py` + `stock.py:compute_operational_kpi`)
- **Geceleme/oda-gece** rezervasyondan **occupancy-overlap** ile (generate_series): bir konaklama
  birden çok aya yayılırsa her ayın gecelemesine doğru pay düşer — stok tüketim ayıyla eşleşir.
  `guest_nights = SUM(pax×gece)`, pax=adult+child_paid+child_free+baby, checkout EXCLUSIVE.
- **Departman → maliyet grubu** (`stock_depots.cost_group`, import'ta türetilir): `fb` (002 ANA
  MUTFAK, 003 BARLAR, 006 STEWARD, 010 MİNİBAR) · `rooms` (005 HK, 007 ÇAMAŞIRHANE, 117) · `staff`
  (004, 020) · `technical` · `waste` (030 ZAYİ) · `capex` (100-116) · `overhead`.
- **Kişi başı F&B maliyeti** = F&B tüketim (`fb`, direction=consume) ÷ geceleme. **CPOR** = oda
  bölümü tüketim ÷ oda-gece. **Zayiat %** = zayi ÷ toplam. **Devir hızı** = tüketim ÷ anlık stok değeri.
- **Eşleşen aylar kuralı (kritik):** Tüketim (Type 29) ay-sonu sayımla **geç post edilir**; doluluğu
  olup tüketimi henüz girilmemiş aylar headline'ı dilüye etmesin diye KPI yalnız **fb>0 & geceleme>0**
  aylar üzerinden hesaplanır (`matched_periods`). Canlı: Mart 1.223 · Nisan 883 TL/kişi/gece.

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/stok/operational-kpi` | stok.maliyet view | Füzyon KPI: kişi başı maliyet, CPOR, devir, zayiat, aylık + by_group |
| GET | `/stok/price-variance` | stok.maliyet view | Ürün satın alma fiyat sapması (son vs ortalama, ≥2 alış) |
| GET | `/yonetim/dashboard` | yonetim.panel view | Üst düzey: doluluk + maliyet + oda geliri + tedarikçi borcu + avans + GOP~ |
| GET | `/yonetim/alerts` | yonetim.panel view | Fiyat sapması + tedarikçi borcu top + kritik stok |
| GET | `/yonetim/cost-classification` | yonetim.panel view | Sabit/değişken/yarı-değişken göstergesi (yıllık TRY) |

`yonetim.py` **yeni hesap mantığı içermez** — mevcut servisleri çağırır: `occupancy_metrics`,
`compute_operational_kpi`, `compute_price_variance`, `_get_vendor_net_debts`, `_merged_advances`,
`ScheduledEntry` toplamları, `SalesInvoice`. Banka/nakit/90-gün projeksiyon/vadesi gelen çek-kredi
frontend'de mevcut endpoint'lerden (`/cash-flow/mobile-dashboard`, `/krediler/upcoming-payments`) çekilir.

## Frontend
- **Yönetim Paneli** (`/dashboard/yonetim`): 10 KPI hero (banka/doluluk/ADR/RevPAR/kişi başı maliyet/
  GOP~/devir/oda geliri/tedarikçi borcu/Food Cost%[bloke]) + uyarılar grid (çek/kredi/cari/avans/fiyat
  sapması linkli) + sabit-değişken kartı.
- **Maliyet Kontrol** (`/dashboard/stok/maliyet`): operasyonel KPI kartları + maliyet-grubu çubukları
  + **aylık F&B tüketim vs doluluk** + fiyat sapması + tedarikçi sıralaması + bloke-KPI placeholder.

## Bloke KPI'lar (Faz 2 — PMS erişimi)
Gerçek **Food/Beverage Cost %**, **reçete sapması** (teorik vs gerçek), **milliyet bazlı tüketim**
reçete (Standart Reçete) + POS satış verisi gerektirir. Sedna `btadmin` şu an yalnız muhasebe DB'sine
erişir. Açmak için (Sedna SQL admin, her PMS/F&B DB'de):
```sql
USE [<PMS_DB>]; CREATE USER [prenses\btadmin] FOR LOGIN [prenses\btadmin];
ALTER ROLE db_datareader ADD MEMBER [prenses\btadmin];
```

## Test
`tests/test_cost_control.py` (occupancy hesabı + füzyon KPI + eşleşen-ay dışlama + fiyat sapması +
yonetim dashboard/alerts/classification + izin). Canlı: kişi başı 970.98 TL, doluluk %44.3, GOP~46M.
