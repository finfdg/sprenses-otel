# Finans Modülü — Geliştirici Rehberi

Bu dosya finans modülüne katkıda bulunanlar için temel kuralları ve mimari kararları belgeler.
Daha kapsamlı mimari belgeleme için: `docs/modules/finans-mimarisi.md`

---

## Cariler Yeniden Tasarımı — Notlar + Firma Bilgileri + Nakit Akım Faaliyet/Finansman (2026-07-04, YENİ)

"Sprenses Tasarımlar" (GitHub) tasarım klasörünün uygulanması. İki parça:

### 1) Cari detay = 3 sekme (Hesap Hareketleri / Notlar / Firma Bilgileri)

- **Yeni model `VendorNote` (`vendor_notes` tablosu, migration `d8c3f1a2b4e6`):** cari görüşme/takip
  notları — `text`, `author_id`(FK users SET NULL) + `author_name`(yazma anı snapshot), `done`
  (yapıldı), `created_at`/`updated_at`. `vendor_id` FK CASCADE. `Vendor.notes` relationship.
- **Yeni iletişim kolonları `vendors`:** `contact_person`, `phone`, `email` (hepsi nullable; Sedna'da
  yok, elle girilir). Aynı migration.
- **Endpoint'ler (`cariler/notes.py` + `vendors.py`):**
  - `GET/POST /vendors/{id}/notes`, `PATCH/DELETE /vendors/{id}/notes/{note_id}` — not CRUD + `done` toggle.
  - `PATCH /vendors/{id}/contact` — iletişim güncelle.
  - `GET /vendors/{id}` yanıtına eklendi: `contact_person/phone/email` + özet kart metrikleri
    **`overdue`/`overdue_count`** (NET vadesi geçmiş — aşağıya bkz) + **`last_payment_*`**
    (en yeni borç kaydı = son ödeme).
