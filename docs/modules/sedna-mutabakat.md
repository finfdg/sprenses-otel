# Sedna Mutabakat (Uyuşmayan Veriler — Banka ↔ Sedna)

## Genel Bilgi

- **Modül kodu:** `accounting.mutabakat` (Muhasebe altı; modül id=921, parent=Muhasebe)
- **Frontend rota:** `/dashboard/muhasebe/mutabakat`
- **Backend prefix:** `/api/accounting/mutabakat`
- **İzin:** `accounting.mutabakat` — view (özet + listeler), use (tarama + kayıt aksiyonları + hesap eşleme)
- **Tasarım kaynağı:** `docs/denetim/2026-07-11-sedna-mutabakat-incelemesi.md` (9 ajanlık canlı-Sedna ölçüm ve tasarım çalışması — buradaki tüm sayılar/kurallar o incelemeden gelir)

Banka ekstresi hareketleri (`bank_transactions`) ile Sedna muhasebe **102 (Bankalar) defteri**
fiş satırları karşılaştırılır; uyuşmazlıklar kalıcı kayda yazılır ve "Uyuşmayan Veriler"
ekranında gösterilir. Merkezi Sedna senkronunun (`sedna_sync.py:_STEPS` → `bank_recon` adımı)
bir parçasıdır; elle de tetiklenebilir (`POST /run`).

### Kural Hiyerarşisi — EN ÖNEMLİ KURAL (kullanıcı kararı, 2026-07-11)

1. **Banka ekstresi HER ZAMAN otoritedir.** Motor hiçbir `bank_transactions` satırını
   DEĞİŞTİRMEZ — yalnız sınıflandırır. Bankayla çelişen Sedna verisi ASLA otomatik
   düzeltilmez; yalnız uyuşmazlık kaydı + bildirim üretilir.
2. **Sedna sonradan girilince/düzeltilince kayıt OTOMATİK kapanır** (`status='matched'`,
   `resolution='auto'`) ve açık listeden düşer. Gerekçe: 102 fişlerinde giriş gecikmesi
   **medyan 3 gün / p90 = 27 gün**, fişlerin **%36'sı kayıttan sonra değiştiriliyor** —
   otomatik kapanma olmazsa ekran çöp listesine döner (kullanıcı kararı 2026-07-11).
3. Kullanıcı "yoksay" (`resolution='ignored'`) dediği kayıt sonraki koşularda **yeniden
   açılmaz** (bilinçli fark).

## Dosya Haritası

### Backend
| Dosya | Rol |
|---|---|
| `app/models/sedna_recon.py` | `SednaReconRun` + `SednaBankRecon` modelleri + `RESOLUTION_*` sabitleri |
| `app/models/bank_account.py` | `sedna_account_code` (String(30), **unique**) + `sedna_code_confirmed` kolonları |
| `app/schemas/sedna_recon.py` | `ReconItemAction` / `AccountMappingUpdate` / `ReconRunRequest` |
| `app/services/sedna_recon_service.py` | **Motor** — eşleştirme + koşu + hesap eşleme + kayıt aksiyonları (router + onay executor ORTAK, D1-2) + **Faz B:** `report_entity_diff` / `close_stale_entity_diffs` |
| `app/services/fx_service.py` | **Faz B** — `ledger_rate` (Sedna-eşdeğer defter kuru) + `record_match_fx_diff` + `compute_monthly_revaluation` |
| `app/models/event_match.py` | **Faz B** — `EventMatch` (kalıcı eşleşme izi) + `FxDifference` (kur farkı kayıtları) + `MATCH_METHOD_*` sabitleri |
| `app/routers/accounting/mutabakat.py` | 8 endpoint (`accounting/__init__.py` → `prefix="/mutabakat"`; Faz B: `+ fx-revaluation`, `+ fx-differences`) |
| `app/utils/sedna_client.py` | `fetch_bank_leaf_accounts` / `fetch_bank_ledger_rows` / `fetch_bank_ledger_max_dates` + `_safe_codes` (kod injection guard) |
| `app/utils/approval_executor.py` | `_handle_accounting_mutabakat` (op: `resolve_item` \| `account_mapping`) |
| `app/routers/finance/sedna_sync.py` | `_STEPS` → `bank_recon` adımı (merkezi Sedna butonu) |
| `app/constants.py` | `ReconStatus` (durum sözlüğü) + `BroadcastModule.RECON` |
| `alembic/versions/c7d8e9f0a1b2_add_sedna_mutabakat.py` | Migration: 2 tablo + bank_accounts kolonları + RBAC |
| `alembic/versions/e5f6a7b8c9d0_faz_b_event_matches_fx_sedna_ids.py` | **Faz B migration:** `event_matches` + `fx_differences` + recon `entity_type/entity_id` + kalıcı Sedna RecId kolonları (cari/çek/satış) |
| `tests/ci/02_seed.sql` | Modül seed satırı (id=921) |

