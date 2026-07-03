# Hak Ediş Takibi

## Genel Bilgi
- **Modül kodu:** `finance.hakedis` (üst modül: `finance`, modül id: 920)
- **Frontend rota:** `/dashboard/finans/hakedis`
- **Backend prefix:** `/api/finance/hakedis`
- **İzin kodu:** `finance.hakedis` (view/use)

## İş Akışı (neden var)
Rezervasyon → misafir konaklar → **çıkışta fatura kesilir = HAK EDİŞ** (acenteden alacağımız).
Anlaşma gereği firma **30 veya 45 gün** içinde ödemeli. Bu modül firma bazlı açık hak edişleri,
vadeleri ve gecikmeleri takip eder.

## Mimari Karar — Sedna'da vade YOK (2026-07-02 keşfi)
Sedna'nın tüm veritabanları incelendi (29 DB): PMS `Invoice.DueDate` her zaman `InvoiceDate`'e eşit,
`Agency.Days` tüm acentelerde 0 → **Sedna gerçek vade takibi yapmıyor.** Bu yüzden:
- **Veri kaynağı:** Muhasebe 120.* hesapları — zaten `finance.sales_invoices` modülünce import edilir
  (fatura=borç, tahsilat=alacak) ve FIFO ile eşlenir (`sales_invoice_service._compute_cached`).
  **PMS'ten ayrı import YOK** (finansal tek doğru kaynak muhasebe; mükerrer import yaratılmaz).
- **Vade katmanı yerel:** `receivable_terms` tablosu (customer_code → term_days). Tanımsız firma
  **varsayılan 30 gün** (`DEFAULT_TERM_DAYS`). 45 günlük anlaşmalılar sayfadan düzenlenir.

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Model | `backend/app/models/receivable_term.py` (`receivable_terms`) |
| Schema | `backend/app/schemas/receivable.py` |
| Servis | `backend/app/services/receivable_service.py` — vade+yaşlandırma hesabı; `upsert_term` router+executor ORTAK |
| Router | `backend/app/routers/finance/hakedis.py` |
| Executor | `approval_executor._handle_finance_hakedis` (ortak service çağırır) |
| Migration | `alembic/versions/f4a8c2d6e9b1_receivable_terms.py` (tablo + modül 920 + Admin izni) |
| Frontend | `frontend/src/routes/dashboard/finans/hakedis/+page.svelte` |
| Test | `backend/tests/test_hakedis.py` + `test_approval_system.py::test_hakedis_term_via_approval_regression` |