- **ONAY KARARI — notlar + iletişim ONAYDAN MUAF (bilinçli):** finansal etkileri yok
  (finance_events'e YAZILMAZ) → payment_deferral / manuel-banka gibi operasyonel-özel istisna.
  Yine de `require_permission(finance.cariler, use)` + `log_action` (entity_type `vendor_note`/`vendor`)
  + `broadcast_finance_update(CARILER, "update")` uygulanır. **check_approval çağrılMAZ → executor
  handler GEREKMEZ** (`test_all_approval_callers_have_executor_handler` yeni endpoint'leri kapsamaz).
  Vade/durum (payment-days/status) onaya TABİ kalır (finansal); iletişim/not değil.
- **Frontend (`cariler/+page.svelte`) — MASTER-DETAIL (kullanıcı isteği 2026-07-04):** "Cariler"
  alt-görünümü tasarımdaki gibi **sol dar liste + sağ detay** düzenine çevrildi (eski tam-genişlik
  tablo + aç-kapa akordiyon kaldırıldı). SOL: arama + **filtre çipleri (Tümü / Vadesi Geçmiş /
  Bakiyeli)** + vurgu-çubuklu kompakt satırlar (ad + bakiye + kod + durum/eşleşmemiş/vade). SAĞ:
  seçili carinin başlığı (ad + kod + **durum toggle** + **vade düzenle**) + 3 özet kart (Güncel
  Bakiye koyu lacivert / Vadesi Geçmiş / Son Ödeme) + 3 sekme. Mobilde liste↔detay geçişli
  (detayda "Cari listesine dön"). Yükleme/Ödeme Planı/Ödeme Talimatı üst sekmeleri KORUNDU.
  - **"Vadesi Geçmiş" çipi backend filtresi:** `GET /vendors?overdue_only=true` — NET vadesi geçmiş
    tutarı > 0 olan cariler (detay kartıyla aynı FIFO kaynağı → çip ile kart tutarlı).
    `hide_zero` "Bakiyeli", filtresiz "Tümü". Test: `test_vendor_notes.py::test_list_overdue_only_filter`.
- Detay sekmesi/notlar/firma bilgileri: `tests/test_vendor_notes.py` (11).

#### "Vadesi Geçmiş" = NET (FIFO), brüt DEĞİL (2026-07-06, kullanıcı bulgusu)

**Belirti:** Cari detayındaki "Vadesi Geçmiş" kartı, "Güncel Bakiye"den kat kat büyük çıkıyordu
(canlı: net −₺558.909'a karşı vadesi geçmiş ₺1.572.579). Kullanıcı "verilen çek/ödemeler
gecikmeyi kapatmıyor mu?" diye sordu.

**Kök neden:** Kart iki AYRI mantık kullanıyordu — Güncel Bakiye NET (`Σborç − Σalacak`), ama
Vadesi Geçmiş BRÜT: eşleşmemiş (`match_number IS NULL`) + `payment_due_date < bugün` **alacak
satırlarının ham toplamı**. Ödemeleri (borç) hiç düşmüyordu → gerçek net borçtan çok büyük.
Bu, Ödeme Planı için 2024'te zaten düzeltilen "brüt fatura toplamı" sorununun kartta tekrarıydı.

**Çözüm — tek kaynak FIFO:** `vendor_fifo.calculate_overdue_by_vendor(db, today=None, vendor_ids=None)`
eklendi. Ödeme Planı + nakit akımla **AYNI** `calculate_fifo_amounts` çıktısını kullanır (ödemeler
en eski faturalardan düşülür), sonra efektif vadesi bugünden önce olan ödenmemiş fatura paylarını
toplar. Böylece kart = Ödeme Planı'nın geçmiş-vadeli kısmı → gecikmiş tutar net borcu **aşamaz**.
- Detay endpoint'i (`vendors.py`) bu fonksiyonu `vendor_ids=[vendor_id]` ile çağırır.
- Liste `overdue_only` çipi de aynı fonksiyondan net-overdue cari kümesini alıp `Vendor.id.in_(...)`
  ile süzer (eski HAVING brüt SQL yerine) → çip ile kart tutarlı.
- **Davranış değişimi (bilinçli):** yasaklı/borçsuz cariler artık overdue göstermez (FIFO
  kaynağında yer almazlar); eşleşmiş-fatura özel-durumu yok (FIFO net borç üzerinden çalışır,
  ödeme planıyla aynı). Kalıcı öteleme (`payment_deferrals`) efektif vadeye uygulanır.
- Test: `test_vendor_notes.py::test_detail_summary_metrics` (net FIFO) +
  `test_overdue_is_net_capped_by_balance` (brüt 300K'ya karşı net 50K) + `test_list_overdue_only_filter`
  (net-ödenmiş cari çipe girmez).

### 2) Nakit Akım "Faaliyet / Finansman" ayrımı (3a tasarımı) — T Hesap Cetveli

`t-account` yanıtı **additive** genişletildi: her gruba `section` (`"finansman"` = `advance`/`credit`
kaynakları, aksi `"faaliyet"`) + yanıta `faaliyet_net_eur`/`finansman_net_eur`. Bu **SALT yeniden-mercek**:
`Net = Faaliyet Neti + Finansman Neti = total_in − total_out` (toplam DEĞİŞMEZ → mutabakat riski yok).
Kredi taksiti anapara+faiz AYRIŞTIRILAMADIĞINDAN taksitin tamamı finansmanda. `CashFlowTAccount.svelte`
finansman gruplarına rozet + (finansman hareketi varsa) Faaliyet Neti / Finansman bantları gösterir;
runway zaten gömülü `NakitKoruma` ile sağlanıyor. Test: `test_cash_flow_taccount.py::TestTAccountFaaliyetFinansman`.

**T Hesap iyileştirmeleri (2026-07-05, kullanıcı isteği — 4 madde):** (1) **Detay kalemleri kendi
para biriminde** — `t-account` item'ına `amount_native` + `currency` eklendi; frontend detay satırı
`fmtNative` ile ₺/€ gösterir (grup/kolon toplamı EUR konsolide KALIR — karışık-para karşılaştırması için).
(2) **Gerçekleşen vs bekleyen** — yanıta `realized_in_eur`/`realized_out_eur` (is_realized=banka vb.);
kolon başlığında "✓ Gerçekleşen €X · Bekleyen €Y" (toplam DEĞİŞMEZ, salt bilgilendirme; kullanıcının
"gerçekleşti, kalan bu kadar" isteği).
**Bekleyen/Gerçekleşen SEGMENTİ + Tarih görünümü (2026-07-06, tasarım "Nakit Akım T-Hesap.dc.html"):**
Her sütunda İKİ bağımsız sütun-içi kontrol (backend additive — grup `realized_eur`/`realized_count`
sayaçları + item `is_realized`; kolon toplamları/Net DEĞİŞMEZ):
- **Segment (Bekleyen | ✓ Gerçekleşen):** iki-satırlı segment (etiket + EUR tutar); **aynı liste
  YERİNDE değişir** (ayrı panel açılmaz). Varsayılan **Bekleyen**; dönem/gezinme değişince sıfırlanır.
  Bölme SAYAÇLARDAN yapılır (`catGroups`) — items `MAX_ITEMS_PER_GROUP`=100 ile kırpık olabildiğinden
  itemlardan sayma yanlış olur. Ödenen kredi taksiti gibi realized kalemler varsayılan (bekleyen) listeyi şişirmez.
- **Tarih görünümü:** sütun başlığı (takvim ikonlu) toggle — kategori-gruplama ↔ **gün-gruplama** arası.
  Açıkken `dateBuckets(groups, realized)` segment'e göre TÜM kalemleri düzleştirir, güne göre gruplar
  (her satır: kategori etiketi + kalem adı + native tutar), 40 gün cap + "+N gün daha".
- Renk: gelir **emerald** (yeşil), gider **brass** (altın); net bandı `teal-700` (lacivert) + Faaliyet/
  Finansman neti çipleri. open-state anahtarı `side:realized:label` (segmentler arası çakışmaz).
Test: `TestTAccountRealizedSplit` (sayaçlar + item bayrakları + Σgrup==kolon) + `TestTAccountItemOrdering`
(items tarih sıralı — tarih görünümü keyed-each mükerrer anahtar donmasına karşı). (3) Giriş/Çıkış başlık puntosu büyütüldü. (4) **Gelecek dönem
navigasyonu** — offset `le=0`→`le=24` (frontend `MAX_FUTURE_OFFSET=24`); sağ ok artık ileri ay/hafta/
gün/yıl açar (planlı çek/kredi/scheduled/cc-projeksiyon gelecekte görünür). Test: `test_offset_bounds`
(−120..+24). Toplam 16 yeşil.

---

## Kalıcı Öteleme + Overdue (Cuma roll-over KALDIRILDI) (2026-07-04, YENİ)

Kullanıcı kararı: (1) Nakit Koruma'da bir kalemin "ötelemesi" artık **KALICI**; (2) vadesi geçen
cari ödemelerinin **"sonraki Cuma'ya kaydırılması" GLOBAL KALDIRILDI** (fatura orijinal/geçmiş
tarihinde kalır — gerçek durum). Doğrudan uygulanır (**onaysız** — bilinçli; finance.cash_flow
**use** + audit + WS broadcast).

**Model + tablo:** `payment_deferrals` (migration `a6fb877d2af1`) — TEK tablo, tüm ödeme türleri.
Doğal anahtar `(source_type, source_id)` (`uq_payment_deferrals_source`). `deferred_to Date NOT NULL`,
`created_by` FK users SET NULL, `note` Text. Model `app/models/payment_deferral.py`.

**Service `app/services/deferral_service.py`:**
- `get_deferral_map(db)` → `{(source_type, source_id): deferred_to}` — **modül-içi dict cache**'li
  (`_deferral_cache`; `finance_event_service` FIFO cache deseni). `_upsert` her FE'de çağırır →
  cache olmadan bulk Sedna sync yavaşlar. `apply`/`clear` `invalidate_deferral_cache()` çağırır.
  Test izolasyonu: conftest her test başında invalidate eder (DB SAVEPOINT rollback ile sızmasın).
- `apply_deferral` (upsert), `clear_deferral` (sil) — commit ETMEZ (çağıran eder).
- `resync_deferred_event(db, st, sid)` — kaynağı bulup uygun `upsert_*`'ı çağırır → FE `event_date`
  hemen yansır. vendor_payment→`sync_vendor_finance_events`, check→`upsert_check`, credit→
  `upsert_credit_payment`, cc_payment→`upsert_cc_statement`, scheduled türleri→`upsert_scheduled_entry`
  (direction eşlemesi `_SCHEDULED_DIRECTION`; rent_income=+1, gerisi=-1).
- `DEFERRABLE_SOURCE_TYPES` — **bank HARİÇ** (gerçekleşmiş nakit; en kalabalık FE türü → lookup dışı).

**MERKEZÎ override — `finance_event_service._upsert`:** başta `if source_type != SOURCE_BANK and
"event_date" in fields:` → deferral_map'ten bakar, varsa `fields["event_date"] = deferred_to` (lazy
import → circular kır). Böylece **TÜM türler tek yerden** ertelenmiş tarihi alır; Sedna sync / FIFO
yeniden yazımı ötelemeyi korur (kalıcılık buradan gelir). **İSTİSNA:** `sync_vendor_finance_events`
FE'yi ORM ile DOĞRUDAN yazar (`_upsert` üzerinden DEĞİL) → orada override çalışmaz; öteleme
`effective_due_date(..., deferral_map)` ile o modülde de ayrıca uygulanır.
- Not: `_upsert` `ON CONFLICT DO UPDATE` SQL düzeyinde yazar → identity-map'teki python nesnesi
  bayat kalabilir (öteleme sonrası eski `event_date`). Dönüşte `db.expire(event)` eklendi (lazy;
  okunmayan hot-path'te ekstra sorgu yok) → dönüş değeri artık taze.

**Cuma roll-over kaldırma — NELERİ değiştirdim/koruduğum (KRİTİK ayrım):**
- `vendor_fifo.effective_due_date(payment_due_date, vtx_id=None, deferral_map=None)`: eski
  `if payment_due_date < today: return coming_friday(today)` **SİLİNDİ** → vadesi geçen fatura
  ORİJİNAL tarihinde kalır. Yalnız KALICI ÖTELEME uygulanır (deferral_map'te varsa deferred_to döner).
- **`_next_friday(raw_due)` KORUNDU** (vendor_fifo:116,282 + payment_schedule.py:113) — bu AYRI bir
  kural: `payment_due_date` BOŞ olduğunda fatura tarihinden vade hesaplarken (`fatura + payment_days`)
  ham vade gününü Cuma'ya HİZALAR ("ödeme günü Cuma"). Vadesi geçeni ileri AKTARMAKLA (kaldırıldı)
  karıştırılmamalı. `coming_friday` artık çağrılmıyor (tanım korundu; re-import kırmasın).
- Çağıranlar güncellendi: `sync_vendor_fifo.py` (new+update yolları deferral_map ile), `vendor_fifo.
  get_payment_schedule`, `cariler/payment_schedule.py` router (ScheduleInvoice/InvoiceRow'a `vtx_id`
  eklendi). **Çek/kredi `_next_friday`/vade kuralına DOKUNULMADI** — yalnız vendor overdue-roll kalktı.

**Endpoint `cash_flow/deferral.py` — `POST /cash-flow/defer`:** body `{source_type, source_id,
deferred_to: str|null, note?}`. deferred_to null→`clear_deferral`, değilse→`apply_deferral`; sonra
`resync_deferred_event` → `db.commit` → audit (entity_type=`payment_deferral`) → `broadcast_finance_
update(CASH_FLOW, "update")`. Validasyon: source_type deferrable kümede (yoksa 400), tarih YYYY-MM-DD
(bozuk→400). Yanıt `{ok, deferred_to, cleared}`.

**Runway (`cash_flow/runway.py`) güncellendi:** pencere `[today, month_end]` yerine `[MIN_DATE,
month_end]` çekilir, sonra Python'da bölünür: `event_date < today` → **`overdue`** dizisi (vadesi
geçen ödenmemiş — Cuma roll kalktığı için artık geçmişte durur), aksi halde `inflows`/`outs`. Her
out/overdue/inflow kalemine `deferred: bool` (payment_deferrals'ta var mı) + `original_date` (ötelenmişse
kaynağın öteleme-öncesi doğal vadesi `_natural_date` ile; değilse event_date). inflow'da `source_type`
gösterilmez (geriye uyum).

**Test:** `tests/test_payment_deferral.py` (21 test — service apply/clear/cache, `_upsert` override
[credit/bank-hariç], `effective_due_date` overdue-orijinal + deferral, endpoint 401/403/viewer-403/400/
200 + FE event_date değişimi + clear-geri-döner + audit, runway overdue + deferred/original_date).

---

## Nakit Akım PDF Raporu (2026-07-03, YENİ)

Nakit Akım sayfasındaki **"PDF Rapor"** butonu (PageHeader actions) ekrandaki ayların
nakit akışını PDF indirir: `GET /cash-flow/report/pdf?start_date&end_date`
(`cash_flow/report.py`, `finance.cash_flow` view, `heavy_limiter`, onaydan muaf GET).

- **Tek sayı kaynağı:** EUR gün/ay hesabı `eur_balances.py`'den
  **`compute_eur_balances(db)`** fonksiyonuna çıkarıldı; `eur-balances` endpoint'i ve
  PDF raporu AYNI fonksiyonu çağırır → ekran ile rapor birebir tutar. (Paket-içi
  import — paketler-arası router→router yasağına girmez.)
- **İçerik:** ay başına günlük Gider/Gelir/Bakiye (€) tablosu + ay toplamı + genel
  toplam; gün etiketi ekranla aynı ("1 Temmuz Çar", locale bağımsız sabit listeler);
  gider kırmızı / gelir yeşil / negatif bakiye kırmızı; font `register_turkish_fonts()`.
- **Ay toplamı semantiği:** rapora dahil edilen günlerden hesaplanır; ay bakiyesi =
  aralıktaki son günün `balance_eur`'u (UI ay başlığı tam-ay gösterir — tam-ay
  aralığında ikisi özdeş).
- **Frontend:** `api.fetchRaw` → blob → **`PdfPreviewModal.svelte`** (paylaşılan
  önizleme modalı). **Kapsam = akordiyonda AÇIK olan ay** (kullanıcı isteği 2026-07-03:
  "Temmuz seçiliyse Temmuz raporu"): `MonthAccordion.getExpandedMonthKeys()` +
  `monthKeysToDateRange()` (utils/finance.ts, testli) → start/end; birden çok açık ay =
  kapsayan aralık; hiç açık ay yoksa fallback uygulanmış filtre (`cashFlowCache.filters`).
  **NOT (2026-07-03):** ilk sürümdeki `<a download>` + `click()` deseni iPad Safari'de
  "WebKitBlobResource hatası 1" verdi → talimatlar sayfasının modal-iframe çözümü
  `lib/components/PdfPreviewModal.svelte` ortak bileşenine çıkarıldı; nakit-akım +
  krediler + talimatlar üçü de bunu kullanır. **Yeni PDF indirme akışı yazarken blob'u
  `<a download>`/yeni-sekme ile AÇMA — PdfPreviewModal.open(blob, dosyaAdi) kullan.**
- **Test:** `tests/test_cash_flow_report.py` (8 test) +
  `src/lib/components/PdfPreviewModal.test.ts` (6 test). Detay: `docs/modules/nakit-akim.md`.

---

## Refactor — Çek Sedna İçe-Aktarma Ayrıştırması + Pagination Helper (2026-06-27)

- **`check_import.py` (yeni) — Sedna çek içe-aktarma domain katmanı:** `checks.py` 814→432 satıra
  indi. Tüm Sedna içe-aktarma mantığı (`run_check_import`, `_import_one_check_row`,
  `_build_existing_and_stale`, `infer_check_banks`, `detect_check_no_mismatches`,
  `_sweep_stale_checks`, dedup/status anahtar helper'ları `_check_dedup_key`/`_check_status_from_pos`/
  `_check_group_key`/`_checkno_to_int`/`_norm_bank`) yeni `app/routers/finance/check_import.py`'ye
  taşındı. Bu modül **router'dan import ETMEZ** (tek yön → cycle yok); `checks.py` ihtiyaç duyduğu
  isimleri (`_check_dedup_key` [Excel upload dedup'u], `run_check_import`, `detect_check_no_mismatches`)
  geri import eder. `sedna_sync.py` artık `run_check_import`'u doğrudan `check_import`'tan alır (router
  yerine domain modülü). **`run_check_import` mantığı değişmedi** — yalnız taşındı + iç döngü
  `_import_one_check_row` helper'ına bölündü (207→~80 satır; davranış birebir).
  - **Test patch hedefi değişti:** `sedna_configured`/`fetch_issued_checks` patch'leri artık
    `app.routers.finance.check_import`'u hedefler (run_check_import orada bu adları kendi global'inde
    arar). `TARGET`/`CHK` sabitleri + 3 doğrudan import (`infer_check_banks`/`detect_check_no_mismatches`/
    `_sweep_stale_checks`) `check_import`'a repoint edildi. Test: `test_checks.py`, `test_sedna_sync.py`.
- **`bank_statement_import.py` (yeni) — banka ekstresi yükleme/işleme domain katmanı:** `banks.py`
  833→467 satıra indi. Ekstre dosyası doğrula+ayrıştır (`_save_and_parse`), dedup ile hesaba kaydet
  (`_process_statement`), yükleme sonrası bildirim+otomatik eşleştirme (`_post_upload_processing`) +
  yardımcıları (`_notify_bank_upload`/`_get_banks_viewer_ids`/`_ensure_upload_dir`/`UPLOAD_DIR`) bu modüle
  taşındı. `banks.py` upload endpoint'leri 3 fonksiyonu buradan import eder; modül router'dan import etmez.
  Davranış birebir (test: `test_finance`/`test_bank_manual_transaction`/`test_banks_cc_match`).
- **`utils/bank_parse_helpers.py` (yeni) — saf sayı/tarih ayrıştırma:** `bank_parser.py` 1044→857 satıra
  indi. **NOT:** bank_parser banka-başına DEĞİL konu-başına organize (tek banka-özel fn `_parse_vakifbank_text`)
  → "per-bank parser" split uygulanamaz. Saf fonksiyonlar (`parse_turkish_number`/`parse_english_number`/
  `_detect_number_format`/`_smart_parse_number`/`parse_date_tr`/`_normalize_tr`/`_strip_currency_suffix`/
  `_extract_trailing_numbers`) ayrıldı; `bank_parser` geri import eder. Davranış birebir (`_normalize_tr`
  unicode eşdeğerliği test edildi; `test_bank_parser.py` 63 yeşil).
- **`utils/pagination.py` (yeni) — `page_meta(items, total, page, page_size)` + `paginate(query, ...)`:**
  baskın pagination konvansiyonu (boş→`pages=1`). 14 endpoint'in tekrar eden `{items,total,page,page_size,
  pages: math.ceil(...)}` dict literal'i bununla değiştirildi (audit/advances/error_logs/notifications/
  krediler/cariler/cash_flow/checks/butce/exchange_rates/scheduled/quality/sales/system_users). **`approval/*`
  HARİÇ** — orada boşta `pages=0` konvansiyonu farklı (sapma yaratmamak için dokunulmadı). Banks/sales_invoices/
  attendance/stock farklı formatlı (`if total else 1` / `total_count` / tek-satır) → adapte edilebilir, dokunulmadı.

---

## Verilen Çek — Ödeme Bankası (`checks.bank_name`) (2026-06-20)

Verilen çekin **hangi bankadan ödeneceği** (çek defterinin bankası) artık ayrı kolonda tutulur.
- **Kaynak:** Sedna `AccCheck.Bank` (`fetch_issued_checks()` → `bank` anahtarı). Verilen çekte = bizim ödeme bankamız.
- **Kolon:** `checks.bank_name VARCHAR(100)` (migration `c1f5a8e3b9d2`, additive+nullable). **Eskiden `description`'a yazılıyordu** ama description Excel notlarıyla karışıyordu (güvenilmez) → ayrı kolon.
- **Import:** `run_check_import` banka adını `bank_name`'e yazar (new + drift + status-sync yolları). **Backfill:** status/vade değişmese bile `bank_name` eksik/farklıysa güncellenir → re-sync mevcut çeklerde geriye doldurur (71/77 bekleyen çek dolduruldu; Sedna'da `Bank` boş olanlar + Excel-only çekler boş kalır).
- **finance_events:** `upsert_check` FE'nin `bank_name`'ini doldurur (eşleşmişse banka hareketinin bankası, değilse çekin `bank_name`'i) → Nakit Akım çek kartında **banka rozeti** (Landmark ikonlu) gösterilir.
- **Frontend:** `CashFlowItem.svelte` çek dalında banka rozeti; `cekler/+page.svelte` tabloya "Banka" sütunu + mobil kartta rozet. Test: `test_checks.py::test_import_status_mapping_dedup_and_sync` (bank_name doğrulaması).

### Banka Tahmini — komşu çek-no interpolasyonu (`bank_name_inferred`) (2026-06-20)

Sedna'da bankası boş çekler için, **ardışık çek numarası = aynı çek defteri = aynı banka** kuralından
banka TAHMİN edilir. `infer_check_banks(db)` (checks.py): bir çekin sayısal **alt + üst ONAYLI komşusu**
(inferred=False) aynı bankada ve aralarındaki fark ≤ `_INFER_MAX_GAP` (50) ise o banka atanır
(`bank_name_inferred=True`). **Yalnız interpolasyon** (izole/uçtaki çek atlanır), **çapa = yalnız onaylı banka**
(tahmin-üstüne-tahmin yok), sayısal-olmayan çek-no (`_checkno_to_int` → None) atlanır. Idempotent; çapa
kalkarsa eski tahmin temizlenir.
- **Tetikleme:** `run_check_import` sonunda otomatik (her Sedna sync banka tahminini günceller). Sedna gerçek
  banka verince `bank_name_inferred=False` (tahmin → kesin override).
- **Ayrı tutulur:** `bank_name_inferred` bayrağı (checks + finance_events) → UI'da **soluk/italik "~banka" rozeti**
  (CashFlowItem + cekler), gerçek banka teal rozet. Sedna'da banka girilince otomatik kesinleşir.
- **İlk sonuç (2026-06-20):** 15 çek tahmin edildi → bekleyen-bankasız çek 6→2'ye düştü. Migration `d2a6c4f8e1b5`. Test: `test_checks.py::TestCheckBankInference`.

### Çek No ↔ Açıklama-No Uyuşmazlığı Tespiti (`detect_check_no_mismatches`) (2026-06-20)

Excel/cari açıklamasında gerçek çek no gömülü olur (ör. "GALAKSİ 0012419 NL 25.06.2026 VADELİ ÇEK").
`check_no` bu numaradan farklıysa **transkripsiyon hatası** olabilir (canlı bulgu: `0012119` kayıtlı ama
açıklama `0012419` → '4' yerine '1'; izole görünüp banka tahmini alamıyordu). `detect_check_no_mismatches(db)`
açıklamadaki 6-7 haneli numarayı `check_no` ile kıyaslar (Türkçe-duyarsız int normalize). **Yalnız TESPİT —
asla otomatik düzeltmez** (off-by-1 farklar açıklamanın komşu çeke referansı da olabilir; düzeltme insan kararı).
- **Tetikleme:** `run_check_import` sonunda çalışır → uyuşmazlıkları `logger.warning` + sonuç `number_anomalies` sayısı.
- **Endpoint:** `GET /finance/checks/number-anomalies` (finance.checks view) → `{items, count}` liste (UI/inceleme için).
- **Düzeltilen no'lar (2026-06-20, elle doğrulamayla):** `0012119→0012419`, `02012411→0012411`, `782820→7823820`
  (üçü de bozuk check_no + boş hedef slot + deftere oturuyor). Kalan 3 anomali ödenmiş+belirsiz (off-by-1) → dokunulmadı.
- Test: `test_checks.py::TestCheckBankInference::test_number_anomaly_detection`.

### Bayat Çek Süpürme — Sedna = Tek Doğru Kaynak (`_sweep_stale_checks`) (2026-06-20)

**Kök sorun:** Çek içe aktarması eskiden yalnız INSERT/UPDATE yapıyordu — Sedna'da artık olmayan
(veya farklı/typo'lu numarayla duran) eski Excel kayıtlarını **SİLMİYORDU** → bayat mükerrerler birikiyordu
(ör. AYKIN'ın "ANTALYA" çeki Sedna'da yok ama lokalde duruyor, borcu 200K şişiriyordu). Kullanıcı uyarısıyla
keşfedildi: **canlı Sedna sorgulanınca** AYKIN'da TEK çek (9498646) olduğu, "ANTALYA"nın bayat lokal artefakt
olduğu görüldü. **DERS: typo/mükerrer şüphesinde önce Sedna CANLI sorgulanmalı** (lokal kopya bayat olabilir).

`_sweep_stale_checks(db, sedna_rows)`: `run_check_import` sonunda çalışır. Bir lokal çek **silinir** ancak:
(a) **eşleşmemiş** (banka/cari bağı yok — `bank_transaction_id` ve `match_number` NULL), (b) verilen-çek kapsamı
(`320/159/335`), (c) Sedna'da **birebir** (no dahil, `_check_dedup_key`) karşılığı YOK, **ama** (d) Sedna'da
**no'suz kimliği** (`_check_group_key` = cari+para+tutar+vade) VAR → yani aynı çek Sedna'da farklı no ile duruyor =
bayat typo-dup. **Sedna'da hiç eşi olmayan (legit) çeke ve EŞLEŞMİŞ çeke DOKUNMAZ.** finance_event invalidate'lenir.
- **Eşleşmiş bayat çek** süpürülemez (güvenlik) → elle: eşleştirmeyi Sedna'nın doğru çekine **taşı**, sonra stale'i sil
  (GALAKSİ 0012419→0012119'da yapıldı: match 96 doğru çeke taşındı, kayıt korundu).
- **İlk temizlik (2026-06-20):** 3 bayat çek süpürüldü (7823820/D054, 0012411/B086, ANTALYA/A225) + GALAKSİ elle +
  AYKIN bayat cari hareketi (id 10265) silindi → AYKIN net 200K→**0** (gerçek durumu). Sonuç `swept_stale` ile döner.
- **Cari tarafı:** stale cari hareketleri için `cariler` modülünde `removal_candidates` mekanizması var (manuel onay).
- Test: `test_checks.py::TestCheckBankInference::test_sweep_stale_checks_removes_only_sedna_absent_dupes`.

## Krediler — Ortak Service Katmanı + Onay Sapması Düzeltmesi (2026-06-22, D1-2)

Kredi ürün/ödeme mutasyon mantığı tek kaynakta: **`app/services/credit_service.py`**. Hem router
endpoint'leri (`products.py` create/update/delete, `payments.py` update/delete) hem onay executor
handler'ı (`approval_executor._handle_finance_krediler`) AYNI service fonksiyonlarını çağırır
(`create_product`/`apply_product_update`/`delete_product`/`apply_payment_update`/`delete_payment`).
BCH/KMH plan üreticileri (`_regenerate_bch_payments`/`_regenerate_kmh_payments`) `_helpers.py`'den
buraya taşındı (router→router/service import yönü korunur); `_helpers.py` yalnız sunum yardımcıları
(`_build_product_response`/`_batch_payment_stats`) tutar.

**Kapatılan sapmalar (2026-06-21 denetim D2-4 — executor router'dan elle sapıyordu):**
- `payment.product_id` / `CreditPayment.product_id` → model kolonu **`credit_product_id`**; onaylı
  ödeme-güncelleme + ürün-silme `AttributeError`/500 veriyordu. Artık doğru kolon (service).
- Onaylı create/update'te **BCH/KMH ödeme planı + finance_events üretilmiyordu** (router üretiyor,
  executor atlıyordu) → onaylı BCH kredisi sessizce plansız/nakit-akımsız oluşuyordu. Artık üretilir.
- **Tarih coercion:** onay payload'ı `json.dumps(..., default=str)` ile saklanır → tarihler string
  olur; `credit_service._coerce_date` regeneratör tarih aritmetiği öncesi `date`'e çevirir.

**Regresyon testleri:** `test_approval_system.py::TestApprovalExecutorMoreModules` →
`test_credit_bch_create_via_approval_generates_plan`, `test_credit_payment_update_via_approval`,
`test_credit_product_delete_via_approval`. Davranış router ile birebir.

**Close/Reopen sapması + broadcast (2026-07-01 denetim, KRİTİK):** close/reopen endpoint'leri onay
payload'ını `{"action": "close"|"reopen"}` olarak gönderir; ama executor `update` dalı bunu OKUMUYORDU →
`apply_product_update` `action`'ı anlamsız bir attribute'a `setattr` edip `status`'ü DEĞİŞTİRMİYOR,
ödenmemiş taksit FE'lerini invalidate/re-upsert ETMİYORDU → **onaylı kapatma/açma sessizce çalışmıyordu.**
Düzeltme (D1-2 deseni): mantık `credit_service.close_product`/`reopen_product`'a çıkarıldı; router endpoint'i
+ executor `action` dalı AYNI fonksiyonu çağırır. Regresyon: `test_credit_close_reopen_via_approval_actually_toggles`.
Ayrıca **ürün + ödeme CRUD** (create/update/delete) artık `broadcast_finance_update(..., BroadcastModule.CREDITS, ...)`
çağırır (eskiden yalnız close/reopen ediyordu → açık sekmeler kredi CRUD'unda gerçek-zamanlı güncellenmiyordu).

**Cariler dilimi (aynı desen):** `app/services/vendor_service.py::apply_vendor_update` — cari
vade/durum güncelleme tek kaynak. Router (`cariler/vendors.py` payment-days + status endpoint'leri) ve
`_handle_finance_cariler` ORTAK çağırır: alanları uygula → vade değiştiyse işlem ödeme tarihlerini
yeniden hesapla (+ FE upsert) → `sync_vendor_finance_events`. Geçersiz durum/negatif vade → ValueError.
Eski executor handler router mantığını elle tekrarlıyordu (doğrulama yoktu; router değişse sessiz sapardı).
Regresyon: `test_vendor_payment_days_via_approval`, `test_vendor_status_via_approval_syncs_finance_events`.

**Diğer finans dilimleri (aynı desen, 2026-06-22):** `advance_service` (avanslar CRUD+FE),
`bank_account_service` (banka hesabı CRUD), `department_service` (departman CRUD — **drift kapatıldı:**
executor delete'i guard'sız SOFT idi → router'la birebir guard'lı HARD oldu). Router endpoint'leri +
ilgili executor handler'ları ORTAK service çağırır.

**butce dilimi (2026-06-22, `budget_service`):** **GERÇEK BUG kapatıldı** — executor budget create'i
**id-bazlı INSERT** yapıyordu (create'te entity_id=0 → her zaman INSERT), router ise `_upsert_budget`
ile **kompozit-anahtar upsert** (department_id+category_id+year+month → varsa GÜNCELLE). Sonuç: onaylı
budget create aynı dönem için **ÇİFT bütçe satırı / `uq_budget_dept_cat_year_month` ihlali**. `_upsert_budget`
mantığı `budget_service.upsert_budget`'e taşındı; router upsert endpoint'i + executor AYNI çağırır.
Kategori CRUD + budget delete de service'te. Regresyon: `test_budget_create_via_approval_upserts_not_duplicate`.

**D1-2 TAMAMLANDI (16/16 handler):** finans (krediler/cariler/checks/avanslar/banks/departmanlar/butce),
scheduled (8 modül), system×3, sales.room_types, quality (templates/forms), hr×3 (attendance/shifts/
shift_schedule) — hepsi router+executor ORTAK service. `app/services/` 15 modül. Detay: denetim raporu.

**Çekler dilimi (aynı desen):** `app/services/check_service.py::apply_check_status` — çek durum
güncelleme tek kaynak. Router (`checks.py::update_check_status`) ve `_handle_finance_checks` ORTAK
çağırır: iptal ise **eşleşme kademesi** (cari `match_number`+`payment_method` temizle, banka
`bank_transaction_id` çöz) → `check.status` → `finance_event_svc.upsert_check`. Bu çoklu-varlık kademe
iki yerde elle tekrarlanıyordu (router değişse executor sessizce yetim eşleşme bırakırdı). Mevcut
`test_check_status_via_approval_regression` yalnız temel pending→paid'i kapsıyordu; yeni
`test_check_cancel_via_approval_unmatches_vendor` iptal kademesini doğrular. (Toplam 1158 test yeşil.)

## Hak Ediş Takibi — finance.hakedis (2026-07-02, YENİ MODÜL)

Çıkışta kesilen acente faturası = hak ediş; firma anlaşma vadesi (30/45 gün) içinde ödemeli.
**Sedna'da vade YOK** (29 DB incelendi: PMS `Invoice.DueDate`=`InvoiceDate`, `Agency.Days`=0) →
vadeler yerel `receivable_terms`'te (varsayılan 30 gün, `DEFAULT_TERM_DAYS`). Veri kaynağı:
mevcut `sales_invoices` FIFO'su (`_compute_cached`) — **PMS'ten ayrı import YOK**, üstüne yalnız
vade+yaşlandırma katmanı (`receivable_service.compute_receivables`). `upsert_term` router
(`hakedis.py`) + executor (`_handle_finance_hakedis`) ORTAK (D1-2; doğal anahtar customer_code,
budget deseni). Modül id 920 (905 stok'a ait — ÇAKIŞMA yakalandı, migration `f4a8c2d6e9b1`).
Test: `test_hakedis.py` (7) + onay regresyonu. Detay: `docs/modules/hakedis.md`.

**Tahsilat görünürlüğü (2026-07-03):** firma satırına `collected_tl/native` + `collection_count` +
`last_collection_*` + **`unapplied_tl`** (FIFO `advance_balance` havuzunda askıda kalan çapraz-kur
tahsilat — EUR faturalı firmaya TL EFT gelirse mahsup edilmez, açık tutardan düşülmez; canlı örnek
FUN AND SUN ₺213.959) alanları eklendi; yeni `GET /hakedis/firms/{code}/collections` döküm
endpoint'i; UI'da "Tahsilat" kolonu + amber "eşlenmemiş" rozeti + detayda tahsilat tablosu.
Test: `TestCollectionsVisibility` (4). Detay: `docs/modules/hakedis.md` "Tahsilat Görünürlüğü".

**Düzenli satır yapısı (2026-07-03, aynı gün):** kolonlar iş akışı sırasına dizildi —
Faturalanan (ödenmişler DAHİL toplam; `invoiced_tl/native` + `total_invoice_count`) → Avans
(kalan + "alınan/mahsup" alt satırı; `advance_received_tl/consumed_tl` — netleme DEĞİŞMEDİ) →
Tahsilat → Kalan Hak Ediş (eski Net Açık) → Vadesi Geçen (+gecikme rozeti tek hücre) →
**Ay Sonu Plan** (`monthly_due`: ay içi vadesi dolan + kümülatif; gecikmiş geçmiş aylar
kümülatife devreder; satırda ilk 3 ay, detayda tam tablo). Test: `TestOrganizedRowFields` (3).

## Virman/Döviz Satım Pair — Kur-Duyarlı Eşleme (2026-07-03 düzeltmesi)

`tag_transaction`'daki karşı-bacak araması kur gözetmiyordu (aynı tarih + ±%2 HAM tutar):
€36.428,78 döviz satışına TL bacağı (₺1,94M) yerine aynı gün aynı EUR hesaba gelen
€36.781,33 acente havalesi eşlendi (canlı hata #481, elle #482'ye düzeltildi).
Yeni `_find_pair_counterpart`: **Virman** = yalnız AYNI birimli hesaplar (birebir → ±%2,
en yakın aday); **Döviz Satım** = yalnız FARKLI birimli hesaplar + iki bacağın TL değeri
(TCMB forex_selling, o gün) ±%5 (`FX_PAIR_TOLERANCE`) — kur yoksa eşleme YAPILMAZ.
Test: `test_transaction_tags.py` (3 yeni). Detay: `docs/modules/transaction-tags.md`.

---

## CC Ekstresi Otomatik Eşleştirme — Maskeli PAN + Tam Ödeme + Pencere (2026-07-04, YENİ)

**Belirti:** Yapı Kredi World Kart (\*7261) ekstresi (stmt 16, ₺493.421,94, son ödeme 30.06)
banka ödemesi yapılmasına rağmen nakit akımda "Bekliyor" kalıyordu. Kök neden `_match_cc_to_bank`
(`utils/matching_service.py`) üç noktada bu ödemeyi atlıyordu:
1. **Kelime kapısı:** `_is_cc_payment_desc` açıklamada "kart öd/kredi kartı/kk borç…" arıyordu;
   ödemenin açıklaması **"Diğer Internet - Mobil INT 650837\*\*\*\*\*\*7261 3006"** — maskeli PAN var
   ama kart ifadesi yok → hareket kart kelimesi bulunmadığından hiç değerlendirilmiyordu.
2. **Son-4 çıkarımı:** `_extract_last4_from_desc` kalıpları son-4'ü açıklamanın SONUNDA (`$`)
   ve tam 4/8 yıldızla arıyordu; maskeli PAN (6 yıldız + sonda referans " 3006") hiçbirine uymuyor →
   `None`. (Aynı sebeple QNB stmt 8'in "\*\*\*\*\*\*6075" ödemesi de çıkarılamıyordu.)
3. **Fazla ödeme:** banka ödemesi (₺493.469) ekstre toplamını ~47 TL **aşıyordu** (faiz/masraf);
   matcher yalnız tam-eşit veya kısmi (ödeme ≤ borç) kabul ediyordu.

**Çözüm (kelime kapısı KALDIRILDI, iki-yol + pencere):**
- **Son-4 çıkarımı** genişletildi: `r'\*{2,}\s*(\d{4})(?!\d)'` maskeli PAN'ı (2+ yıldız + son 4)
  açıklamanın herhangi bir yerinde yakalar. Yıldız (maske) şartı → düz sayılarda yanlış-pozitif yok.
- **İki yol** (`_match_cc_to_bank` iç döngü):
  - **Kelime VAR** (`_is_cc_payment_desc` True): mevcut mantık DEĞİŞMEDİ (tam kalan/toplam veya kısmi,
    tarih-yakınlığı tiebreak). Güvenilir sinyal → geriye uyum korunur.
  - **Kelime YOK ama bilinen kart son-4'ü:** YÜKSEK GÜVEN şartı — yalnız **TAM ödeme**
    (`toplam-1 ≤ ödeme ≤ toplam×(1+%2)`, `CC_OVERPAY_TOLERANCE`) **+ ödeme tarihi pencerede**
    (`_cc_payment_in_window`: `kesim ≤ ödeme ≤ son_ödeme + CC_PAY_GRACE_DAYS(25)`).
- **Neden pencere şart:** Kart 7261 gibi oto-ödeme kartlarında aylara yayılmış bol kısmi/gecikmeli
  banka borcu var; kelime kapısı kalkınca gevşek matcher bunları **açık ekstrelere yığıyordu**
  (canlı kuru-çalışma: 13 eşleşme — stmt 16'ya 178K+493K, stmt 3'e 8 kısmi, farklı-ayların ödemeleri).
  Pencere + tam-ödeme şartı 13→**2 doğru eşleşmeye** indirdi (5722→16, 3390→8); kesimden önceki
  (farklı-ay) ve kısmi ödemeler elendi.
- **Eşleşme sonrası** artık `finance_event_svc.upsert_cc_statement(db, stmt, prod)` çağrılır (elle
  `cc_fe.is_matched=True` yerine — çek düzeltmesiyle aynı desen): tam ödemede FE gizlenir
  (`is_matched` + `event_status='paid'`), kısmi ödemede kalan borç tazelenir (eskiden `event_status`
  bayat kalıyordu).
- **Canlı düzeltme:** matcher yeniden çalıştırıldı → stmt 16 + stmt 8 ödendi/gizlendi.

**İkinci (uygulanMAYAN) neden — bayat overdue-gizleme:** `upsert_cc_statement` `is_past_due =
son_ödeme < bugün` bunu YAZMA anında hesaplar; ekstre vadesi geçmeden yazıldıysa, vade geçince FE
yeniden işlenmedikçe bayat "pending" kalır (günlük süpürme yok). Kullanıcı **kalıcı çözüm #1'i**
(matcher genişletme) seçti; günlük overdue-tazeleme (#2) uygulanmadı — gerçek ödemeyi bağlamak
(gizlemek yerine) tercih edildi.

**Test:** `test_banks_cc_match.py` — `TestLast4Extraction::test_masked_pan_anywhere` +
`TestMatchCcNoKeyword` (7: tam-ödeme+pencere eşleşir, hafif fazla kırpılır, %2-aşan/kısmi/kesim-öncesi/
grace-sonrası/yanlış-kart eşleşmez). Kelime-yolu testleri değişmeden geçer (20 yeşil; geniş finans
süiti 140 yeşil).

---

## Kredi Kartı Ekstresi Projeksiyonu — Nakit Akım (2026-07-04, YENİ)

**İhtiyaç:** 5 kredi kartının ekstreleri her ay düzenli gelir ama hepsi sisteme yüklenmez.
Yüklü olmasa da nakit akımda kartların **kesim + son ödeme tarihleri** ileri aylar için
görünsün; cari ayın ekstresi henüz yoksa **worst-case rezerv** olarak kart limiti kadar borç
yazılsın (nakit planlaması), ileri aylar ise yalnız tarih göstergesi (tutar 0).

**Yaklaşım — OKUMA-ANINDA (materialize DEĞİL):** `app/services/cc_projection_service.py::
compute_cc_projections(db, today, horizon_months=12)`. Kalıcı `finance_event` **YAZILMAZ** —
tarih geçince bayat kalan FE sınıfı sorununu (aynı gün düzeltilen CC overdue-gizleme bug'ı)
tekrar etmemek için bilinçli tercih. Endpoint `GET /cash-flow/cc-projections` (finance.cash_flow
**view**, onaydan muaf GET; `cc_projections.py`). Frontend bunu ay akordiyonuna karıştırır.

**Kural (kullanıcı kararı 2026-07-04):**
- Her **aktif** kredi kartı için cari aydan itibaren **12 ay** ileri; o ay **gerçek (yüklü)
  ekstresi yoksa** projeksiyon üretilir (gerçek ekstresi olan due-ay atlanır).
- **Cari ay** → tutar = kart **LİMİTİ** (`CreditProduct.total_amount`); ay giderine **DAHİL**
  (kullanıcı: "borç olarak yaz" → `groupByMonth` toplamına katılır, `is_projected` toplam-dışı
  YAPILMADI). **Halkbank limiti girilmemişti (0) → 300.000 set edildi** (kullanıcı verdi).
- **İleri aylar** → tutar = **0** (yalnız kesim/son-ödeme tarih göstergesi).

**Kesim/son-ödeme günü türetme (`_derive_days`):** EN SON yüklü ekstrenin gerçek günleri
(kullanıcı: "yüklü ekstrelere bakarak çıkart") + kesim↔son-ödeme ay farkı (`offset`; son ödeme
günü kesimden küçükse ödeme sonraki aya taşar). Ekstre yoksa `details.ekstre_kesim_gunu`/
`son_odeme_gunu` (Halkbank: 25/30). Hiçbiri yoksa kart atlanır. Gün ay-uzunluğuna kırpılır
(31 → Şubat'ta 28/29).

**İKİ kalem türü (`projection_kind`):**
- **`due`** — son ödeme kalemi (tarih=son ödeme; tutar=limit[cari ay]/0[ileri]). 12 ay üretilir.
- **`cut`** — **"Ekstre yükleyin" GÜNLÜK hatırlatıcısı** (tutar=**0**; kullanıcı isteği 2026-07-04):
  **YALNIZ cari ayda**, kesim gününden (veya bugünden, hangisi sonraysa) son ödeme gününe kadar
  **HER GÜN** bir kalem (`event_date=o gün`, `kesim_date`/`son_odeme_date` sabit; `id` = 910M+card*
  1000+gün). Son ödeme geçince biter; **ekstre yüklenince** o ay `real_due`'ya girip komple atlanır
  → hatırlatıcı da kaybolur. **İleri aylarda kesim hatırlatıcısı YOK.** Frontend'de amber
  "↑ Ekstre yükleyin" (tutarsız).

**Kalem şekli:** Frontend `CashFlowItem` ile uyumlu (source=`cc_payment`, `is_projected: true`,
`projection_kind`, `is_current_month`, `kesim_date`, `son_odeme_date`, `has_limit`; sentetik
yüksek-aralık `id` = due:900M / cut:910M + card*1000+i, gerçek FE id'leriyle çakışmaz).
**`is_matched=false`** → toplama girer (çift-sayım kalemi değil).

**EUR bakiye + Runway + T-Hesap'a da dahil (kullanıcı isteği 2026-07-04):** `cc_projection_service.
due_reserve_projections(db)` yalnız tutar taşıyan (cari ay limit) son-ödeme kalemlerini döner;
- `compute_eur_balances` bunu `cc_projection_expense_by_date` olarak günlük EUR gidere + kümülatif
  gelecek gidere ekler → **EUR ay başlığı** rezervi içerir.
- `runway.py` bunu cari-ay **OUT** kalemi olarak ekler (`projected:true`, "(Tahmini)" adıyla; kur
  yoksa `skipped_no_rate`) → **Nakit Koruma** rezervi içerir.
- `t_account.py` bunu, dönemi kapsayan due tarihleriyle **ÇIKIŞ "KK Borç Ödemeleri"** grubuna ekler
  (Panel T-Hesap Cetveli). Cari-ay dışı (geçmiş offset) dönemlerde due tarihi aralık dışı → eklenmez.
Kesim hatırlatıcıları (tutar 0) her üçünde de hariç. ÜÇ tüketici de aynı servisi çağırır → nakit akım
tablosu / EUR başlığı / runway / T-Hesap aynı rezerv sayısını gösterir (tek kaynak).

**Frontend:** `cashFlowCache.projectedItems` (`loadCashFlowProjections`, `loadAllCashFlow` +
`refreshCashFlowFull`'a eklendi → ekstre yüklenince WS ile projeksiyon kaybolur). `+page.svelte`
`filteredItems`'a karıştırır — **yalnız daraltıcı filtre yokken** (tag=all, arama boş, ödeme
yöntemi yok/kredi_karti) + tarih aralığına saygılı. `groupDaySourceItems` tahmini kalemleri
GRUPLAMAZ (her kart ayrı satırda). `CashFlowItem` 3 varyantta: kesikli/soluk kart; `due`→"Tahmini ·
Ekstre yüklenmedi" + "Kesim DD.MM · Son Ödeme DD.MM", `cut`→amber "↑ Ekstre yükleyin"; tıklanamaz,
"Etiketsiz" göstergesi gizli. EUR başlığı/runway backend'den beslendiği için otomatik yansır.

**Test:** `tests/test_cc_projections.py` (16 — cari-ay-limit/ileri-0, kesim hatırlatıcı,
ekstreden/details türetme, yüklü-ay atla, kapalı/günsüz kart atla, gün kırpma, offset+cut-atla,
limitsiz-0, `due_reserve_projections`, endpoint izin+items) + `finance.test.ts` (3). Detay:
`docs/modules/nakit-akim.md`.

---

## Denetim Sonrası İyileştirmeler (2026-06-19)

Kod tabanı denetimi sonrası finans modülünde uygulanan değişiklikler:

- **Banka eşleştirme servisleri tek modülde (`utils/matching_service.py`):** `_match_cc_to_bank`,
  `_match_checks_to_bank`, `_match_credits_to_bank` artık router'larda değil tek servis modülünde.
  `banks.py` eskiden bu private fonksiyonları üç kardeş router'dan (`checks.py`, `krediler/`,
  `banks_cc_match.py`) import ediyordu (katman/coupling ihlali) → artık hepsi `app.utils.matching_service`'ten.
  `banks_cc_match.py` **silindi**; `checks.py`/`krediler/__init__.py` matcher'ı utils'ten re-import eder
  (geriye uyum + iç kullanım korunur). Davranış birebir aynı (test: `test_banks_cc_match.py`).
- **`sales_invoices` performansı:** `_compute` (FIFO) artık 30sn TTL cache'li (`_compute_cached`) — 4
  endpoint (list/summary/advances + yonetim/dashboard) her okumada iki tam tabloyu yeniden RAM'e
  çekmiyordu. `list_invoices` `status` filtresi yokken **gerçek SQL pagination** (count + offset/limit)
  yapar; `status` filtresi FIFO'dan türediğinden o durumda DB-filtreli çekip Python'da sayfalar. İçe
  aktarma sonrası `_invalidate_compute_cache()`. Test izolasyonu: conftest cache'i her test başında sıfırlar.
  **Konum (2026-06-22, D1-1):** FIFO motoru + cache + `_merged_advances` artık
  `app/services/sales_invoice_service.py`'de (`_EPS`/`_f`/`_compute`/`_compute_cached`/`_invalidate_compute_cache`/`_merged_advances`).
  `yonetim.py` oradan import eder (eski router→router import'u kapatıldı); `sales_invoices.py` router'ı
  geriye uyum için re-import eder. `_norm_tokens` → `utils/text_match.py`. Davranış birebir aynı (1152 test yeşil).
- **Upload Excel/PDF parse'ı threadpool'da:** `banks.py`, `checks.py`, `cc_statements.py`,
  `cariler/uploads.py` (+ `sales/reservations/uploads.py`) `async def` upload'larında CPU-yoğun parse
  artık `await asyncio.to_thread(parse_..., path)` ile çağrılır → tek büyük dosya yüklenirken event
  loop bloke olmaz (eşzamanlı istekler beklemez).
- **`finance_event_service` sessiz hata yutmaz:** `upsert_*` + `match`/`unmatch`/`invalidate`/`sync_tag`
  artık hatayı loglayıp **yeniden fırlatır** (`return None` yerine `raise`). Çağıranlar zaten
  `_safe_commit`/try-except içinde → hata rollback'e gider, finance_events tutarsız (eksik kayıt)
  commit edilmez. (`update_amount_try` sayı dönen cron yolu olduğundan dokunulmadı.)
- **GZip + cache (genel):** `main.py`'ye `GZipMiddleware` (büyük JSON liste yanıtları sıkışır);
  `yonetim/dashboard` ve `accounting/fis_icmali/summary` 60sn TTL cache (mizan deseni).

---

## Cari — Sedna (Muhasebe SQL Server) Doğrudan İçe Aktarma (2026-06-06)

Cariler, Excel'e ek olarak doğrudan Sedna muhasebe DB'sinden beslenir (ters SSH tüneli
`127.0.0.1:11433`). Tasarım kararları:

- **Aynı upsert, aynı hash:** `sedna_import.py` Excel yüklemenin (`uploads.py`) upsert mantığını
  birebir yansıtır ve `compute_vendor_tx_hash` ile **aynı** hash'i üretir → Excel/Sedna **mükerrer
  yapmaz**. `_compute_removal_candidates` aynen yeniden kullanılır.
- **Eşleme:** `AccountingTrans` (hareket) + `AccountingOwner` (FicheDate/Voucher) + `Accounting`
  (Remark=ad, PayDay) + `AccDocumentType` (DocumentRemark=işlem tipi). Join **`AccountingCode`
  (string)** ile (int `AccCode` boş/0 — kullanma). Filtre `LIKE '320%' AND Deleted=0`.
- **Türkçe:** pymssql `charset='CP1254'` ŞART (collation cp1254; aksi halde İ→Ý, Ş→Þ bozulur).
- **pymssql `%`-tuzağı:** `LIKE '320%'` paramla verilemez (pymssql `%`'yi format sanır). Prefix
  güvenli kılınıp (sadece rakam) sorguya gömülür ve `execute()` **parametresiz** çağrılır.
- **Loose coupling:** bağlantı yalnızca import'ta; tünel kapalı → `SednaUnavailable` → 503.
  Uygulamanın geri kalanı etkilenmez. `SEDNA_PASSWORD` boşsa endpoint 503 + buton gizli.
- **Onaydan muaf** (operasyonel içe-aktarma, dosya yükleme gibi), audit'li, finance.cariler use.
- **Cari IBAN içe aktarımı (2026-06-06) — `POST /sedna-import-ibans`:** Cari banka/IBAN bilgileri
  Sedna'da **`dbo.Bank`** tablosunda (cari koduna bağlı, firma başına çok IBAN) — `Accounting.BankIbanNo`
  boş olsa da asıl kaynak burası (canlı: 320'li 763 firma / 821 IBAN). `fetch_vendor_ibans()` çeker,
  endpoint `vendor_bank_accounts`'a upsert eder: join `Bank.AccountingCode` (virgüllü) →
  `Accounting.Code` (noktalı) `REPLACE(',','.')`. **Yalnız mevcut carilere** işler (IBAN'ı olup hareketi
  olmayan firma atlanır); dedup (cari+IBAN); caride hesap yoksa ilki varsayılan; boş banka adı doldurulur;
  varsayılan/elle eklenenler korunur → idempotent. Onaydan muaf, audit'li. Test: `test_cariler_sedna.py`.
- **Verilen çek içe aktarımı (2026-06-06) — `POST /checks/sedna-import`:** Aynı Sedna altyapısı
  (`fetch_issued_checks()` → `checks` tablosu). Kaynak `AccCheckTrans`+`AccCheck`; issuance =
  `CheckPosition=100, ActionType=2`; **durum** çekin EN YÜKSEK pozisyonundan (101/102→paid, 103→
  cancelled, gerisi→pending; `_check_status_from_pos`). Eşleşmemiş çeklerde vade + durum senkronize edilir.
  - **Kapsanan hesaplar — 320+159+335 (2026-06-09):** Yalnız satıcı (320) değil; **159** verilen sipariş
    avansı + **335** personel/ortak verilen çekleri de senkronlanır (`_ISSUED_CHECK_PREFIXES_EXTRA`). Eskiden
    320-only → 159/335 çekleri hiç güncellenmiyor, Sedna'da iptal/ödenir/vade-değişse bile bizde "bekliyor"
    kalıyordu (canlı: çek 0353815 159 avans, Sedna pos=103 iptal ama bizde vadesi-geçen pending). Prefix'ler
    rakam → WHERE'e gömülü, `execute` parametresiz (pymssql %-tuzağı).
  - **Dedup anahtarı — vade DEĞİL, tutar (2026-06-08 düzeltildi — KRİTİK):** `_check_dedup_key()` =
    `(check_no, vendor_code, currency, NATIVE tutar)`. **`due_date` ANAHTARDA YOK.** Eski anahtar
    `(check_no, vendor_code, due_date)` idi; Sedna'da çekin vadesi değişince (yeniden vadelendirme)
    yeni anahtar → **mükerrer kayıt** (eski vade "GEÇMİŞ" olarak hayalet kalıyordu, ör. çek 9498648
    02.06→31.07). Yeni anahtarda vade yok → vade değişince mevcut kayıt **GÜNCELLENİR**.
  - **NATIVE tutar (kur-bağımsız):** TL çek → `amount_tl`; **döviz çek → `amount_currency`** (EUR/USD
    yüz değeri). `amount_tl` döviz çekte TL **değerlemesidir ve kurla değişir** → anahtarda kullanılırsa
    her kur hareketinde "yeni çek" sanılır (PEKSAN 30.000 € çeki bunu tetikledi). Tutar aynı no'lu
    **farklı** çekleri de ayırır (ör. 4149098: 900K vs 969K — ikisi de gerçek, ayrı banka ödemesine eşli).
  - **Mükerrer temizliği + dayanıklılık:** Yükleme başında vade-değişiminden kalan **eşleşmemiş**
    mükerrerler tespit edilip silinir (eşleşmiş çeklere DOKUNULMAZ). Her satır kendi `db.begin_nested()`
    SAVEPOINT'inde işlenir → `UNIQUE(check_no,vendor_code,due_date)` çakışması (eski hatalı-tutarlı
    kayıtlar) tüm içe aktarmayı düşürmez, yalnız o satır atlanır. Excel yükleme de aynı `_check_dedup_key`.
  - **Tutar-kayması heal (2026-06-09):** Dedup-key yok ama aynı `(check_no, vendor_code, due_date)` UNIQUE
    üçlüsünde **eşleşmemiş** kayıt varsa (tutar/para bizde bozuk), INSERT yerine **Sedna'ya hizalanır**
    (UPDATE). Eskiden UNIQUE çakışıp sessizce atlanıyor, yanlış tutar kalıcı oluyordu (canlı: PEKSAN 0353816
    bizde 30.000 TL, Sedna'da 30.000 €=1.596.726 TL → 1,56M TL eksik borç, otomatik düzeldi). **Eşleşmiş**
    kayda dokunulmaz (mutabık veri korunur, ör. 714659 paid+banka-eşleşmiş).
  - Test: `test_checks.py::TestSednaCheckImport` (vade güncelleme≠mükerrer, farklı-tutar ayrı, mükerrer
    iyileştirme, tutar-kayması heal/matched-skip, 159/335 prefix, fetch SQL 320+159+335). Detay: `docs/modules/cekler.md`.
- **Merkezi sync orchestrator (2026-06-06) — `sedna_sync.py`:** Tüm Sedna içe aktarmaları TEK
  endpoint'ten çalışır: `POST /finance/sedna/sync-all` (Topbar'daki tek "Sedna" butonu). Her import
  bir **servis fonksiyonu** (`run_cari_import` / `run_iban_import` — `cariler/sedna_import.py`;
  `run_check_import` — `checks.py`): HTTP'siz, broadcast'siz, hata→HTTPException. Tekil endpoint'ler
  bu fonksiyonların **ince sarmalı** (geriye uyumlu + test'ler için). Orchestrator `_STEPS` registry'si
  adımları sırayla çalıştırır; **adım-bazlı izin** (`user_can(db, user, module, "use")`, yetkisiz adım
  atlanır) + **izolasyon** (bir adım patlarsa diğerleri sürer, `db.rollback()` + devam). Adım sonuçları
  `_summarize()` ile özetlenir, frontend modalında gösterilir. **Yeni import eklemek:** `run_xxx_import`
  yaz + `_STEPS`'e satır + `_summarize`'a özet → buton otomatik kapsar. **Sayfa-içi ayrı Sedna butonu
  YOK** (declutter). Test: `tests/test_sedna_sync.py`.
  - **`recurring_sync` adımı (2026-06-06):** Sedna'dan ÇEKMEZ — carilerden **türetir** (cari adımından
    SONRA çalışır). Cari-bağlı düzenli ödemeleri (Elektrik→CK, Su→ASAT) cari gerçek faturayla
    senkronlar (`run_recurring_vendor_sync`, modül `accounting.recurring`). Detay:
    `docs/modules/muhasebe-ik.md` (Cari Senkronu).
- **Güvenlik:** salt-okunur login; şifre yalnız `.env` (600). Test: `tests/test_cariler_sedna.py`.
- **Ters SSH tüneli anahtar sertleştirmesi (2026-06-06 — KRİTİK):** EC2 `~/.ssh/authorized_keys`'teki
  `sedna-reverse-tunnel` anahtarı **yalnız tünel** içindir. `restrict` **tek başına yetmez** —
  no-pty etkileşimli kabuğu kapatır ama **komut çalıştırmayı engellemez**: `restrict,port-forwarding,
  permitlisten=...` anahtarıyla `ssh -i key ec2-user@EC2 'cat .env'` çalışıp **tüm ec2-user dosyalarını
  (sırlar dahil) okuyabilir**. Sertleştirilmiş satır:
  `restrict,port-forwarding,permitlisten="127.0.0.1:11433",permitopen="127.0.0.1:1",command="echo tunnel-only-no-shell"`
  - `command="..."` → forced komut; keyfi komut/kabuk çalışmaz (dosya okuma kapanır). Test edildi: `-R` tünelini **bozmaz** (`-N -R` oturum kanalı açmaz, forced komut çalışmaz).
  - `permitopen="127.0.0.1:1"` → `-L`/`-D` yalnız ölü porta → DB(5432)/IMDS(169.254.169.254) pivotu kapanır. **`permitopen="none"` OpenSSH 8.7'de anahtarı tümden reddeder — kullanma**, ölü port ver.
  - `permitlisten="127.0.0.1:11433"` → `-R` yalnız bu bind'e.
  - Yedek: `~/.ssh/authorized_keys.bak.pre-harden.*`. **Ayrı dikkat:** tam-erişimli admin anahtarları (`otelyeni`, `sprenses-migration@otel-eski`) Ubuntu LAN makinesinde **bulunmamalı** — tünel için yalnız kısıtlı sedna anahtarı yeter.

---

## Banka Ekstresi Yüklemede Yavaşlık — Senkron Push Bildirimleri (2026-06-02 düzeltildi)

**Belirti:** Banka ekstresi yükleme zamanla "çok yavaş" hale geldi. Kod değişikliği
yoktu, tablolar küçük (`bank_transactions` ~2.3K satır, indeksli) → veri/indeks
sorunu değildi.

**Kök neden — istek içinde senkron, zaman aşımsız push gönderimi:**
1. `banks.py:_notify_bank_upload` push bildirimini **`send_push_to_user`'ı doğrudan
   (senkron) çağırarak** gönderiyordu — kod tabanındaki **tek** senkron push çağrısı
   (diğer tüm modüller `background_tasks.add_task(send_push_to_user, ...)` kullanır).
   Bu çağrı `await _post_upload_processing(...)` içinde olduğundan **HTTP yanıtını
   bloklar**.
2. `push.py:send_push_to_user` → `webpush()` **`timeout` parametresi olmadan** çağrılıyordu
   → altındaki `requests` sonsuza dek bekler. Ölü/yavaş bir abonelik endpoint'i tüm
   yüklemeyi kilitler.
3. **Eski abonelik birikimi:** abonelik upsert'i endpoint bazlı; her tarayıcı/cihaz
   yeni endpoint üretir → ölü endpoint'ler birikir (üretimde tek kullanıcıda 77 aktif).
   Her yüklemede çevrimdışı kullanıcıların onlarca ölü aboneliğine boş yere push denenir.

**Çözüm (3 katman):**
- **Arka plan:** `_notify_bank_upload(... , background_tasks)` artık push'u
  `background_tasks.add_task(...)` ile gönderir → yanıt anında döner, push sonra çalışır.
  WS + DB bildirimi inline kalır (yerel, hızlı).
- **Zaman aşımı:** `push.py` `webpush(..., timeout=PUSH_TIMEOUT_SECONDS)` (10sn) — ölü
  endpoint sonsuza dek beklemez. Zaman aşımı `WebPushException` değildir → generic
  `except`'e düşer, abonelik **pasifleştirilmez** (geçici olabilir).
- **Abonelik tavanı:** `push.py:subscribe` → `_prune_user_subscriptions()` kullanıcı
  başına en yeni `MAX_ACTIVE_SUBSCRIPTIONS_PER_USER` (10) aboneliği tutar, fazlasını
  pasifler. Tek seferlik temizlikle mevcut birikim de düşürüldü (aktif 94→32).

**Test:** `test_ws_push_audit.py::test_subscribe_caps_active_per_user` (kullanıcı başına
aktif abonelik sınırını doğrular).

---

## PDF Türk Lirası Sembolü (₺) "Kutu" Sorunu + Ortak Font Helper (2026-06-02 düzeltildi)

**Sorun:** Kredi PDF raporunda (ve Ödeme Talimatı PDF'inde) TL tutarları `₺` yerine
kutu (□) olarak görünüyordu. Kök neden: reportlab'ın varsayılan **Bitstream Vera**
fontu Türk Lirası sembolünü (₺, U+20BA — Unicode'a 2012'de eklendi) içermez. `€ £ $`
Vera'da olduğu için sadece TL etkileniyordu.

**Çözüm — `app/utils/pdf_fonts.py` (yeni ortak helper):**
- `register_turkish_fonts()` → `(base_font, bold_font)` döner.
- Tercih sırası: **DejaVuSans** (sistemde kurulu, `/usr/share/fonts/dejavu-sans-fonts/`,
  ₺ dahil tüm sembolleri içerir) → Vera (₺ yok) → Helvetica.
- DejaVu, Vera'nın çatalıdır ve **Latin metrikleri aynıdır** → tablo düzeni değişmez.
- Sonuç süreç boyunca önbelleğe alınır (TTF her PDF isteğinde yeniden okunmaz).
- Kullanan endpoint'ler: `krediler/products.py:export_credits_pdf`,
  `payment_instructions.py:export_pdf`. (Banka talimatları `₺` yerine "TL" metni
  kullandığından etkilenmiyordu — `pdf_bank_instruction.py` değişmedi.)

**Kredi PDF — EUR renklendirme (aynı commit):** EUR kredileri raporda mavi arka plan
(`#DBEAFE`) + sol kenar aksanı (`#2563EB`) ile vurgulanır; başlıkta "■ Mavi ile
işaretli satırlar EUR kredileridir" açıklaması; para-birimi-bazında toplamda EUR satırı
mavi (`#1D4ED8`). `eur_rows` indeksleri ROWBACKGROUNDS zebra'sının üzerine yazılır
(sonraki TableStyle komutu öncekini ezer).

**Regresyon testi:** `test_credits.py::test_pdf_font_renders_turkish_lira_glyph` —
seçilen fontun `face.charToGlyph` haritasında ₺/€/£/$ glyph'lerinin bulunduğunu
doğrular (kutu regresyonunu yakalar). `test_export_pdf_with_eur_credit` EUR
renklendirme kod yolunu egzersiz eder.

---

## BCH Ödeme Planı finance_events Eksikliği (2026-06-01 düzeltildi)

**Sorun:** `_helpers.py:_regenerate_bch_payments` BCH/recalc taksitlerini oluşturuyor ama
`finance_event_svc.upsert_credit_payment` çağırmıyordu → **BCH kredileri nakit akımda
görünmüyordu**. Ayrıca recalc sırasında silinen ödenmemiş taksitlerin FE'leri
invalidate edilmiyordu → orphan finance_events kalıyordu. Etkilenen krediler: yeni
oluşturulan tüm BCH'ler (örn. 448, 451, 395 — manuel onarıldı).

**Çözüm:** `_regenerate_bch_payments`:
1. Ödenmemiş taksitleri silmeden **önce** her biri için `finance_event_svc.invalidate(db, "credit", pay_id)`
2. Yeni taksitleri `new_payments` listesinde topla → sonunda `db.flush()` + her biri için
   `finance_event_svc.upsert_credit_payment(db, pay, product)`

**Kritik kural:** Taksit/ödeme üreten HER fonksiyon finance_events'e yazmalı (CLAUDE.md
"Her Para Hareketi finance_events'e Yazılmalı"). `_regenerate_kmh_payments` KMH için ayrı
`sync_kmh_to_finance_events` mekanizması kullandığından bu düzeltmeden hariç tutuldu.

**Test:** `test_credits.py::TestBchFinanceEvents` — create→FE üretimi + recalc→FE tazeleme.

---

## `mobile_dashboard_summary` — Banka Bakiyesi Sorgusu (N+1 Giderildi)

`GET /cash-flow/mobile-dashboard` endpoint'indeki banka bakiyesi hesabı artık tek sorguda yapılır.

**Eski yöntem (N+1):** Her `BankAccount` için ayrı bir `BankTransaction` sorgusu çalıştırılıyordu.

**Yeni yöntem:** Subquery ile her hesabın `max(id)` değeri bulunur, ardından tek `JOIN` ile tüm son bakiyeler tek sorguda alınır:

```python
last_tx_sub = db.query(
    BankTransaction.account_id,
    func.max(BankTransaction.id).label("max_id"),
).filter(BankTransaction.balance.isnot(None)).group_by(BankTransaction.account_id).subquery()

last_balance_rows = db.query(
    BankTransaction.account_id,
    BankTransaction.balance,
).join(
    last_tx_sub,
    (BankTransaction.account_id == last_tx_sub.c.account_id) &
    (BankTransaction.id == last_tx_sub.c.max_id),
).all()
```

TRY para birimli hesapları tespit etmek için `account_currency = {a.id: a.currency for a in accounts}` map'i kullanılır — hesap listesi (accounts) zaten çekilmiş olduğundan ek sorgu gerekmez.

---

## Kritik Kural: Her Para Hareketi `finance_events`'e Yazılmalı

Her yeni para hareketi oluşturulduğunda, güncellendiğinde veya silindiğinde
`finance_event_svc` servisi çağrılmalıdır:

```python
from app.utils.finance_event_service import finance_event_svc

# Ekleme / Güncelleme — db.flush() SONRA, db.commit() ÖNCE
finance_event_svc.upsert_*(db, model_instance, ...)

# Silme — silme işleminden ÖNCE
finance_event_svc.invalidate(db, source_type, source_id)

# Eşleştirme (banka ↔ çek/kredi/avans)
finance_event_svc.match(db, type_a, id_a, type_b, id_b)
```

Neden? Nakit akım listesi artık `finance_events` tablosundan okunuyor.
Buraya yazılmayan kayıt nakit akımda görünmez.

**Kritik:** `sync_tag()` çağrılırken `is_matched` da güncellenir. `match_number > 0` → `is_matched = True`.
Bu yapılmazsa eşleşen kayıtlar nakit akımda çift görünür (`WHERE is_matched = FALSE` filtresi çalışmaz).

---

## Yeni Dosya Yükleme Endpoint'i Ekleme

Tüm dosya yüklemeleri `validate_upload_file` kullanmalı:

```python
from app.utils.file_validation import validate_upload_file

@router.post("/upload")
async def my_upload(file: UploadFile = File(...), ...):
    content = await validate_upload_file(file, allowed_types=["excel"])  # veya ["pdf"]
    # content: bytes — artık file.file.read() çağrısına gerek yok
    with open(file_path, "wb") as f:
        f.write(content)
```

**Not:** `validate_upload_file` async'tir — endpoint `async def` olmalıdır.

---

## WS Broadcast — Zorunlu

Her CRUD işlemi sonunda broadcast:

```python
from app.utils.finance_broadcast import broadcast_finance_update

# Endpoint imzasına BackgroundTasks ekle
def my_endpoint(background_tasks: BackgroundTasks, ...):
    # ... işlem ...
    broadcast_finance_update(background_tasks, "banks", "upload")
    # modül: banks, cariler, checks, credits, advances, cash_flow
    # action: upload, delete, update, match, tag
```

500ms debounce otomatik uygulanır — toplu işlemlerde spam olmaz.

---

## Source Type Referansı

| Modül | source_type | upsert metodu |
|---|---|---|
| Banka işlemi | `"bank"` | `upsert_bank_tx(db, tx, account)` |
| Çek | `"check"` | `upsert_check(db, check, bank_tx=None)` |
| Kredi ödemesi | `"credit"` | `upsert_credit_payment(db, payment, product)` |
| Kredi kartı ekstresi | `"cc_payment"` | `upsert_cc_statement(db, stmt, product)` |
| Avans | `"advance"` | `upsert_advance(db, advance)` |
| Cari ödeme | `"vendor_payment"` | `upsert_vendor_tx(db, vtx, vendor, amount_try)` |
| Vergi | `"tax"` | `upsert_scheduled_entry(db, entry, direction=-1)` |
| Düzenli ödeme | `"recurring"` | `upsert_scheduled_entry(db, entry, direction=-1)` |
| Maaş | `"salary"` | `upsert_scheduled_entry(db, entry, direction=-1)` |
| Stopaj | `"withholding"` | `upsert_scheduled_entry(db, entry, direction=-1)` |
| Alınan kira | `"rent_income"` | `upsert_scheduled_entry(db, entry, direction=1)` |
| Verilen kira | `"rent_expense"` | `upsert_scheduled_entry(db, entry, direction=-1)` |
| SGK | `"sgk"` | `upsert_scheduled_entry(db, entry, direction=-1)` |
| Temettü net | `"dividend"` | `upsert_dividend_net(db, payment, desc, event_date)` (bespoke — **payment.id** anahtarlı, kişi-kişi; event_date = gerçek ödeme tarihi veya taksit vadesi) |
| Temettü stopaj | `"dividend_stopaj"` | `upsert_dividend_stopaj(db, payment, desc, event_date)` (net'in efektif ödeme ayının ertesi ayı 26; net geç ödenip ay geçerse stopaj da kayar) |

---

## Çift Sayım Kuralı

İki kayıt aynı para hareketini temsil ediyorsa (ör. banka işlemi + çek):

```python
# Eşleştirme — ikincisi gizlenir (is_matched=True)
finance_event_svc.match(db, "bank", btx_id, "check", check_id)
# Banka işlemi görünür kalır; çek gizlenir

# Eşleştirme iptali
finance_event_svc.unmatch(db, "check", check_id)
```

Nakit akım sorgusu `WHERE is_matched = FALSE` ile sadece aktif kayıtları döner.

**ÇEK İSTİSNASI (2026-07-03 kullanıcı isteği):** Ödenen (bankayla eşleşmiş) çekler listeden
KALDIRILMAZ — `list_cash_flows` sorgusu `OR (source_type='check' AND event_status='paid')`
ile bunları da döndürür; kayıt `is_matched=true` bayrağı taşır. Frontend bunları **toplamlara
KATMAZ** (`groupByMonth` + `groupDaySourceItems` is_matched'i toplam/grup-dışı bırakır) ve
"Ödendi" rozeti + soluk kartla bilgi amaçlı gösterir. Para hareketi banka bacağında sayılmaya
devam eder (çift sayım korunur). **Çek FE'si artık HER ZAMAN vade tarihinde durur**
(`upsert_check` display_date = due_date; eskiden eşleşince banka tarihine taşınıyordu —
32 mevcut FE 2026-07-03'te vadeye geri çekildi). Test: `test_finance.py::TestPaidChecksVisible`
+ `finance.test.ts` is_matched testleri.

**Denetim düzeltmeleri (2026-07-04, aynı özellik):**
- `_match_checks_to_bank` (ekstre otomatik eşleştirme) match() sonrası artık
  **`upsert_check(db, check, best_match)`** de çağırır — match() yalnız is_matched set
  ediyordu, FE `event_status='pending'` kalınca ödenen çek listede görünmüyordu
  (prod'da 41 çek; backfill ile checks tablosundan senkronlandı, toplam 101 ödenen çek
  görünür oldu). Test: `test_auto_matcher_marks_fe_paid`.
- `upsert_check` **is_matched fallback**: bank_tx parametresiz çağrılar (cari-çek
  eşleştirmesi, banka tahmini) bankayla eşleşmiş çekin is_matched'ını False'a
  düşürüyordu → **çift sayım** (prod'da 12 çek). Artık `check.bank_transaction_id`
  doluysa da is_matched=True.
- `nakit-akim/+page.svelte` etiket sonrası `untaggedCount`'ı yalnız `source==='bank'`
  item'lardan sayar (backend `/tags/untagged-count` evreniyle aynı — çek/cari/kredi
  satırları kategorisiz olduğundan rozeti şişiriyordu).

**Kritik Kural:** `is_matched = True` **sadece çift sayım durumlarında** kullanılır:
- Banka hareketi + Çek aynı para → çek `is_matched=True` (banka görünür)
- Banka hareketi + Kredi ödemesi aynı para → kredi `is_matched=True`
- **Cari eşleştirmesi (tag) `is_matched`'ı DEĞİŞTİRMEZ** — banka hareketi nakit akımda görünmeye devam eder
- `sync_tag()` fonksiyonu `is_matched`'a dokunmaz, sadece `match()` ve `unmatch()` fonksiyonları değiştirir

### Kredi Kartı Ekstresi (cc_payment) Kuralları
- CC finance event tutarı **kalan borç** (`toplam_borc - paid_amount`) kullanır — toplam değil
- Banka üzerinden yapılan kısmi ödemeler zaten banka işlemi olarak görünür; CC tarafı yalnızca ödenmemiş kısmı temsil eder
- **Vadesi geçmiş** (`son_odeme_tarihi < bugün`) ekstreler `is_matched=True` ile gizlenir — gerçek ödeme banka kaydında
- `match-cc-payment` ve `unmatch-cc-payment` çağrıldığında `upsert_cc_statement()` ile CC FE otomatik güncellenir
- `eur-balances` endpoint'i de vadesi geçmiş CC ekstrelerini hariç tutar

---

## KMH (Kredili Mevduat Hesabı) — Adat Bazlı Faiz (ÇEYREKLİK, 2026-07-04)

KMH `taksitli kredi` mantığında değildir. Bağlı banka hesabının (`linked_account_id`)
bakiyesi negatife düştüğünde "adat" üzerinden faiz birikir; banka bunu **ÇEYREKLİK**
(üç ayda bir, çeyrek sonunda: 31 Mar / 30 Haz / 30 Eyl / 31 Ara) tahsil eder (kullanıcı
kararı 2026-07-04; canlı QNB KMH faizi 30 Haz'da tek "Faiz Tahakkuku" olarak çekildi).

**Algoritma** (`utils/kmh_calculator.py:calculate_kmh_status`):
```
Adat        = SUM_over_each_day(|negatif_bakiye_o_gün|)   ← gün × |bakiye|
Faiz        = Adat × yıllık_oran / 36000   ← Türk bankacılığı standardı (360 günlük ticari yıl)
BSMV        = Faiz × bsmv_rate / 100
Komisyon    = Faiz × commission_rate / 100
Toplam Borç = Faiz + BSMV + Komisyon
```

**Bölen 36000 (NOT 36500):** Türk bankacılığı kredi faiz hesaplamasında 360 günlük
ticari yıl kullanır. 365 ile bölmek (Avrupa/ABD standardı) yaklaşık %1.4 daha düşük
faiz çıkarır — bu farklı bir hesap olur, banka ekstresiyle uyuşmaz.

**Period (ÇEYREK):** Her ÇEYREK bağımsız hesaplanır. `period_start = max(çeyrek_başı,
KMH.start_date)`, `period_end = çeyrek_son_gün` (`_quarter_first`/`_quarter_last`/
`_next_quarter_first`). Bugüne kadar gerçekleşen adat (`past_adat`) + bugünden çeyrek
sonuna kadar **mevcut bakiyenin devam ettiği varsayılan** projeksiyon (`future_adat`).
`month_label` artık çeyrek etiketi ("2026-Ç3"); ek `quarter` alanı (1-4). Döngü:
KMH-start çeyreği → bugünün çeyreği + 4 gelecek çeyrek projeksiyonu.

**Nakit akım — YALNIZ MEVCUT ÇEYREK (çift sayım engeli, KRİTİK):** `sync_kmh_to_finance_events`
yalnız **mevcut çeyreğin** çeyrek-sonu projeksiyonunu credit_payment+FE olarak yansıtır.
**Geçmiş çeyrekler nakit akıma GİRMEZ** — banka KMH faizini çeyrek sonunda gerçek bir
"Faiz Tahakkuku" banka hareketi olarak zaten tahsil eder (o asıl kaynak); sistem geçmiş
çeyrek projeksiyonu da eklerse aynı faiz İKİ KEZ sayılır (canlı QNB hatası: Mart-Haziran
aylık projeksiyonları ₺9.198 **+** bankanın 30 Haz ₺9.910 çekimi ikisi de nakit akımda,
Mart "vadesi geçen" görünüyordu). Gelecek çeyrekler yalnız KMH detay sayfasında tahmin.
Endpoint her görüntülemede idempotent re-sync eder.

**Forward fill:** Period başlangıcı öncesi son tx'in bakiyesi `initial_balance` olarak
alınır (önceki çeyrek devrinden gelen bakiye dikkate alınır).

**Frontend:** `/dashboard/finans/krediler` — `type='kmh'` kredisi genişletildiğinde
ödeme planı yerine 4 stat kart (Bu Çeyrek Adat/Birikmiş/Tahmini Çeyrek Sonu) +
Çeyreklik Tahakkuklar tablosu + hareketler gösterilir (`GET .../kmh-status`).

**KMH için zorunlu:** `linked_account_id` (bank_accounts FK). Yoksa endpoint 400 döner.
**Test:** `tests/test_kmh.py` (çeyrek yardımcıları + çeyreklik period hizalaması + sync yalnız-mevcut-çeyrek).

---

## Bakiye Hesabı

Nakit akım bakiyesi:
```python
balance = SUM(direction * amount_try)  WHERE is_matched = FALSE AND is_realized = TRUE
```

`is_realized = True` → Gerçekleşmiş işlemler (ödendi, tahsil edildi)
`is_realized = False` → Bekleyen/ilerideki işlemler (vadeli çek, kredi taksiti)

---

## Cari Firma Durumu (Vendor Status)

### Durum Seçenekleri
- `normal` (varsayılan) — Normal cari, ödeme planına dahil
- `odeme_yasaklisi` — Ödeme yasaklı cari, ödeme planından hariç

### Etki Zinciri
1. `PATCH /vendors/{id}/status` ile durum değiştirilir
2. `_get_vendor_net_debts()` (vendor_fifo.py) ödeme yasaklı carileri filtreler
3. `calculate_fifo_amounts()` ve `get_payment_schedule()` bu carileri atlar
4. `sync_vendor_finance_events()` yasaklı carilerin `finance_events` kayıtlarını siler
5. WS broadcast → frontend anlık güncellenir (cari listesi + ödeme planı)

### Frontend Gösterimi
- Cari listesinde "Durum" sütunu — tıklanabilir badge (Normal / Yasaklı)
- Yasaklı cariler kırmızı arka plan + kırmızı badge
- Mobilde yasaklı cariler için ek kırmızı etiket
- Durum değişikliğinde onay diyalogu gösterilir

---

## Cari Ödeme Planı — İş Kuralları

### Vade Tarihi Hesaplama
- **Tüm alacak kayıtları** (sadece "fatura" tipi değil, "Muhasebe Fişi" dahil) vade tarihi alır
- Hesaplama: `fatura_tarihi + payment_days + ilk_cuma`
- `_is_invoice_type()` filtresi KULLANILMAZ — `alacak > 0 && date != null` yeterli koşul
- Vade günü değiştirildiğinde tüm alacak kayıtlarının tarihi yeniden hesaplanır

### Net Borç Bazlı FIFO Kırpma
- Ödeme planı toplamı = Cari Borçları kartı ile **birebir eşleşmeli**
- Her carinin `net_borç = alacak - borç` hesaplanır
- Faturalar en eskiden yeniye sıralanır (FIFO)
- Yapılan ödemeler en eski faturalardan düşülür
- Kısmi ödenen fatura kalan tutarıyla gösterilir
- Vadeli faturası olmayan cariler için `invoice_date + payment_days → next_friday` hesaplanır

### Vadesi Geçmiş Faturaların Kaydırılması (Roll-over)
- Vadesi geçmiş (payment_due_date < bugün) ödenmemiş faturalar **sonraki Cuma'ya** kaydırılır
- `effective_due_date()` fonksiyonu (`vendor_fifo.py`): bugünden itibaren en yakın Cuma'yı döner
- Bu kaydırma hem **ödeme planı** (display) hem **finance_events** (nakit akım) tablosunda uygulanır
- `sync_vendor_finance_events()` çağrıldığında `event_date` güncellenir
- Ödeme planı endpoint'i (`/payment-schedule`) her çağrıda sync tetikler → gün değiştiğinde otomatik güncelleme
- Neden? Ödenmemiş tutarlar eski haftanın listesinde takılı kalmamalı, bir sonraki haftanın bütçesine dahil olmalı

### Kısmi Ödeme / Çek ile Düşme
- Kısmi ödeme (yeni borç kaydı yükleme) → net borç azalır → FIFO yeniden hesaplar → tutar düşer
- Çek eşleştirme (`/transactions/{vtx_id}/match-check/{check_id}`) → `sync_vendor_finance_events()` çağrılır
- Eşleştirme kaldırma → tutar geri eklenir
- Her iki durumda da hem ödeme planı hem nakit akım tablosu otomatik güncellenir
- **Minimum tutar eşiği (0.01 TL):** Float aritmetiğindeki kırıntı hataları (ör. 8.37e-11) filtrelenir — aksi halde finance_events'te 0 tutarlı hayalet kayıtlar oluşur

### Neden Böyle?
- Eski mantık tüm faturaları brüt gösteriyordu (₺41M) — gerçek borç ₺16M
- Kullanıcı sadece ödenmemiş tutarı görmek istiyor
- Bakiyesi sıfır/pozitif cariler ödeme planında yer almaz (zaten ödenmiş)

---

## Cari Eşleştirme Sistemi

### Eşleştirme Türleri
1. **Banka ile eşleştirme** — Nakit akım sayfasına yönlendirme → `match_number` + `payment_method` (havale_eft, nakit vb.)
2. **Çek ile eşleştirme** — Modal ile çek seçimi → `match_number` + `payment_method = "cek"`
3. **Devir işaretleme** — Açılış/devir kayıtları → `match_number = -1`, `payment_method = "devir"`

### match_number Kuralları
- PostgreSQL sequence (`match_number_seq`) ile üretilir
- **Asla tekrar kullanılmaz** — audit trail için her eşleştirme benzersiz numara alır
- Kaldırılıp tekrar yapılan eşleştirme farklı numara alır (ör: #90 kaldırıldı, yeni #91)
- Neden? Denetim izi: "ne zaman eşleştirildi, ne zaman kaldırıldı" takip edilebilir

### Özel match_number Değerleri
- `-1` = Avans/Devir (eşleştirme gerekmez)
- `-2` = İade
- `-3` = Satış Faturası
- `NULL` = Eşleştirilmemiş
- `> 0` = Eşleştirilmiş (banka veya çek ile)

### Eşleştirme Kaldırma
- Cari sayfasında eşleşme badge'inin yanındaki **X** butonu ile kaldırılır
- Çek eşleştirmesi: `DELETE /transactions/{vtx_id}/unmatch-check`
- Banka eşleştirmesi: `DELETE /transactions/{vtx_id}/unmatch`
- Her iki tarafın da (`VendorTransaction` + `BankTransaction/Check`) match bilgisi temizlenir

### Check Modeli Eşleşme Alanları
- `checks.match_number` — Cari eşleştirmesinde atanan numara (VendorTransaction ile aynı)
- `checks.matched_vendor_id` — Eşleşen carinin vendor_id'si
- Eşleştirme yapıldığında her iki tarafa da aynı `match_number` yazılır
- Çekler sayfasında `match_number` varsa "📄 #N" badge'i gösterilir
- Çek iptal edildiğinde `match_number` ile direkt cari işlemi bulunup temizlenir (N+1 sorgu yok)

### Çek Durumu ve Eşleştirme İlişkisi
- Cari ile çek eşleştirmesi çekin durumunu **değiştirmez** — çek "Bekliyor" kalır
- Çek durumu ancak bankadan tahsil edildiğinde "Ödendi" olur (otomatik eşleşme veya manuel)
- Çek "İptal" edildiğinde eşleştirme de otomatik kaldırılır (cari + banka tarafı)
- Kullanıcıya onay diyalogu gösterilir
- Çek tekrar "Bekliyor" yapıldığında eşleştirme geri gelmez — yeniden yapılması gerekir

### Çek Eşleştirme Skorlama
- Tutar tam eşleşme: +50 puan
- Tutar yakın (%5 içinde): +20 puan
- Firma adı 2+ kelime eşleşme: +30 puan
- Firma adı 1 kelime (>3 harf): +15 puan
- Skor sıralamasıyla en uygun çek önerilir

---

## Cari Yüklemesi — Kaynakta Olmayan Kayıtların Tespiti (2026-04-28)

Cari Excel yükleme insert-only çalıştığından, kaynakta (muhasebe programında) silinen bir hareket DB'de durup Excel'in yürüyen bakiyesiyle uyuşmazlığa neden olur. Bu sorunu manuel onaylı bir diff akışıyla çözüyoruz:

### Akış
1. `POST /cariler/upload` yanıtına `removal_candidates: RemovalCandidate[]` eklenir (`uploads.py:_compute_removal_candidates`)
2. Frontend modal'ı (`cariler/+page.svelte`) checkbox listesi gösterir, kullanıcı seçim yapar
3. `POST /cariler/transactions/bulk-delete` çağrısıyla seçilen ID'ler silinir

### Diff Kapsamı (İki Katmanlı Kısıt)
- **Vendor scope:** Sadece yüklenen Excel'deki `hesap_kodu` listesi içindeki vendor'lar
- **Tarih scope:** Sadece Excel'in `min(date) ↔ max(date)` aralığı

Tek vendor yükleyen kullanıcı diğer carilerin kayıtlarını yanlışlıkla silmez; "son 3 ay" Excel'i daha eski kayıtlara dokunmaz.

### Korumalı Kayıtlar (otomatik atlanır)
SQL seviyesinde filtrelenir, asla aday gösterilmez:
- `match_number IS NOT NULL` → banka/çek ile eşleşmiş
- `dept_status IN ('assigned', 'approved')` → departmana atanmış/onaylanmış (`_PROTECTED_DEPT_STATUSES`)
- `finance_events.is_matched = TRUE` (source_type='vendor_payment') → karşı tarafla bağlı

**`dept_status NULL` özel durumu:** PostgreSQL'de `NULL NOT IN (...)` UNKNOWN döner ve WHERE'de FALSE gibi davranır. Bu yüzden filtre `or_(dept_status.is_(None), ~dept_status.in_(...))` şeklinde yazılmıştır — aksi halde tüm yeni eklenen (dept atanmamış) kayıtlar diff'ten atılırdı.

### Bulk Delete Endpoint Güvencesi
`bulk-delete` endpoint'i upload akışından bağımsız olarak da çağrılabilir, bu yüzden korumaları **tekrar kontrol eder** (race condition güvencesi):
- Aynı kontroller burada da uygulanır
- Atlanan kayıtlar `skipped_reasons` alanında raporlanır
- Tek seferde maksimum **5000 ID** (DoS koruması)
- Her başarılı silme `finance_event_svc.invalidate("vendor_payment", id)` çağırır
- Yetim cariler (`VendorTransaction kalmayan Vendor`) otomatik temizlenir
- Audit log: `entity_type=vendor_transaction`, `action=delete`, `entity_id=None`

### Test
- `tests/test_finance.py::TestRemovalCandidates` — 8 test
  - `_compute_removal_candidates` unit testleri (basic diff, tarih kapsamı, korumalı kayıtlar)
  - `bulk-delete` endpoint testleri (boş, auth, 5000 limit, korumalı atla, eksik id)

### Sedna Import — Bayat Satır Otomatik Süpürme (2026-07-02)

**Sorun:** Cari Sedna import'u insert-only + tutar-hash'li; Sedna'da bir hareket sonradan
düzeltilir/silinirse eski yerel satır kalır (nakit akım/bakiyeyi şişirir). `_compute_removal_candidates`
bunları buluyordu ama **yalnız manuel onayla** (`bulk-delete`) siliniyordu → biriktiler (canlı bulgu:
YİĞİTOĞLU +₺795K, +3 cari daha). **Çözüm (`sedna_import._sweep_stale_vendor_txns`):** `run_cari_import`
sonunda, bayat adaylardan **yalnız POZİTİF KANITLI** olanları otomatik siler (emsal: `_sweep_stale_checks`
— "sadece Sedna'da yok" YETMEZ, legit/Excel-only korunur):
- **Sinyal A:** yerel `tx_hash` Sedna'nın **`Deleted=1`** hash kümesinde (soft-delete). Yeni Sedna sorgusu:
  `sedna_client.fetch_cari_deleted_rows()`.
- **Sinyal B:** yerel `(kod, tarih, evrak-rakam)` Sedna **aktifte** var ama tam hash farklı → **tutar düzeltmesi**;
  eski tutarlı satır bayat.
- **Kanıtsız** (hard-delete / elle-eklenmiş, Sedna'da hiç izi yok) → SİLİNMEZ, **manuel silme-adayı** olarak kalır.
- Guard'lar `_compute_removal_candidates` ile birebir (eşleşmemiş, atanmamış, eşleşmiş-FE yok, kapsam-içi) +
  `_SWEEP_SAFETY_CAP=200` devre kesici (aşılırsa süpürme iptal, hepsi manuel adaya düşer). Silme: `finance_event_svc.invalidate` + `db.delete` + WARNING log; sonra `sync_vendor_finance_events`.
- Test: `tests/test_cariler_sedna.py::test_sedna_import_auto_sweeps_stale_rows` (A+B silinir, kanıtsız korunur).

---

## Cari "Devir" Butonu Gösterim Kuralı

- "Devir" butonu **sadece** açıklamasında veya işlem tipinde "açılış" veya "devir" geçen kayıtlarda gösterilir
- Normal ödeme kayıtlarında (EFT, çek vb.) Devir butonu gizlidir
- "Eşleştir" butonu tüm eşleşmemiş borç kayıtlarında gösterilir (ilk kayıda özel değil)

---

## Vade Günü Değişikliği Etki Zinciri

Cari vade günü değiştirildiğinde şu işlemler sırayla yapılır:
1. `Vendor.payment_days` güncellenir
2. Tüm alacak kayıtlarının `payment_due_date`'i yeniden hesaplanır
3. Her kayıt için `finance_event_svc.upsert_vendor_tx()` çağrılır → `finance_events.event_date` güncellenir
4. Frontend'de `schedule = []` ile ödeme planı cache'i sıfırlanır
5. WS broadcast tetiklenir → nakit akım sayfası otomatik yenilenir

---

## Excel Export

### Cariler Listesi (`GET /export/vendors`)
- Tüm cariler: hesap kodu, adı, vade, borç, alacak, bakiye, işlem sayısı
- Renkli başlıklar (teal), negatif bakiye kırmızı, pozitif yeşil
- Alt toplam formülleri

### Ödeme Planı (`GET /export/payment-schedule`)
- Aynı FIFO mantığı ile net borç bazlı
- `get_payment_schedule()` fonksiyonunu çağırarak tutarlılık sağlar

---

## Ödeme Planı EUR Karşılığı

- Ödeme planı yüklenirken TCMB döviz kuru da paralel çekilir (`/finance/exchange-rates/latest`)
- Aylık, haftalık ve toplam tutarların yanında EUR karşılığı gösterilir
- `formatEur(tryAmount)` helper'ı TL→EUR dönüşümü yapar

---

## 90 Gün Dışı Vade Renklendirme

- **< 90 gün** → Mavi arka plan (`bg-blue-100 text-blue-700`)
- **> 90 gün** → Turuncu arka plan (`bg-amber-100 text-amber-700`)
- **= 90 gün** → Normal gri (varsayılan)
- Hem cari listesindeki tablo sütununda hem detay bölümünde uygulanır

---

## Manuel (Ekstre-Dışı) Banka Hareketi + Dedup (2026-06-06)

**İhtiyaç:** Ekstresi henüz alınamayan bir banka işlemini (ör. iki kendi EUR hesabı arası
virmanın ekstre-gelmemiş tarafı) bakiyeye yansıtmak — ama ekstre yüklenince **çift kayıt olmasın**.

**Tasarım:**
- `bank_transactions.source` (`'statement'` | `'manual'`). Manuel satırlar `POST
  /accounts/{id}/manual-transaction` ile eklenir (finance.banks use, audit, onaydan muaf —
  dosya yükleme/eşleştirme gibi özel düzeltme endpoint'i). Tutar **işaretlidir** (negatif=çıkış);
  yeni bakiye = hesabın güncel son bakiyesi + tutar; açıklama `[MANUEL]` ön ekli; tx_hash
  **benzersiz** (`sha256("manual:...uuid")`) → ekstre hash'leriyle asla çakışmaz. `upsert_bank_tx`
  ile finance_event'e de yazılır (her para hareketi kuralı; yön tutar işaretinden).
- **Dedup (kritik):** `_process_statement` ekstre satırlarını işlemeden ÖNCE, o ekstrenin
  kapsadığı **tarih aralığındaki** (`min..max(parsed dates)`) `source='manual'` satırları siler
  ve finance_event'lerini `invalidate` eder. Böylece bakiye-bazlı mükerrer kontrol manuel satırı
  "mevcut" sanıp gerçek satırı atlamaz; ekstre **asıl kaynak** olur. Yükleme sonucu `manual_purged`
  sayısını döner.
- **Neden tarih-aralığı purjü (tutar eşleştirme değil):** Manuel satırın tahmini bakiyesi gerçek
  ekstre satırının bakiyesiyle birebir tutmayabilir; aralık-bazlı temizlik bakiyeden bağımsız
  çalışır ve sağlamdır. Ekstre transferin gününü kapsamıyorsa (daha eski ay) manuel satır korunur.
- **Test:** `tests/test_bank_manual_transaction.py` — oluşturma + bakiye hesabı + finance_event +
  **upload→purge→çift kayıt yok** (kritik) + izin/doğrulama (4 test).

## Banka Ekstre Mükerrer Kontrolü

Mükerrer tespiti **bakiye bazlı** yapılır — en güvenilir yöntem:

1. **Birincil kontrol:** `(tarih, tutar, bakiye)` üçlüsü DB'de var mı?
   - Aynı tarih + aynı tutar + aynı bakiye = **kesinlikle aynı işlem** → atla
   - Farklı bakiye = farklı işlem → ekle
2. **Açıklama bazlı fallback (2026-04-20 düzeltildi):** `(tarih, tutar, normalize_desc)` — **yalnızca bakiye yoksa (None) veya 0 ise** devreye girer. Aksi halde aynı gün/tutar/açıklama olan ama bakiyesi farklı iki ayrı işlem (ör. aynı güne iki ayrı EFT çıkışı) birbirini yutar.
3. **Hash bazlı fallback:** Bakiye ve açıklama eşleşmediyse hash kontrolü — `compute_tx_hash(date, receipt_no, amount, description, seq)` ile çakışırsa seq 1-19 artırılarak benzersiz hash üretilir

**Neden bakiye en güvenilir?**
- Her banka işlemi sonrası bakiye benzersizdir (ardışık işlemler farklı bakiye üretir)
- Aynı gün iki ayrı 100.000 TL çıkış varsa bakiyeleri farklıdır → ikisi de eklenir
- Aynı işlem farklı ekstreden gelirse bakiyesi aynıdır → mükerrer olarak atlanır
- Açıklama formatı farklı olsa bile bakiye değişmez

**Neden sadece hash veya tarih+tutar yetmez?**
- Farklı ekstre formatları aynı işlem için farklı açıklama üretebilir → hash farklı → çift kayıt
- Aynı gün aynı tutar farklı işlem olabilir → tarih+tutar bazlı sayım yanlış sonuç verir

---

## Banka Talimatları (Bank Instructions)

### EFT / Havale / Transfer Talimatı
- `POST /bank-instructions/transfer` — Kaynak ve hedef hesap seçilir, PDF oluşturulur
- PDF formatı: Logo (sol üst) + tarih (sağ üst) + banka başlığı (ortalı, bold) + gövde (justify + paragraf başı) + imzalar
- **İşlem Adı Kuralı (2026-04-16)** — Otomatik tespit:
  - **TL + aynı banka** → "havale" (örn: Halkbank TL → Halkbank TL)
  - **TL + farklı banka** → "EFT" (örn: Halkbank TL → Garanti TL)
  - **TL dışı** (EUR/USD/GBP vb.) → "transfer" (döviz havalesi)
  - `_transfer_term(source_currency, source_bank, dest_bank)` → `"havale"|"EFT"|"transfer"` (case/whitespace toleranslı banka karşılaştırması)
  - Dosya adı da işleme göre: `havale-talimat-*.pdf`, `eft-talimat-*.pdf`, `transfer-talimat-*.pdf`
- **Metin Yapısı (2026-04-16 sadeleştirildi — "bulunan" tekrarı giderildi):**
  - **EFT/Havale/Transfer:**
    > "Şubeniz nezdindeki {hesap_no} numaralı, {source_IBAN} IBAN'lı vadesiz {cur} hesabımızdan, {hedef_banka} {hedef_şube} Şubesindeki {dest_IBAN} IBAN'lı hesabımıza {tutar} tutarında **{havale|EFT} yapılmasını / transfer gerçekleştirilmesini** rica ederiz."
  - **Döviz bozma (aktarım ile):**
    > "Şubeniz nezdindeki {hesap_no} numaralı, {source_IBAN} IBAN'lı {source_name} hesabımızdan {tutar} tutarın **{target_name} cinsine çevrilerek** {target_IBAN} IBAN'lı hesabımıza **aktarılmasını** rica ederiz."
  - **Döviz bozma (aktarım olmadan):** "...tutarın {target_name} cinsine çevrilmesini rica ederiz."
  - **Kaynak hesap IBAN'ı** gövde metninde belirtilir (hesap no varsa + IBAN)
  - **"bulunan" kelimesi artık kullanılmaz** — yerine "-deki" eki kullanılır (anlam düşüklüğü olmaması için)
  - **Fiil seçimi:** havale/EFT → `yapılmasını`, transfer → `gerçekleştirilmesini`, döviz bozma → `çevrilmesini/aktarılmasını`
- **Yazışma Düzeni (2026-04-16):**
  - Platypus `Paragraph` kullanılır — `reportlab.platypus`
  - `ParagraphStyle`: `alignment=TA_JUSTIFY` (iki yana dayalı, sağa-sola yaslı)
  - `firstLineIndent=12*mm` — paragraf başı girintisi
  - `leading=18pt` — satır yüksekliği
  - Açıklama varsa ayrı paragraf olarak "Açıklama: ..." şeklinde render edilir
- **İmza Düzeni (2026-04-16 güncellendi):**
  - **SOL:** Uğur CARUS (Yön.Kur.Üyesi) — varsayılan / **ya da** Erol YILDIZ (Yön.Kur.Bşk.Yrd.)
  - **SAĞ:** İsmail ÖZDEN (Yön.Kur.Baş.) — sabit
  - **Seçim:** PDF oluşturma formunda radio ile yapılır; payload'da `left_signer: "ugur"|"erol"` gönderilir (default: `"ugur"`)
  - Backend: `LEFT_SIGNERS` sabitinden name/title çözülür, bilinmeyen değer → `ugur` fallback
  - "Saygılarımızla," ibaresi imza bloğu öncesinde **ayrı bir paragraf** olarak render edilir (paragraf başı + justify, gövdeyle aynı stil)
- **Para birimi kuralı (2026-04-16):** Kaynak hesabın para birimi ile hedef hesabın para birimi **aynı olmak zorundadır** (TL→TL, EUR→EUR vb.). Farklı para birimi için **Döviz Bozma Talimatı** kullanılır.
  - **Backend:** `bank_instructions.py:create_transfer_instruction` — farklı currency için HTTP 400 döner
  - **Frontend:** Hedef hesap dropdown'u kaynak hesabın para birimiyle süzülür (`transferDestAccounts` derived). Kaynak hesap değiştiğinde mevcut hedef seçimi uyumsuzsa `$effect` ile otomatik sıfırlanır. Eşleşen hedef hesap yoksa kullanıcı "Döviz Bozma Talimatı" sekmesine yönlendirilir.
  - **Frontend rozet:** Form başlığında seçilen işlem türüne göre renkli badge: "Havale (aynı banka)" mavi, "EFT (farklı banka)" teal, "Döviz Transferi" mor — `transferTerm` derived ile canlı hesaplanır.

### Döviz Bozma Talimatı
- `POST /bank-instructions/currency-exchange` — Kaynak hesap + hedef para birimi + opsiyonel hedef hesap
- Metin: "...{tutar}'nin {hedef_para_birimi} olarak bozulmasını [ve {IBAN} nolu hesabımıza aktarılmasını] rica ederiz."

### Hesap Listesi
- `GET /bank-instructions/accounts` — Aktif banka hesaplarını label ile döner

### Frontend
- Rota: `/dashboard/finans/bankalar/talimatlar`
- İki sekme: EFT/Havale + Döviz Bozma
- Hesaplar dropdown'dan seçilir, PDF yeni sekmede açılır
- İzin: `finance.banks` view

### iOS Safari Uyumluluğu — "WebKitBlobResource hatası 1" Fix (2026-04-20)
**Sorun:** iPad/iPhone Safari'de "PDF Oluştur" tuşuna basılınca `blob:https://...` açılamıyor, `WebKitBlobResource hatası 1` veriyordu.

**Kök neden 1 — CMYK logo:** `uploads/logos/1_17e1b8ab.jpg` **CMYK renk modunda** 945×709 / 813KB idi. iOS Safari embedded CMYK görüntü içeren PDF'leri sorunlu render ediyor.
→ `PIL.Image.convert('RGB')` + thumbnail(900×450) → 37KB, PDF 1.1MB → 89KB. Orijinal `.cmyk.bak.jpg` olarak saklandı.

**Kök neden 2 — Blob URL yeni sekme erişimi (asıl sorun):** iOS Safari blob URL'leri yalnızca oluşturan **document context** içinde erişilebilir tutar. `window.open(blob_url, '_blank')` veya `<a target="_blank">` ile yeni sekmede açmaya çalışılan blob'lar `WebKitBlobResource hatası 1` verir — yeni sekme parent blob deposuna erişemez.

**Çözüm — Sayfa içi modal iframe:**
- Blob URL yeni sekmede açılmaya çalışılmaz; bunun yerine **aynı sayfada `<iframe src={blobUrl}>` ile modal** gösterilir (aynı-origin blob sorunsuz çalışır).
- Modal başlığında **Yazdır / İndir / Kapat** aksiyon butonları (Lucide ikonlu: Printer/Download/X) vardır.
  - **Yazdır:** `iframe.contentWindow.print()` ile tetiklenir; hata olursa gizli iframe fallback'i devreye girer (iOS Safari bazen iframe print sinyalini yoksayar — kullanıcıya Paylaş → Yazdır ile fallback önerilir).
  - **İndir:** `<a download>` ile native indirme.
- Tüm platformlarda (iPad / Mac / Windows / Android) aynı akış çalışır — iOS tespiti artık gereksiz.
- Modal kapandığında veya yeni PDF üretildiğinde `URL.revokeObjectURL()` ile bellek serbest bırakılır.
- Esc tuşu ile modal kapatılabilir; backdrop'a tıklama da kapatır.
- **Ortak bileşene çıkarıldı (2026-07-03):** bu desen artık `frontend/src/lib/components/PdfPreviewModal.svelte` paylaşılan bileşenindedir (`pdfModal?.open(blob, dosyaAdi)` — blob URL yaşam döngüsü, Yazdır/İndir/Kapat, Esc bileşenin içinde). Tüketiciler: talimatlar, nakit-akım PDF raporu, krediler PDF raporu. Aynı hata nakit-akım/krediler'in `<a download>` + `click()` deseninde de iPad'de tetiklendi — **blob'lu PDF indirmede tek doğru desen budur.** Test: `PdfPreviewModal.test.ts` (6).

**Yeni logo yüklerken:** `convert_logo_to_rgb(path)` helper'ı çağrılmalı veya upload endpoint'i PIL ile CMYK→RGB dönüşümü yapmalı — aksi halde Safari PDF render'da hatalı renk gösterebilir.

---

## Dosya Yapısı

```
app/routers/finance/
├── banks.py            # Banka hesapları CRUD + ekstre upload endpoint'leri + işlem listesi
├── bank_statement_import.py # Ekstre yükleme/işleme domain mantığı (_save_and_parse/_process_statement/_post_upload_processing)
├── bank_instructions.py # Banka talimatları (EFT/havale, döviz bozma PDF)
├── checks.py           # Çek CRUD + upload + liste/özet/durum endpoint'leri
├── check_import.py     # Çek Sedna içe-aktarma domain mantığı (run_check_import + dedup/infer/sweep)
├── krediler/            # Kredi ürünleri paketi
│   ├── __init__.py      # Alt router'ları birleştirir (prefix="/krediler") + `_match_credits_to_bank` ihracı (banks.py geriye uyumluluk)
│   ├── products.py      # Kredi ürünleri CRUD (list, get, create, update, delete)
│   ├── payments.py      # Ödeme planı CRUD + `_match_credits_to_bank` (banka-kredi otomatik eşleştirme)
│   ├── kmh.py           # KMH durumu (adat, faiz, projeksiyon)
│   ├── summary.py       # Tip bazlı özet + yaklaşan ödemeler
│   └── _helpers.py      # Ortak yardımcı fonksiyonlar (`_build_product_response`, `_batch_payment_stats`, BCH/KMH plan üreticileri)
├── cc_statements.py    # Kredi kartı ekstresi
├── cariler/             # Cari hesaplar paketi
│   ├── __init__.py      # Alt router'ları birleştirir
│   ├── uploads.py       # Excel yükleme, yükleme geçmişi, silme
│   ├── vendors.py       # Cari listesi, detay, vade günü güncelleme
│   ├── payment_schedule.py  # Ödeme planı + Excel export
│   ├── matching.py      # Çek eşleştirme, kaldırma, devir
│   └── _helpers.py      # Ortak yardımcı fonksiyonlar (UPLOAD_DIR, response builder)
├── advances.py         # Avanslar
├── butce.py            # Bütçe yönetimi (kategori + bütçe kaydı CRUD + özet)
├── onay.py             # Departman onay iş akışı (atama, onay, ret)
├── departmanlar.py     # Departman CRUD
├── cash_flow/           # Nakit akım paketi (finance_events üzerinden)
│   ├── __init__.py      # Alt router'ları birleştirir
│   ├── listing.py       # Liste, özet, mobil dashboard
│   ├── matching.py      # Eşleştirme (cari, kredi kartı, kredi)
│   ├── eur_balances.py  # EUR bakiye özeti + compute_eur_balances(db) ortak çekirdek
│   ├── report.py        # Nakit akım PDF raporu (ay/gün bazlı EUR tablosu)
│   ├── runway.py        # Runway / nakit koruma projeksiyonu (ay-içi planlı hareketler EUR)
│   └── _helpers.py      # Ortak yardımcı fonksiyonlar
├── exchange_rates.py   # Döviz kurları
└── transaction_tags.py # Etiketleme + kategori yönetimi
```

---

## Önemli Dosyalar

| Dosya | Açıklama |
|---|---|
| `app/utils/finance_event_service.py` | Merkezi olay deposu servisi |
| `app/utils/finance_broadcast.py` | WS broadcast + 500ms debounce |
| `app/utils/file_validation.py` | MIME + boyut güvenlik doğrulaması |
| `app/models/finance_event.py` | `finance_events` tablo modeli |
| `backend/cron_fetch_exchange_rates.py` | Günlük TCMB kur güncelleme cronu |
| `backend/cron_weekly_push.py` | Pazartesi haftalık push bildirimi cronu |
| `backend/backfill_finance_events.py` | Mevcut verilerin tek seferlik aktarımı |

---

## Veritabanı Rollback Koruması

Çok adımlı veritabanı işlemleri `_safe_commit()` context manager ile sarılmıştır.
Herhangi bir adım başarısız olursa `db.rollback()` çağrılarak tutarsız durum önlenir.

### cariler.py — `_safe_commit(db, error_msg, sync=True)`
Tüm yazma endpoint'leri bu context manager'ı kullanır:
- `upload_vendor_excel`, `delete_upload`, `update_vendor_payment_days`
- `match_vendor_with_check`, `unmatch_vendor_check`, `unmatch_vendor_transaction`
- `mark_as_devir`

`sync=True` (varsayılan) olduğunda commit sonrası otomatik `sync_vendor_finance_events()` çağrılır.

### banks.py
- `_process_statement` — Ekstre kaydı + işlem ekleme döngüsü (flush + finance_event) + commit
- `upload_statement_auto` / `upload_statement` — Otomatik eşleştirmeler (çek, kredi, kredi kartı) her biri `db.begin_nested()` (SAVEPOINT) ile izole edilir; biri başarısız olursa rollback sadece o matcher'ın değişikliklerini geri alır, matched=0 durumunda session'daki asılı değişiklikler sonraki matcher'ın commit'ine sızmaz

**Kural:** `broadcast_finance_update()` her zaman try bloğunun **dışında** çağrılır — rollback sonrasında yanlış WS bildirimi gönderilmez.

---

## Hata Düzeltmeleri

### cariler.py — Refactoring (2026-04-12)
**Sorun:** ~1360 satır, 40+ doğrudan DB sorgusu, tekrarlayan try/except/rollback/broadcast kalıbı, ödeme planı mantığı (~190 satır) `vendor_fifo.py` ile mükerrer, inline import'lar, duplicate `_next_friday`, Excel export'ta tekrarlayan styling kodu, `export_payment_schedule_excel`'de `len(rows)` yerine `len(flat_rows)` hatalı kullanımı.
**Çözüm:**
1. `_safe_commit(db, error_msg, sync)` context manager — 7 endpoint'teki tekrarlayan try/except/rollback/sync kalıbını tek yere topladı
2. `get_payment_schedule(db, from_date, to_date)` fonksiyonu `vendor_fifo.py`'ye taşındı — endpoint ince wrapper oldu
3. `_build_lookup_maps(db, transactions)` — dept/category/user map oluşturmayı tek helper'da birleştirdi
4. `_paginate(total, page, page_size)` — pagination meta tekrarını kaldırdı
5. `_get_eur_rate(db)` — EUR kuru sorgusunu izole etti
6. `_setup_excel_sheet()` / `_excel_response()` — Excel export styling tekrarını kaldırdı
7. `_upsert_vendors()` / `_insert_transactions()` / `_detect_file_headers()` — upload fonksiyonunu parçaladı
8. `_score_candidate_checks()` — skorlama mantığını endpoint'ten çıkardı
9. Tüm import'lar dosya başına taşındı (inline `from datetime`, `from sqlalchemy`, `from openpyxl` kaldırıldı)
10. `vendor_fifo.py`'de `_get_vendor_net_debts()` ve `_get_vendor_payment_days()` ortak helper'ları çıkarıldı — `calculate_fifo_amounts` ve `get_payment_schedule` tarafından paylaşılıyor

### butce.py — Audit Log `details` Tipi (2026-04-12)
**Sorun:** `log_action()` çağrılarında `details` parametresine `dict` geçiliyordu, `str` bekleniyordu → `psycopg2.ProgrammingError: can't adapt type 'dict'` hatası.
**Çözüm:** Tüm `log_action()` çağrılarında `json.dumps(details, ensure_ascii=False)` kullanıldı.

### banks.py — Upload Sonrası Kod Tekrarı (2026-04-12)
**Sorun:** `upload_statement_auto` ve `upload_statement` endpoint'lerinde ~80 satır tekrarlayan otomatik eşleştirme kodu vardı.
**Çözüm:** `_post_upload_processing()` helper fonksiyonu çıkarıldı — WS bildirim + çek/kredi/kredi kartı eşleştirmelerini tek yerde yönetir.

### files.py — session_id Kontrolü (2026-04-12)
**Sorun:** Dosya sunma endpoint'i JWT'den sadece `user_id` çıkarıyordu, `session_id` kontrolü yoktu → çıkış yapmış kullanıcılar hâlâ dosyalara erişebiliyordu.
**Çözüm:** `_authenticate_from_request()` artık `(user_id, session_id)` tuple döner, `serve_file()` aktif oturum kontrolü yapar.

### cash_flow.py — match_credit_payment finance_events Sync Eksikliği (2026-04-12)
**Sorun:** `match_credit_payment` endpoint'i kredi taksitini ödendi olarak işaretliyor ve banka işlemini etiketliyordu ama `finance_event_svc` çağrısı yoktu → eşleşen kredi taksiti nakit akımda hâlâ "pending" görünüyordu, çift sayım engeli çalışmıyordu.
**Çözüm:** `upsert_credit_payment()` + `match()` + `sync_tag()` çağrıları eklendi. try/except + rollback ile sarıldı.

### finance_event_service.py — invalidate() Orphan Match (2026-04-12)
**Sorun:** `invalidate()` sadece kaydı siliyordu, `matched_event_id` ile bağlı karşı tarafın `is_matched` flag'ini temizlemiyordu → silinen kaydın eşi sonsuza dek gizli kalıyordu.
**Çözüm:** Silme öncesi çift yönlü orphan temizliği eklendi — hem bu event'e bağlı karşı taraf hem bu event'in bağlı olduğu karşı taraf temizlenir.

### finance_event_service.py — unmatch() matched_event_id Temizlenmiyordu (2026-04-12)
**Sorun:** `unmatch()` sadece `is_matched=False, is_realized=False` yapıyordu, `matched_event_id` alanını `None` yapmıyordu → eski referans kalıyordu.
**Çözüm:** `matched_event_id: None` update'e eklendi.

### cash_flow.py — Tarih Aralığı + Metin Arama Filtresi Eklendi (2026-04-12)
**Sorun:** `list_cash_flows` endpoint'i tarih aralığı ve metin araması desteklemiyordu. Frontend 5000 kayıt sessizce yüklüyor, kullanıcı truncation farkında olmuyordu.
**Çözüm:**
- Backend: `start_date`, `end_date` (YYYY-MM-DD) ve `search` (ILIKE açıklama/banka/cari/etiket) parametreleri eklendi
- Frontend store: `cashFlowCache.filters` + `applyCashFlowFilters()` + `totalCount` alanı eklendi
- Frontend UI: Açılır filtre çubuğu (tarih + arama) + truncation uyarı banner'ı eklendi

### cash_flow — page_size=5000 Performans Düzeltmesi (2026-04-12)
**Sorun:** Frontend `page_size=5000` ile tüm kayıtları filtresiz çekiyordu → ağ/bellek yükü, 5000+ kayıtta sessiz veri kaybı.
**Çözüm:**
- Backend: `page_size` üst sınırı `5000 → 2000` olarak düşürüldü
- Frontend store: Varsayılan filtre olarak mevcut yılın başlangıcı (`YYYY-01-01`) ayarlandı → ilk yüklemede sadece yıl içi veriler gelir
- Frontend store: `page_size` `5000 → 2000` olarak düşürüldü
- "Temizle" butonu tüm filtreleri kaldırır (kullanıcı bilinçli tercih), `invalidateCashFlowCache()` ise yıl filtresini korur
- Truncation uyarı banner'ı zaten mevcut — 2000+ kayıt durumunda kullanıcı bilgilendirilir

### bank_parser.py — Aynı Gün İçi İşlem Sıralama Hatası (2026-04-15)
**Sorun:** TEB PDF ekstreleri işlemleri ters kronolojik sırada (yeni→eski) listeler. `_ensure_chronological_order` çok günlü ekstrelerde doğru çalışıyordu ama aynı güne ait tüm işlemlerde bakiye zinciri skoru berabere kalıyordu → sıra düzelmiyordu → son bakiye yanlış görünüyordu. TEB EUR hesabında havale (+70K, 16:10) ve çek ödemesi (-70K, 16:12) ters sırayla kaydedildi → bakiye 3,86 yerine 70.003,86 görünüyordu.
**Çözüm:**
1. `ParsedTransaction` modeline `time: Optional[str] = None` alanı eklendi
2. `_detect_columns`'a "saat" kolonu algılama eklendi (TEB format)
3. `_try_parse_mapped_row`'da saat bilgisi çıkarılıyor (HH:MM formatı)
4. `_ensure_chronological_order`'a 2 ek tiebreaker eklendi:
   - Saat bilgisi: ilk TX saati > son TX saati → reverse
   - Dekont numarası: ilk dekont > son dekont → reverse
5. Bu düzeltme tüm banka formatlarını etkiler ama sadece saat/dekont bilgisi olan bankalar için aktif olur

### bank_parser.py — Birebir Zıt Tutarlı Aynı-Gün Çifti (2026-07-06 düzeltildi)

**Sorun:** Türk Eximbank TRY ekstresinde aynı gün (07.04.2026) kredi kullandırımı (+₺6,34M,
income) ve aynı tutarın tam transferi (−₺6,34M, expense) ters sırayla içe aktarıldı — dosyada
transfer önce, kullandırım sonra geliyordu; olması gereken tam tersiydi. `_balance_chain_score`
bu durumda **matematiksel olarak ayırt edemez**: iki işlem `amt[0] == -amt[1]` (birebir zıt)
olduğunda ileri ve geri skor HER ZAMAN eşittir (kanıt: `test_offsetting_pair_balance_chain_is_tied`).
Saat/dekont no da yoksa (bu ekstrede yoktu) tiebreaker'lar devreye giremiyor, fonksiyon dosyadaki
ham sırayı olduğu gibi bırakıyordu → `max(BankTransaction.id)` bazlı "güncel bakiye" hesabı
(listing.py/runway.py) yanlışlıkla ₺6,34M gösteriyordu (gerçek: ₺0, para transfer edilmişti).
**Canlı düzeltme:** 2 kayıt (id 5836/5837) doğru sırayla yeniden oluşturuldu (finance_events dahil).

**Kalıcı çözüm — yeni tiebreaker (saat/dekont'tan SONRA, en son çare):** Tam 2 işlem +
`a.type != b.type` (biri income biri expense) + `abs(abs(a.amount)-abs(b.amount)) < 0.02`
(birebir zıt tutar) ise **gelir gidere ÖNCE gelir** varsayımıyla karar verilir (para
harcanmadan önce alınmış olmalı — makul iş kuralı varsayımı, kesin veri değil). Aynı-tip
(income+income veya expense+expense) çiftlerde bu tiebreak devre dışı kalır — yalnızca bu
özel simetrik duruma (matematiksel ayırt edilemezlik) özgü. Test: `test_offsetting_pair_*`,
`test_non_offsetting_tie_not_affected` (4 test, `TestEnsureChronologicalOrder`).

---

## Test

```bash
# Backend testleri (1220+ test)
cd backend && source venv/bin/activate && python -m pytest tests/ -v

# Finans modülü testleri
python -m pytest tests/test_finance.py tests/test_finance_performance.py tests/test_credits.py tests/test_checks.py tests/test_budget.py tests/test_onay.py tests/test_advances.py -v

# Cron dry-run
python cron_weekly_push.py --dry-run
python cron_fetch_exchange_rates.py
```

### Test Kapsamı (2026-04-12 güncel)
- `test_finance.py` — Nakit akım, banka, cariler, döviz genel testleri
- `test_finance_performance.py` — Performans ve eş zamanlılık testleri
- `test_credits.py` — Kredi ürün CRUD + ödeme planı + remaining_amount testi
- `test_checks.py` — Çek liste, özet, durum güncelleme, yükleme geçmişi
- `test_budget.py` — Bütçe kategori CRUD + bütçe kaydı upsert + bulk + özet
- `test_onay.py` — Departman onay iş akışı (atama, onay, ret, kaldırma)
- `test_advances.py` — Avans CRUD
- `test_scheduled_base.py` — Planlı gider fabrikası (8 modül: vergi, düzenli ödeme, kiralar, temettü, maaş, stopaj, SGK)
- `test_permissions.py` — Tüm endpoint'lerde auth + izin kontrolü

---

## Modül Dokümantasyonu

| Modül | Dosya |
|---|---|
| Finans Mimarisi | `docs/modules/finans-mimarisi.md` |
| Nakit Akım | `docs/modules/nakit-akim.md` |
| Bankalar | `docs/modules/bankalar.md` |
| Cariler | `docs/modules/cariler.md` |
| Çekler | `docs/modules/cekler.md` |
| Krediler | `docs/modules/krediler.md` |
| Avanslar | `docs/modules/avanslar.md` |
| Döviz | `docs/modules/doviz.md` |
| İşlem Etiketleme | `docs/modules/transaction-tags.md` |
| Bütçe | `docs/modules/butce.md` |
| Onay | `docs/modules/onay.md` |