### Frontend
| Dosya | Rol |
|---|---|
| `routes/dashboard/muhasebe/mutabakat/+page.svelte` | "Uyuşmayan Veriler" sayfası (sekmeler: uyuşmazlıklar + hesap eşleme) |
| `lib/constants/realtime.ts` | `BROADCAST_MODULE.RECON` + durum sabitleri (backend `ReconStatus` ile birebir) |
| `lib/config/navigation.ts` | Muhasebe grubuna `accounting.mutabakat` NavItem (sidebar + route guard) |

## Veritabanı Şeması

### `bank_accounts` (eklenen kolonlar)
| Kolon | Tip | Açıklama |
|---|---|---|
| `sedna_account_code` | String(30), **unique**, null | Eşlenen Sedna 102 leaf kodu (ör. `102.01.02.0003`) |
| `sedna_code_confirmed` | Boolean, default false | **İnsan onayı** — yalnız onaylı hesaplar taranır |

### `sedna_recon_runs` (koşu başlığı — Sedna AccReconOwner deseni)
| Kolon | Açıklama |
|---|---|
| `run_at`, `window_start`, `window_end` | Koşu zamanı + tarama penceresi |
| `triggered_by` | FK users (SET NULL) — tetikleyen kullanıcı |
| `accounts_scanned` / `accounts_skipped` | Taranan / eşlemesiz-atlanan hesap sayısı |
| `matched_count`, `open_count`, `new_count`, `auto_closed_count` | Koşu sayaçları |
| `note` | Serbest not (ör. "Eşlenmiş hesap yok") |