## Veritabanı Şeması — `receivable_terms`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `customer_code` | varchar(50) unique | 120.* cari kodu (doğal anahtar) |
| `term_days` | integer (default 30) | Sözleşme vadesi (gün, 0-365) |
| `notes` | varchar(300) | Anlaşma notu |
| `created_at` / `updated_at` | timestamptz | |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/hakedis/` | view | Firma bazlı açık hak ediş + yaşlandırma + özet (tek çağrı; aggregate — pagination yok) |
| GET | `/hakedis/firms/{customer_code}/invoices` | view | Firmanın açık/kısmi faturaları (vade, gecikme, kalan native+TL) |
| GET | `/hakedis/firms/{customer_code}/collections` | view | Firmanın tahsilat dökümü, yeniden eskiye (`group-{id}` destekli) |
| PATCH | `/hakedis/terms/{customer_code}` | use | Vade tanımı upsert — `check_approval` + audit |

## Tahsilat Görünürlüğü + Eşlenmemiş Havuz (2026-07-03)

Kullanıcı sorusu "bu acentadan hiç tahsilat yapılmış mı?" satırdan okunamıyordu (yalnız
Açık/Avans/Net/Geciken vardı; Avans'taki "—" tahsilat yok sanılıyordu). Eklenenler:

- **Firma satırı yeni alanlar** (`compute_receivables`): `collected_tl` / `collected_native`
  (display_currency biriminde tahsilat toplamı), `collection_count`, `last_collection_date/
  amount/currency`, `unapplied_tl` / `unapplied_by_currency`. Grup satırında üye toplamları.
  Özet: `collected_tl`, `unapplied_tl`.
- **UI:** "Tahsilat" kolonu (yeşil toplam + "son: tarih"; hiç yoksa "—"); satır genişletilince
  fatura listesinin altında **Tahsilatlar** tablosu (tarih · native tutar · TL karşılığı ·
  açıklama, yeniden eskiye) — hiç yoksa "henüz hiç tahsilat kaydı yok" metni.
- **Eşlenmemiş (unapplied) havuz — çapraz kur bulgusu:** FIFO (customer, currency) bazında
  eşler; faturaları EUR olan firmaya **TL tahsilat** gelirse hiçbir faturaya mahsup edilmez,
  `_compute`'un `advance_balance` havuzunda askıda kalır ve **açık tutardan düşülmez** (canlı
  örnek: FUN AND SUN 120.01.01.F005 — 12.06.2026 ₺213.959 TL EFT, faturalar EUR; sistem geneli
  ₺307.635). Artık satırda **amber "eşlenmemiş" rozeti** + detayda açıklama notu gösterilir;
  Avans özet kartının ipucunda toplam verilir. Mahsup edilmez — yalnız GÖRÜNÜR kılınır
  (kur çevrimiyle otomatik mahsup ayrı bir iş kararı; nakit yönetimi tarafı bilerek dokunulmadı).
- Test: `test_hakedis.py::TestCollectionsVisibility` (4 test — istatistikler, çapraz-kur
  unapplied, döküm endpoint'i, RBAC).

## Düzenli Satır Yapısı — İş Akışı Sırası (2026-07-03 kullanıcı isteği)

Tablo kolonları muhasebe akışı sırasına dizildi: **Faturalanan → Avans → Tahsilat →
Kalan Hak Ediş → Vadesi Geçen → Ay Sonu Plan** ("önce kesilen faturalar, sonra alınan
avanslar, yapılan tahsilatlar, avans mahsup edilmiş mi, kalan hak ediş ve ay sonları
itibariyle tahsil edilmesi gereken").

- **Faturalanan:** kesilen TÜM faturalar (ödenmişler DAHİL) — `invoiced_tl/invoiced_native`
  + `total_invoice_count`; alt satırda "N fatura · M açık". Eski "Açık Tutar" kolonu kalktı;
  avans-öncesi açık, Kalan kolonunun tooltip'inde.
- **Avans:** ana rakam = KALAN avans (netlemeye giren); alt satır **"alınan ₺A · mahsup ₺B"**
  (`advance_received_tl`/`advance_consumed_tl` — `_advance_by_code` artık tamamı mahsup edilmiş
  avansları da istatistik için toplar; netleme davranışı DEĞİŞMEDİ, yalnız kalan>1 sayılır).
- **Kalan Hak Ediş** = eski "Net Açık" (açık − kalan avans).
- **Vadesi Geçen:** tutar + gecikme rozeti tek hücrede (ayrı Gecikme kolonu kalktı).
- **Ay Sonu Plan** (`monthly_due`): vade ayına göre `[{month, due_tl/native (ay içi vadesi
  dolan), cum_tl/native (ay sonu itibariyle KÜMÜLATİF — gecikmişler ilk aya devreder)}]`.
  Satırda içinde bulunulan ay + sonrası (ilk 3) gösterilir; detay genişletmesinde tam tablo
  ("Ay Sonu Tahsilat Planı"). Grup satırında üye planları ay bazında birleştirilir.
- Test: `TestOrganizedRowFields` (3 — ödenmiş-dahil faturalanan, kümülatif plan, mahsup istatistiği).

## Münferit İstisnası (2026-07-02 kanıtlı karar)
**Münferit (walk-in) faturalar (`is_munferit=True`, 120.03.*) hak ediş takibine GİRMEZ.**
Kanıt: Haziran 2026'daki 259 münferit faturanın 259'unun PMS folio bakiyesi 0 (misafir çıkışta
kart/nakit/havale ile ödemiş — DepartCode 900/980/930…), ama muhasebe 120.03.01.0001'e tahsilat
kaydını işlemiyor (son alacak kaydı 15.05). 120-alacak sinyali münferitte güvenilmez → sahte
"₺5,7M açık" üretiyordu. Takip yalnız anlaşmalı acente alacaklarını kapsar.

## Bayat Tahsilat Riski (2026-07-02 bulgusu)
`sales_collections` import'u insert-only + tutar-hash'li → Sedna'da tahsilat düzeltilir/taşınırsa
eski satır yerelde kalır ve faturaları FIFO'da sahte "ödendi" gösterir (**açık alacak gizlenir**).
Canlı temizlik 2026-07-02: 7 bayat satır / ₺6,57M silindi (ODEON ₺5,8M virman düzeltmeleri, PEGAS
₺616K tarih taşıma + kur farkı). **Kalıcı çözüm (yapılacak):** cari sweep deseni
(`_sweep_stale_vendor_txns`) sales_invoices import'una da uygulanmalı.

## Acente Gruplama (2026-07-02)
Rezervasyon modülündeki **acente grupları** (`agency_groups`) hak edişte birleşik satır olarak
gösterilir (ör. ODEON grubu = ODEON TUR + CORAL SEYAHAT). **Eşleme isimle YAPILMAZ** — PMS adları
↔ muhasebe adları farklı evren ('CORAL PL' ↔ 'CORAL SEYAHAT A.Ş.'). Köprü: `agency_code_map`
tablosu (PMS `Agency.Name → AgencyAccCode.AccCode`, `fetch_agency_acc_codes()` ile sales
import'unda tazelenir). Grup satırı: `is_group=true`, `code="group-{id}"`, `members[]`; üyeler
farklı vadedeyse `term_days=null` ("karma"). Grup fatura detayı: `GET /firms/group-{id}/invoices`.
UI'da grup vadesi düzenlenince TÜM üye kodlarına uygulanır (her biri kendi onay kontrolünden geçer).

## Avans Düşme (2026-07-02)
Firma/grubun **340 'Alınan Avanslar'** kalanı (SalesAdvance, isim-token eşleme — `_merged_advances`
deseni) son TCMB `forex_selling` kuruyla TL'ye çevrilip açıktan düşülür:
`net_open_tl = max(0, open_tl - advance_tl)`. Kartlarda ve tabloda Açık / Avans / **Net Açık**
birlikte gösterilir (ör. ALLTOURS €4,4M avanslı → net 0; FUN&SUN avanssız → net = açık).

## Düzenli Sedna Senkronu (2026-07-02)
Hak ediş verisi `finance.sales_invoices` import'undan beslenir; artık **otomatik**:
`cron_sync_sales_invoices.py` + systemd **`sprenses-sales-sync.timer`** (08–22 arası 2 saatte bir,
Europe/Istanbul; `Persistent=true`). Tünel kapalıysa uyarı loglar, timer düşmez. Topbar'daki
manuel "Sedna" butonu da aynı import'u çalıştırır. Kurulum: `scripts/systemd/sprenses-sales-sync.*`.

## Hesaplama Kuralları
- Fatura vadesi = `invoice_date + term_days` (firma tanımı yoksa 30).
- **Ödendi (FIFO)** faturalar ve kalanı ≤ 0,01 TL olanlar listeye girmez.
- Yaşlandırma kovaları: `not_due` · `overdue_1_7` · `overdue_8_30` · `overdue_30_plus`.
- Firma sıralaması: geciken tutar (TL) azalan, eşitlikte açık tutar azalan.
- Tutarlar kart/toplamada **TL karşılığı**; fatura detayında native (EUR/USD) + TL birlikte.
- `summary.due_7d_tl`: 7 gün içinde vadesi dolacak (henüz gecikmemiş) toplam.

## Onay Akışı
- `PATCH /terms/{code}` `check_approval(db, "finance.hakedis", term_id|0, ...)` — payload'da
  `customer_code` taşınır; executor **doğal-anahtar upsert** yapar (budget deseni, çift kayıt yok).
- Executor router ile AYNI `receivable_service.upsert_term`'i çağırır (D1-2).
- GET'ler salt-okuma → onaydan muaf. Vade tanımı silinmez (30'a çekilir) → delete dalı yok.

## Audit Log
- `entity_type`: `receivable_term` — `action`: create/update (customer_code + term_days detayı).

## Frontend UI
- Kanonik iskelet: PageHeader → StatCard×4 (Açık/Vadesi Geçen/7 Gün İçinde/30+ Gün) → filtre
  (arama debounce 300ms + "yalnız vadesi geçenler") → tablo (satır genişlet → fatura detayı) → Modal.
- Gecikme rozeti: `StatusBadge` success(vadesinde)/warning(≤7g)/error(>7g). Mobil `<sm` kart görünümü.
- Vade düzenleme: Modal + `Field`/`Input type=number` (gün — para değil, MoneyInput gerekmez;
  bilinçli istisnalar listesindeki "vade günü" deseni).
- WS: `finance_updated` event'inde yeniden yükler (Sedna sync sonrası güncel).

## Geliştirme Kuralları
- Veri tazeliği `finance.sales_invoices` import'una bağlıdır (Topbar "Sedna" butonu / merkezi sync).
- v2 adayları (bilinçli ertelendi): vadesi geçenler için günlük bildirim (Notification+push),
  Excel export, firma takip notu geçmişi.