### `sedna_bank_recon` (uyuşmazlık kayıtları)
| Kolon | Açıklama |
|---|---|
| `bank_account_id` | FK bank_accounts (CASCADE) — **Faz B'de NULL'a açıldı** (entity sapma kayıtlarında banka hesabı yok) |
| `entity_type`, `entity_id` | **Faz B** — banka-dışı varlık sapmaları (`check` \| `vendor_tx`; eşleşmiş/korunan yerel kayıtta Sedna farkı). Upsert anahtarı bu ikili; indeks `ix_sedna_bank_recon_entity` |
| `bank_transaction_id` | FK bank_transactions (CASCADE, null) — banka bacağı |
| `sedna_trans_rec_id`, `sedna_owner_id`, `sedna_voucher` | Sedna bacağı (`AccountingTrans.RecId` = kalıcı kimlik — Sedna'nın kendi SourceId damgalama deseninin bizdeki karşılığı) |
| `status` | `constants.ReconStatus` (aşağıdaki durum sözlüğü) |
| `amount`, `currency` | İşaretli tutar (+giriş / −çıkış), **hesap para biriminde** |
| `event_date` | Banka tarihi (banka bacağı varsa) ya da Sedna FicheDate |
| `description` / `sedna_description` | Banka açıklaması / Sedna Remark1 |
| `sedna_record_user`, `sedna_change_date` | Fişi kim girdi / son değişiklik — **"kime sorulacak"** bilgisi |
| `detected_at`, `last_seen_at`, `notified_at` | Yaşam döngüsü damgaları (`notified_at` = tekrar-bildirim yok) |
| `resolved_by`, `resolved_at`, `resolution`, `resolution_note` | Kapanış: `auto` (kendiliğinden) / `manual` (çözüldü) / `ignored` (yoksay) |

- **Kayıt kimliği (upsert anahtarı):** `(bank_transaction_id, sedna_trans_rec_id)` ikilisi.
- **Yalnız AÇIK bulgular + kapanmış geçmiş saklanır** — birebir eşleşen yüzlerce satır
  KAYDEDİLMEZ (koşu sayaçları `sedna_recon_runs`'ta). Tablo şişmez.
- İndeksler: `(bank_account_id, status)`, `bank_transaction_id`, `sedna_trans_rec_id`, `event_date`.

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/accounting/mutabakat/summary` | view | Açık durum sayıları + en eski açık tarih + son koşu + hesap eşleme kapsamı (`mapped_accounts/total_accounts`) |
| GET | `/accounting/mutabakat/items` | view | Uyuşmazlık listesi — **sayfalı** (`page`/`page_size≤200`), `sort_by` **whitelist'li** (`event_date\|amount\|status\|detected_at`) + `sort_dir`; filtreler: `status`, `account_id`, **`entity_type` (`bank\|check\|vendor_tx`, Faz B — `bank` = entity_type'ı NULL banka satırları için takma değer)**, `include_closed`, `q` (banka/Sedna açıklamasında arama). Yanıt satırında `entity_type`/`entity_id` alanları |
| POST | `/accounting/mutabakat/run` | use | Mutabakat taramasını elle tetikle (`window_days` 7–365, varsayılan 45). **Onaydan MUAF** (sınıflandırma — veri mutasyonu değil) + audit + WS broadcast. Tünel kapalı → **503** |
| PATCH | `/accounting/mutabakat/items/{id}` | use + **onay** | Kaydı çöz / yoksay / yeniden aç (`action: resolve\|ignore\|reopen` + `note`) — `check_approval` (op=`resolve_item`) |
| GET | `/accounting/mutabakat/account-mappings` | view | Hesap eşleme durumu + **canlı Sedna** önerileri (102 leaf, Remark-numara skorlaması) — tünel kapalı → **503** olabilir |
| PATCH | `/accounting/mutabakat/account-mappings/{account_id}` | use + **onay** | Banka hesabına Sedna 102 kodu ata/onayla/temizle — `check_approval` (op=`account_mapping`) |
| GET | `/accounting/mutabakat/fx-revaluation` | view | **Faz B** — aylık kur değerlemesi raporu (`year`+`month`; bizim hesap ↔ Sedna Type=4 fişi yan yana). Salt rapor — deftere/FE'ye YAZMAZ. Sedna canlı → tünel kapalıysa **503** |
| GET | `/accounting/mutabakat/fx-differences` | view | **Faz B** — kur farkı kayıtları (646/656 eşleniği; çapraz-para eşleşmelerden birikir). Sayfalı + `total_amount_try` genel toplam |

## Eşleştirme Motoru — 3 Geçişli, Adet-Duyarlı

Canlı ölçüm: geçiş 1 tek başına Sedna satırlarının **~%97'sini** kapatır (288/297 birebir).

1. **Geçiş 1 — (tarih, yönlü tutar) anahtarında k↔k adet eşleme.** Aynı gün + aynı tutar
   serilerinde (ör. 8× maaş) adet korunur: banka k satır ↔ Sedna k satır. Sedna adedi banka
   adedinden FAZLAYSA (ve bankada o anahtar varsa) artan Sedna satırları **mükerrer şüphesi**.
2. **Geçiş 2 — ±3 gün penceresi** (aynı tutar, en yakın tarih). Canlı veride tek istisna
   +3 gündü; pencere genişletilirse yanlış-pozitif üretir.
3. **Geçiş 3 — gün-içi subset-sum (k≤4), İKİ YÖNLÜ:** banka 1 ↔ Sedna N (KDV+damga bölmesi)
   ve banka N ↔ Sedna 1 (ücret+BSMV tek satırda). Aynı günde `SUBSET_DAY_CAP`'ten çok aday
   varsa kombinasyon denenmez (patlama koruması).

Geçiş 2 ile 3 arasında **yön-tersi kontrolü**: aynı gün + aynı mutlak tutar + zıt işaret →
`direction_flip` (borç/alacak ters girilmiş fiş).

### Parametre Sabitleri (tek yerde — `sedna_recon_service.py`)

| Sabit | Değer | Canlı ölçüm gerekçesi |
|---|---|---|
| `DATE_WINDOW_DAYS` | 3 | Geçiş 2 penceresi — 289 eşleşmenin 288'i aynı gündü, tek istisna +3 gün |
| `SUBSET_MAX_K` | 4 | Geçiş 3 küme boyutu üst sınırı (KDV+damga / ücret+BSMV desenleri ≤4 parça) |
| `SUBSET_TOLERANCE` | 0.02 | Küme toplamı toleransı (kuruş yuvarlaması) |
| `SUBSET_DAY_CAP` | 12 | Gün-içi aday üst sınırı (kombinasyon patlaması koruması) |
| `DEFAULT_WINDOW_DAYS` | 45 | Tarama penceresi — giriş gecikmesi **medyan 3 / p90 = 27 gün**, %36 sonradan düzeltme → 45 gün kuyruklu gecikmeyi kapsar |
| `PENDING_ALERT_DAYS` | 15 | Bu yaştan eski `sedna_pending` bildirim konusu olur |
| `_CURRENCY_TO_SEDNA` | `{"TRY": "TL"}` | Sedna `Curr` **'TRY' bilmez, 'TL' kullanır** — çevrim haritası zorunlu |

### Durum Sözlüğü (`constants.ReconStatus` — DB-saklı, DEĞİŞTİRİLEMEZ)

| Durum | Anlamı | Doğduğu canlı vaka |
|---|---|---|
| `matched` | Birebir/grup eşleşti (kapalı — açık listede görünmez) | ~%97 taban vaka |
| `sedna_pending` | Bankada var, Sedna **henüz girmemiş** (hesabın Sedna `max(FicheDate)`'inden SONRAKİ banka işlemi) — gecikme, **uyuşmazlık DEĞİL**; 15 günü aşarsa bildirim konusu | Giriş gecikmesi medyan 3 / p90 27 gün |
| `sedna_missing` | Bankada var, Sedna **dönem içinde girmemiş** (gerçek eksik) | Kapsama penceresi içinde hiç girilmemiş kredi taksit tahsilatları, gelen EFT'ler, kâr payı ödemeleri, 680.000 TL virmanın iki bacağı, POS bloke çözümü |
| `sedna_extra` | Sedna'da var, bankada yok (muhtemel hatalı giriş) | Bankaya yansımayan defter satırları |
| `direction_flip` | Aynı gün + aynı mutlak tutar + **TERS yön** (borç/alacak ters bacaklı fiş) | **3 canlı vaka:** 5.000 TL ve 1.645.000 TL EFT'ler ters bacaklı; en ağırı 4.275.120 TL banka faiz ÖDEMESİ 642 faiz GELİRİ yazılmış (tek fişte ~8,5M TL sapma) |
| `duplicate_suspect` | Sedna adedi > banka adedi (mükerrer fiş şüphesi) | **13.500 EUR** aynı gün çift girilmiş fiş |
| `sedna_diff` | **Faz B** — eşleşmiş/KORUNAN yerel kayıtta (çek/cari) Sedna farkı: yerel kayıt otomatik DEĞİŞTİRİLMEZ, fark burada gösterilir (`entity_type`/`entity_id`'li) | Eşleşmiş çekte vade/tutar/iptal farkı; eşleşmiş cari satırının Sedna'da düzeltilmesi/silinmesi |

Frontend karşılığı `lib/constants/realtime.ts`'te tutulur — iki taraf **birebir aynı**
(merkezi sabitler kuralı; otomatik senkron yok).

### Nakit-Dışı Filtre — Değerleme Satırları

Sedna ay sonu **kur farkı değerleme** satırları gerçek nakit hareketi DEĞİLDİR ve eşleştirme
evrenine **ALINMAZ** (`classify_sedna_row` → `'valuation'`):

- `AccountingOwner.Type = 4` (Sedna'da bu fiş tipi YALNIZ kur farkı değerlemesi için kullanılıyor, 18/18), **VEYA**
- döviz hesabında `Rate = 0` **ve** `CurrDebit = CurrCredit = 0` (yalnız TL bacağı düzeltilir,
  döviz miktarı değişmez — Sedna'nın çift-bakiye deseni).

Bu filtre olmasaydı **her ay sonu sahte uyuşmazlık yağmuru** oluşurdu (bankada karşılığı
olmayan defter-içi düzeltmeler `sedna_extra` görünürdü).

**İşaret/tutar kuralı (canlı doğrulandı):** bizim `amount > 0` (giriş) = Sedna 102 **Borç**.
Döviz hesabında tutar `CurrDebit/CurrCredit`'ten alınır (`Debit/Credit` TL karşılığıdır);
TL hesapta `Debit/Credit`.

### Koşu Bütünlüğü — Tek Sorgu, Kısmi Veri Yok

- Sedna verisi **TEK sorguyla** çekilir (`fetch_bank_ledger_rows` — tüm eşlenmiş hesap kodları
  tek `IN (...)` listesinde). Tünel koparsa `SednaUnavailable` yükselir ve **HİÇBİR kayda
  dokunulmaz** — kısmi veriyle sahte uyuşmazlık yazılmaz (yazılsaydı ilk haftada güven biterdi).
- `fetch_bank_ledger_rows` **çift soft-delete filtresi** uygular (`t.Deleted` + `o.Deleted`) —
  canlı fişlerin İÇİNDE silinmiş satır var (32/2476).
- Yalnız `sedna_code_confirmed = true` (insan onaylı eşlenmiş) hesaplar taranır; eşlemesizler
  `accounts_skipped` sayacına düşer.
- Hesap kodları `_safe_codes` ile doğrulanır (yalnız harf/rakam/nokta — SQL gömme güvenliği;
  Sedna leaf'leri harf içerebilir: `340.01.01.L001`).

## Hesap Eşleme (banka hesabı ↔ Sedna 102 leaf)

Sedna'da IBAN alanları pratikte **boş** (102 leaf'lerinde `BankIbanNo` 3/137) → IBAN'la eşleme
imkânsız. Güvenilir anahtar **skorlamayla** kurulur (`suggest_account_mappings`):

| Sinyal | Puan |
|---|---|
| `Remark`'a gömülü hesap numarası (≥6 haneli rakam grubu, bizim IBAN/hesap-no rakamlarında geçmeli) | +60 (ana sinyal) |
| Banka adı token kesişimi (`_norm_tokens`) | +25 |
| Para birimi eşleşmesi (**TRY↔'TL' çevrimi** ile) | +15 |

- Öneri yalnız **skor ≥ 60** ve hesabın mevcut kodu yoksa gösterilir; eşlenmemiş Sedna
  leaf'leri ayrıca listelenir (`unmatched_sedna` — YKB kırılım şüphesi gibi vakaların incelenmesi için).
- **İnsan onayı zorunlu:** öneri otomatik uygulanmaz — kullanıcı `PATCH /account-mappings/{id}`
  ile atar/onaylar (`sedna_code_confirmed`). Canlı ölçümde 28 hesabın 26'sı güvenle eşlendi;
  2'si Sedna tarafındaki yazım hatası nedeniyle insan kararı ister (Halkbank USD hane eksik,
  Halkbank EUR POS).
- Kod `102` ile başlamak zorundadır (`set_account_mapping` doğrular); `null` → eşlemeyi temizler.

## Onay Akışı Kapsamı

- **`POST /run` onaydan MUAF** — tarama veri mutasyonu değil **sınıflandırmadır** (banka/Sedna
  verisi değişmez); CLAUDE.md'deki "dosya yükleme, toplu işlem" istisna sınıfına girer.
  Audit (`run`) + WS broadcast yine yapılır.
- **PATCH endpoint'leri `check_approval`'lıdır:** kayıt aksiyonu (op=`resolve_item`,
  entity_id=`SednaBankRecon.id`) ve hesap eşleme (op=`account_mapping`, entity_id=`BankAccount.id`).
- **Executor handler:** `approval_executor._handle_accounting_mutabakat` — `payload["op"]` ile
  iki mutasyonu ayırır ve router'la **AYNI service fonksiyonlarını** çağırır
  (`sedna_recon_service.resolve_recon_item` / `set_account_mapping`) — D1-2 ortak-service deseni,
  sapma yapısal olarak imkânsız.

## Bildirim + Gerçek Zamanlılık

- **Yeni KRİTİK uyuşmazlıkta** (`direction_flip`, `duplicate_suspect`, `sedna_missing`,
  `sedna_extra`, **`sedna_diff`** — Faz B) `accounting.mutabakat` **view** izni olan tüm aktif kullanıcılara **tek toplu
  bildirim** gönderilir ("3 Yön ters · 1 Mükerrer şüphesi — Uyuşmayan Veriler ekranından
  inceleyin", link `/dashboard/muhasebe/mutabakat`). `sedna_pending` bildirim üretmez (gecikme
  normaldir).
- `notified_at` damgasıyla **tekrar-bildirim yok**; bildirim hatası koşuyu düşürmez (try/except + log).
- WS: `BroadcastModule.RECON` — koşu ve kayıt aksiyonları sonrası `broadcast_finance_update`
  (polling yasak kuralı gereği ekran WS ile tazelenir).

## Frontend UI Yapısı

- **Rota:** `/dashboard/muhasebe/mutabakat` — tasarım sistemi zorunlu bileşenleriyle
  (PageHeader + StatCard + filtre barı + tablo + Pagination + Modal/ConfirmDialog + EmptyState +
  Skeleton + StatusBadge + Lucide; referans iskelet: `finans/avanslar`).
- **Özet kartlar:** açık uyuşmazlık toplamı + durum kırılımı + en eski açık tarih + eşlenmiş
  hesap kapsamı (`mapped/total`) + son koşu özeti (`/summary`).
- **Sekmeler:** Uyuşmazlıklar (durum filtreli liste; satır aksiyonları: Çözüldü / Yoksay /
  Geri aç — not alanıyla) · Hesap Eşleme (öneri skorları + onay; `unmatched_sedna` listesi).
- **Detay gösterimi:** banka satırı ↔ Sedna fiş bacağı yan yana + `sedna_record_user` /
  `sedna_change_date` ("kime sorulacak").
- **Tetikleme:** Topbar'daki merkezi **Sedna** butonu `bank_recon` adımını çalıştırır
  (sayfa-içi ayrı Sedna butonu eklenmez kuralı); sayfadan `POST /run` ile elle tarama da var.
- `navigation.ts`'e NavItem (sidebar + route guard otomatik gelir).

## Audit Log Entegrasyonu

| Eylem | entity_type | entity_id | details |
|---|---|---|---|
| Tarama (`POST /run`) | `sedna_recon` | — | `window_days` + koşu özeti (JSON) |
| Kayıt aksiyonu (`PATCH /items/{id}`) | `sedna_recon` | kayıt id | `action` + `note` |
| Hesap eşleme (`PATCH /account-mappings/{id}`) | `bank_account_sedna_map` | hesap id | atanan kod + confirmed |

## Faz B (2026-07-11) — Kalıcı Sedna Kimliği + Eşleşme İzi + Kur Farkı Katmanı

İnceleme raporundaki Faz B çekirdeği uygulandı (migration `e5f6a7b8c9d0`).
**POLİTİKA HATIRLATMASI (değişmez):** banka-kanıtlı / KORUNAN yerel kayıt (eşleşmiş
`match_number`/`bank_transaction_id` veya departmana atanmış) **ASLA otomatik değiştirilmez** —
Sedna farkı `sedna_diff` sapma kaydına yazılır, karar insanındır. Korumasız kayıtta ise Sedna
otoritedir (rec_id-kimlikli güncelleme/aynalama aşağıda).

### 1) `ledger_rate` — Sedna-eşdeğer defter kuru (1 gün kayma, KRİTİK)

`app/services/fx_service.py::ledger_rate(db, value_date, currency)`:
**defter kuru = `exchange_rates(value_date − 1).forex_buying`** (satır yoksa en yakın ÖNCEKİ
gün — hafta sonu taşması Sedna ile aynı hizaya gelir; TRY/TL → 1.0; kur bulunamazsa `None`
döner — sessiz 0 üretmez, çağıran karar verir).

- **Neden −1 gün:** Sedna `ExchangeRate(G).Buying` == bizim `exchange_rates(G−1).forex_buying`.
  Sedna'daki tarih kurun **"geçerlilik"** tarihi, bizimki **"yayın"** (TCMB bülten) tarihidir →
  1 gün kayma. Canlı doğrulama (2026-07-11): Sedna fiş kuru **53,3716** = bizim bir önceki
  günün `forex_buying` değeri (tüm Temmuz satırlarında birebir).
- Sedna fiş kurları ve ay sonu değerlemesi TCMB **döviz ALIŞ (Buying)** kullanır (Faz A kur
  kararının devamı). **Yeni kur-duyarlı Sedna-mutabakat kodu bu fonksiyonu çağırmalı**, elle
  `forex_buying` sorgusu yazmamalı.

### 2) `event_matches` + `fx_differences` (yeni tablolar — `app/models/event_match.py`)

- **`event_matches`** — Sedna `AccountingMatch` deseninin bizdeki karşılığı: hangi banka
  kaynağı hangi kalemi hangi tutar/kur/yöntemle kapattı (`bank_source_type/id` +
  `target_source_type/id` + `amount` [hedef para biriminde] + `currency` + `rate_used`
  [hedef dövizse `ledger_rate`] + `method` `auto|manual|suggestion` + `score` + `created_by`).
  **SALT-EK katman:** finance_events `is_matched`/`match_number` davranışı DEĞİŞMEZ.
  `finance_event_service.match()` yazar; `unmatch()`/`invalidate()` kaynağın taraf olduğu
  izleri siler. Yazma/silme **best-effort** (hata loglanır, eşleşmeyi ASLA düşürmez).
  İleride öneri kuyruğu (`method='suggestion'` — henüz üretilmiyor) ve kısmi/1-N eşleşme
  aynı şemayı kullanır.
- **`fx_differences`** — çapraz-para eşleşmede (banka bacağı TRY ↔ hedef kalem döviz)
  otomatik kur farkı kaydı; Sedna **646 (kambiyo karı) / 656 (kambiyo zararı)** eşleniği.
  `amount_try` **işaretli: + = kar, − = zarar** (gider kaleminde beklenenden AZ TL ödemek kar,
  gelir kaleminde FAZLA TL almak kar — `fx_service.record_match_fx_diff`). `rate_estimate` =
  kalem vadesindeki `ledger_rate`, `rate_realized` = gerçekleşen TL/döviz oranı; `source`:
  `match` | `revaluation`. `event_match_id` FK **CASCADE** (eşleşme izi silinince fark da düşer).
  **finance_events'e kalem YAZILMAZ** (kur farkı nakit hareketi değildir — kullanıcı kararı
  2026-07-11).

### 3) Aylık kur değerlemesi raporu — `compute_monthly_revaluation`

`fx_service.compute_monthly_revaluation(db, year, month)` (endpoint `GET /fx-revaluation`):
eşlenmiş (onaylı) **döviz** banka hesapları için bizim hesap ↔ **Sedna Type=4 değerleme fişi**
yan yana. Değerleme formülü (Sedna ile aynı):

```
expected_try = ay sonu ekstre döviz bakiyesi × ledger_rate(ay sonu günü)   ← döviz × TCMB ALIŞ
```

Durum: `mutabik` (fark ≤ %0,5 veya 100 TL) / `sapma` / `sedna_bekliyor` (o ayın Type=4 fişi
henüz yok — Sedna kapanışı 1-3 ay gecikebilir, sapma SAYILMAZ) / `veri_eksik`.
**KARAR: değerleme RAPOR katmanında kalır — deftere/finance_events'e YAZMAZ** (kullanıcı
kararı 2026-07-11; FE'ye/deftere yazma ancak ayrı bir kullanıcı kararıyla açılır).

### 4) Kalıcı Sedna kimliği (RecId) + korunan-kayıt sapmaları

Sedna sorguları artık satır kimliği döndürür (`sedna_client`: `AccountingTrans.RecId` /
`AccCheck.RecId`) ve yerel tablolara damgalanır — hepsi **partial unique** indeksli
(`WHERE ... IS NOT NULL`):

| Yerel tablo | Kolon |
|---|---|
| `vendor_transactions` | `sedna_rec_id` |
| `checks` | `sedna_check_rec_id` |
| `sales_invoices` / `sales_collections` | `sedna_rec_id` |

- **Cari import (`cariler/sedna_import.py`):** rec_id-kimlikli **GÜNCELLEME geçişi** (insert'ten
  önce) — Sedna'da tutar/tarih/evrak düzeltilen KORUMASIZ satır artık sil+ekle (sweep) döngüsüne
  düşmez, doğrudan **UPDATE** edilir (+ payment_due + FE tazeleme). KORUNAN satırda fark →
  `report_entity_diff('vendor_tx', …)` + yeni-hash'li satırın **mükerrer insert'i engellenir**.
  Korunan satır Sedna'da **SİLİNMİŞSE** (Deleted=1) de sapma raporlanır ("muhasebeyle görüşün").
  Hash'i eşleşen eski satırlara **rec_id geri-doldurma** yapılır. Koşu sonunda bu koşuda
  görülmeyen açık sapmalar `close_stale_entity_diffs(db, "vendor_tx", …)` ile otomatik kapanır.
- **Çek import (`check_import.py`):** EŞLEŞMİŞ çekteki önemli Sedna farkı (vade / native tutar /
  iptal) artık **sessiz atlanmaz** → `report_entity_diff('check', …)`. `sedna_check_rec_id`
  yeni satıra yazılır, mevcut/drift satırlara geri-doldurulur. Koşu sonunda
  `close_stale_entity_diffs(db, "check", …)`.
- **Satış faturaları (`sales_invoices.py`):** saf insert-only KALKTI → **TAM AYNALAMA**:
  (1) rec_id'li yerel satır Sedna'dan güncellenir (tutar düzeltmesi çift satır üretmez),
  (2) hash eşleşen rec_id'siz eski satıra kimlik geri-doldurulur, (3) yeni satır rec_id'li
  eklenir, (4) rec_id'li olup Sedna aktifinden **kaybolan yerel satır SİLİNİR** — güvenlik
  tavanı **`_MIRROR_SWEEP_CAP=300`** (aşılırsa süpürme İPTAL, yalnız log; olası kısmi
  veri/mantık hatası koruması); **rec_id'siz eski satırlara dokunulmaz**. Fatura + tahsilat
  iki küme için de aynı akış. `sedna_sync` satış adımı artık **`BroadcastModule.SALES_INVOICES`**
  yayınlar (yeni sabit).

### `sedna_diff` — yeni durum + servis fonksiyonları

- `ReconStatus.SEDNA_DIFF = "sedna_diff"` (`constants.py`) — eşleşmiş/korunan yerel kayıtta
  Sedna sapması. `sedna_bank_recon`'a **`entity_type`** (`check` | `vendor_tx`) + **`entity_id`**
  eklendi (upsert anahtarı bu ikili; bu kayıtlarda `bank_account_id` NULL). **Kritik durum
  kümesindedir** (`_CRITICAL_STATUSES`) — bildirim sınıflandırmasında kritik sayılır
  (toplu bildirim akışı mutabakat koşusu üzerinden çalışır).
- `sedna_recon_service.report_entity_diff(...)` — sapma upsert'i: kullanıcı **'yoksay'**
  dediyse yeniden açmaz; kapanmış kayıtta sapma geri gelirse **yeniden açar**.
  `close_stale_entity_diffs(...)` — koşuda artık raporlanmayan açık sapmaları otomatik kapatır
  ("giderilince otomatik kalksın" kuralının entity ayağı).
- `GET /items` `entity_type` filtresi (`bank|check|vendor_tx` — `bank`, entity_type'ı NULL
  banka satırlarını seçen takma değerdir; frontend tür filtresinin "Banka" seçeneği) + yanıt
  satırında `entity_type`/`entity_id`.
- **Test:** `tests/test_faz_b.py` — `ledger_rate` (önceki gün + hafta sonu taşması + TRY=1 +
  kur-yok=None), event_match izi (match yazar / unmatch+invalidate siler), çapraz-para kur
  farkı (+kar/−zarar işareti, aynı-para üretmez, unmatch CASCADE), entity sapma raporu
  (upsert / yoksay-yeniden-açmaz / auto-close / geri-gelince yeniden açılır), cari rec_id
  import akışı (güncelle + guard + geri-doldurma + silinmiş-korunan sapması), çek sapması,
  satış tam aynalama (düzeltme=tek satır, kaybolan=silinir).

## Geliştirme Kuralları

1. **Banka verisi otorite** — motora banka satırı DEĞİŞTİREN kod eklenemez; yeni sınıf
   eklenecekse yalnız sınıflandırma katmanına eklenir. Bankayla çelişmeyen defter alanları
   (çek vadesi, unvan vb.) bu modülün konusu değildir (o alanlarda Sedna otorite — ilgili
   import modülleri günceller).
2. **Durum değerleri DB-saklıdır** (`ReconStatus`) — değiştirilemez; yeni durum = migration
   değil ama frontend `realtime.ts` sabitleriyle birebir senkron zorunlu (merkezi sabitler kuralı).
3. **Eşleştirme parametreleri tek yerde** (`sedna_recon_service.py` üst sabitleri) — endpoint
   veya UI'ya parametre kopyalama yok. Değişiklik gerekçesi bu dosyada belgelenir.
4. **Koşu bütünlüğü bozulamaz:** Sedna fetch'i parçalara bölme (hesap-hesap sorgu) YASAK —
   kısmi veri sahte uyuşmazlık üretir. `SednaUnavailable` her zaman kayıtlara dokunmadan yayılır.
5. **Test edilebilirlik:** `run_reconciliation(fetch_rows=..., fetch_max_dates=...)` ve
   `suggest_account_mappings(leafs=...)` enjekte edilebilir — CI'da tünel yokken motor saf
   verilerle test edilir. Yeni davranış eklerken CLAUDE.md test katmanları kuralı geçerlidir
   (executor için modül-bazlı uçtan-uca onay regresyon testi dahil).
6. **Tarih-kritik kod İstanbul-açık:** `_today()` = `datetime.now(tz_istanbul).date()` —
   TZ drop-in'e örtük güvenilmez (CLAUDE.md saat dilimi kuralı).

### Kur Kararları (2026-07-11, kullanıcı onaylı)

- **EUR raporlama çevrimi `forex_selling` → `forex_buying`'e geçirildi** — Sedna defter kuru
  **TCMB döviz ALIŞ** ile hizalama (Sedna fiş Rate'leri TCMB Buying ile birebir doğrulandı).
  Tarih semantiği farkı bilinçli not edilir: **Sedna ExchangeRate(G) = bizim
  exchange_rates(G−1)** (Sedna "geçerlilik", biz "yayın" tarihi — Sedna kur tarihi bizimkinden
  1 gün ileridir). Etkilenen yerler: `eur_balances`/`t_account`/`runway`/`_helpers` + çek/cari/
  kredi özetleri + rezervasyon/stok/hakediş servisleri (bkz. `docs/modules/nakit-akim.md`).
- **Aylık kur değerlemesi RAPOR katmanında kalır — `finance_events`'e kalem YAZILMAZ**
  (Claude kararı, kullanıcı yetkilendirdi): değerleme nakit hareketi değildir; Sedna'da da
  değerleme fişi döviz bakiyesine dokunmaz. **Faz B ile uygulandı (2026-07-11):** değerleme
  raporu Sedna Type=4 fişleriyle yan yana kıyaslanır (`GET /fx-revaluation` — aşağıdaki Faz B
  bölümü); deftere/FE'ye yazma ancak ayrı kullanıcı kararıyla.

### YIL DEVRİ RİSKİ — Bilinçli Açık Madde (KRİTİK)

`config.sedna_database` sabit **`SednaPrensesMhs2026`**. **1 Ocak 2027'de:**

- Yeni yıl DB'sine (`...Mhs2027`) **SELECT izni** verilmeli (btadmin login'i),
- **Ocak–Şubat çift-DB penceresi** gerekecek: giriş gecikmesi p90 = 27 gün → **Aralık fişleri
  Ocak'ta ESKİ DB'ye girilmeye devam eder**; yalnız yeni DB okunursa Aralık kuyruğu
  `sedna_missing` yağmuru üretir,
- Açılış-devir fişleri eşleştirme evreninden filtrelenmeli.

**Henüz çözülmedi** — cari/çek/satış/stok importları da aynı sabitten etkilenir. Yıl sonundan
önce tasarlanmalı (bkz. inceleme raporu "Faz A ön koşulları").

### KAPSAM DIŞI — "YAPMA" Listesi

Bu modül bir **mutabakat/uyarı katmanıdır**, muhasebe sistemi DEĞİLDİR:

- **Çift taraflı defter / fiş üretimi YOK** — hiçbir Sedna fişi oluşturulmaz/değiştirilmez.
- **Kendi 646/656 hesap planı YOK** — kambiyo kar/zarar hesapları Sedna'nındır.
- **KDV'li kur farkı faturası kesme YOK** — muhasebeci işi.
- **108 POS geçiş hesabı modeli YOK** — POS yatışını ekstre doğrudan görür (bilinçli).
- **DocumentType haritası YAPILMAZ** — Sedna'da fiilen kullanılmıyor (%95,5 "Muhasebe Fişi");
  sınıflandırma Remark metni + hesap prefix'inden.
- **AccountingBalance / AccountingAmounts senkronu YOK** — biri kullanıcı-bazlı mizan cache'i,
  diğeri boş iç tablo; gerçek kaynak her zaman `AccountingTrans` aggregate'idir.

### Yol Haritası (inceleme raporundaki fazlar)

- **Faz A (UYGULANDI, 2026-07-11):** motor + Uyuşmayan Veriler + hesap eşleme + otomatik
  kapanma + bildirim + sedna_sync adımı + kur ALIŞ geçişi.
- **Faz B (UYGULANDI, 2026-07-11):** aylık değerleme raporu (bizim hesap ↔ Sedna Type=4 yan
  yana), `sedna_rec_id` kalıcı kimlikleri (cari/çek/satış), `event_matches`/`fx_differences`
  katmanı, korunan-kayıt `sedna_diff` sapmaları — yukarıdaki **Faz B** bölümü.
- **Faz C (açık):** cari↔Sedna mutabakat sekmesi, kredi/avans kod eşlemesi, dönem kilidi
  uyarı modu. Yıl devri (`Mhs2027`) tasarımı da açık. Muhasebe ekibine e-posta iletimi
  **kullanıcı kararı bekliyor**.
