# `codex/acente-finans` Branch'i — Kod İnceleme Raporu

**Tarih:** 2026-09-01 · **İnceleyen:** Claude Fable 5.1 · **Kapsam:** `master..codex/acente-finans`
(27 commit, 59 dosya, +4.739 / −257 satır) · **Karşılaştırma tabanı:** `master` = `b412aa0~1`

---

## 0. Sonuç Özeti

Branch, 5 Ağustos – 31 Ağustos 2026 arasında biriken **yedi ayrı iş paketini** taşıyor:
yeni **Acente Finansal Takip** modülü, **Nakit Akım Grafiği**, ciro projeksiyonunun gün
hassasiyetli yeniden yazımı, GBP çapraz kur, banka hareket filtresi + ekstre mükerrer
düzeltmesi, Sedna mutabakat/etiketleme genişletmeleri ve cariler toplu talimat ekleme.

**Genel değerlendirme: kalite yüksek (≈ 8/10).** Tek-kaynak ilkesi (`bank_snapshot`,
`t_account`'tan import edilen dönüşüm kuralları), canlı vakalardan türetilmiş regresyon
testleri (441 test yeşil) ve modül dokümantasyonu güçlü. Kritik lint kapısı temiz.

Öne çıkan riskler:

| # | Önem | Bulgu |
|---|---|---|
| Y1 | Yüksek | Branch **master'a merge edilmemiş**; canlı sistem (API + frontend + DB migration'ları) bu branch'in checkout'undan koşuyor, `master` 27 commit geride |
| Y2 | Yüksek | `agency_groups.payment_alignment` **yalnız SQL ile ayarlanabiliyor** — API şeması, PATCH ucu ve UI'da alan yok (canlıda 3 grup elle set edilmiş) |
| O1 | Orta | Acente Finans'ta TL/USD tutarlar **bugünkü** EUR kuruyla çevriliyor; T-Hesap/runway/grafik **işlem tarihi** kurunu kullanıyor → aynı fatura iki ekranda farklı EUR |
| O2 | Orta | Doküman indeksleri güncellenmemiş: `docs/modules/README.md`, `docs/api-haritasi.md`, kök `CLAUDE.md` tablo/RBAC listeleri |
| O3 | Orta | Yeni rapor ucu `GET /sales/acente-finans/` cache'siz + hız sınırsız; adı→grup eşleşmesi her satırda yeniden hesaplanıyor (O(N_avans × N_cari)) |
| O4 | Orta | Sedna 340 snapshot yazımında `name`/`description`/`document_no` kolon uzunluğuna kırpılmıyor → uzun değer gelirse tüm tazeleme sessizce geri alınır |
| O5 | Orta | Sedna mutabakat Geçiş 4'te daha önce tüketilen banka satırı ikinci kez aday olabiliyor (teorik çift atama) |

Düşük önemli 9 bulgu (UI tasarım-sistemi sapmaları, sabit kullanımı, test boşlukları, lint
danışma uyarıları) §4.3'te.

> **Durum (2026-09-01, aynı gün):** **Y1 KAPANDI** — `master` branch'e hızlı-ileri alındı (`4482ba8`),
> checkout `master`, `origin/master` push edildi. **Y2 KAPANDI** — `payment_alignment` şema/PATCH/UI
> (Acente Ayarları modalı) + `agency_groups` mutasyonları `check_approval` kapsamına alındı
> (`services/agency_group_service` router+executor ortak; `_kind` ayrıştırıcılı executor). D4 (sabitler)
> de bu kapsamda kapandı. Detay: `backend/app/routers/sales/CLAUDE.md` "Acente Grupları — payment_alignment".
>
> **O1 KAPANDI** — akışlar hareket tarihindeki kurla (`utils/fx_rates.RateBook`, USD/GBP çapraz), açık alacak /
> avans havuzu bugünkü kurla; kur yoksa 0 + `skipped_no_rate` (UI notu). `CROSS_EUR_CURRENCIES` tek kaynak
> `utils/fx_rates`'e taşındı (`_helpers` re-export). O3'ün ad→grup memo'su da eklendi. **O2 KAPANDI** —
> `docs/modules/README.md`, `docs/api-haritasi.md` (acente-finans, chart, banka filtreleri), kök `CLAUDE.md`
> (tablo 86, RBAC Satış satırı, yapı ağacı) güncellendi. Detay: `docs/modules/acente-finans.md` "Kur Yöntemi".

---

## 1. Kapsam ve Yöntem

**Okunan:** `git diff master...HEAD` tamamı (6.371 satır) — backend router/servis/model/
migration, frontend bileşen/sayfa/store, testler, dokümanlar.

**Koşulan doğrulamalar:**

| Kontrol | Sonuç |
|---|---|
| `ruff check --select E9,F63,F7,F82` (CI kritik kapısı) | Temiz |
| pytest — branch'in dokunduğu 14 test dosyası + `test_approval_system` + `test_broadcast_guard` (`sprenses_test` DB) | **441 geçti**, 4 uyarı (SAWarning, önceden var), 140 sn |
| `alembic heads` / `alembic current` (canlı DB) | Tek head `f3c7a9b5d2e8`; canlı DB **head'de** (iki migration uygulanmış) |
| Canlı veri | `sales_advance_transactions` 79 satır; `payment_alignment ≠ friday` 3 grup (NORDIC=day_27, MUNFERIT=checkin, EXPEDIA=checkin) |
| Deploy tazeliği | API restart 19 Ağu 16:48 UTC — sonrası backend değişikliği net sıfır (`_helpers.py` 31 Ağu iki commit birbirini götürüyor); frontend build 31 Ağu 09:37 UTC, kaynaklardan yeni; `/api/health` 200 |
| Rol izin çakışması (`finance.cash_flow view` ⊄ `finance.banks view`?) | 12 rolün hepsinde iki izin birlikte → bugün fiili sızıntı yok |
| Denetim otomasyonu (`audit_automation_config.enabled`) | **Kapalı** (26 Tem'den beri) — ayrıca script master-dışı checkout'ta çalışmayı reddediyor |

**Koşulmayan:** `svelte-check` ve `vitest` (sunucuda 446 MB boş RAM; deploy bekçisi eşiğinin
altında — build zaten 31 Ağu'da başarılı olduğundan tip hatası beklenmiyor), canlı UI/tarayıcı
kontrolü, Sedna sorgusunun gerçek Sedna üzerinde koşturulması.

---

## 2. Değişiklik Envanteri

| Paket | Tarih | Dosyalar (öz) | Test |
|---|---|---|---|
| **A. Acente Finansal Takip** (yeni modül, GET-only) | 05–13 Ağu | `models/sales_invoice.py` (`SalesAdvanceTransaction`), migration `e6a1c4f8b2d7`, `utils/sedna_client.py:186` (340 hareket sorgusu), `routers/finance/sales_invoices.py:290` (snapshot tazeleme), `services/agency_finance_service.py` (387 satır), `routers/sales/agency_finance.py`, `satis/acente-finans/+page.svelte` (380 satır), `docs/modules/acente-finans.md` | `test_agency_finance.py` (6) |
| **B. Nakit Akım Grafiği** | 19–20 Ağu | `cash_flow/chart.py` (329 satır), `cash_flow/_helpers.py:265` `bank_snapshot`, `runway.py` (delege), `CashFlowChart.svelte` (704 satır), `stores/cashflow.svelte.ts:119` tekil-uçuş | `test_cash_flow_chart.py` (14 — tek-sayı kuralı 4 dönem) |
| **C. Ciro projeksiyonu yeniden yazımı** | 13–17 Ağu | `services/contract_projection_service.py` (+289/−~60): gün hassasiyetli acente bazlı seri, `payment_alignment` (friday/month_end/day_N/checkin), fatura evreni penceresi, `per_invoice` kesinti, grup bazlı kırpma; migration `f3c7a9b5d2e8`; `cron_sedna_sync.py` rezervasyon adımı | `test_contract_projection.py` (+9) , `test_faz2_realtime.py` (+1) |
| **D. GBP çapraz kur** | 14 Ağu | `_helpers.py:221` `CROSS_EUR_CURRENCIES`, `t_account.py`, `runway.py`, `eur_balances.py`, `bankalar/+page.svelte` (GBP seçeneği + `toEur`) | 4 test (t-account, runway ×2, eur_balances) |
| **E. Banka** | 05 Ağu, 31 Ağu | `banks.py:65` hesap/hareket filtresi (tarih + mutlak tutar), `bank_statement_import.py:257` `Counter` tabanlı mükerrer kontrolü, `bankalar/+page.svelte` filtre paneli | `test_finance.py` (+4), `test_bank_manual_transaction.py` (+1) |
| **F. Sedna & etiketleme** | 05–14 Ağu | `sedna_recon_service.py` (Geçiş 3 referanslı ücret+BSMV, Geçiş 4 tekrarlı %5 serisi, aktif-yıl penceresi), `sedna_tag_bridge.py` (100/101/159/602/780 + 120 alt-kırılımı), `auto_tagger.py:728` misafir havale eşleşmesi, `matching_service.py:151` oto-ödeme kısmi KK, `recurring_vendor_sync.py:59` kapanış toleransı | `test_sedna_recon.py` (+5), `test_sedna_tag_bridge.py` (+7), `test_auto_tagger.py` (+4), `test_banks_cc_match.py` (+3), `test_recurring_vendor_sync.py` (+1) |
| **G. Cariler toplu talimat** | 31 Ağu | `cariler/MonthlyBalances.svelte:158` FIFO kalan listesini talimat listesine ekleme (modal) | Yok (frontend) |

---

## 3. Bulgular

### 3.1 Yüksek

#### Y1 — Branch master'a merge edilmemiş; canlı bu branch'ten koşuyor

**Kanıt:** `git worktree list` → ana çalışma ağacı `/home/ec2-user/otel` **`codex/acente-finans`**
üzerinde; `git rev-list --left-right --count master...HEAD` → `0 27`. Canlı DB `alembic current`
= `f3c7a9b5d2e8` (branch'in ikinci migration'ı). API ve frontend servisleri bu ağaçtan koşuyor.

**Etki:**
- `master` artık **canlıyı temsil etmiyor**; bellekteki "canlı servisler master checkout'undan
  çalışır" kuralı fiilen bozulmuş. `master`'a checkout yapılırsa DB şeması kodun önünde kalır
  (`sales_advance_transactions` tablosu / `payment_alignment` kolonu model'de yok → ORM sorguları
  değil ama tersine: master kodu bu kolonları bilmez, sorun çıkmaz; ANCAK branch'e geri dönmeden
  `alembic downgrade` denenirse veri kaybı).
- Denetim otomasyonu (`cron_denetim_auto.py`) `master`'dan worktree açıp master'a merge+deploy
  eder; bugün **kapalı** ve script master-dışı checkout'u reddediyor (`cron_denetim_auto.py:607-624`)
  → açılırsa her koşu "checkout master'da değil" diye düşer.
- Stop hook'u branch'i push ediyor; GitHub'daki `master` 27 commit bayat.

**Öneri:** `master` sıfır commit ileride olduğundan hızlı-ileri merge risksiz:
`git checkout master && git merge --ff-only codex/acente-finans && git push`. Sonra branch
silinebilir. Bu, test/deploy/otomasyon varsayımlarını yeniden hizalar.

#### Y2 — `payment_alignment` yalnız veritabanından ayarlanabiliyor

**Kanıt:** `grep -rn payment_alignment app/routers app/schemas frontend/src` → **0 sonuç**.
`routers/sales/agency_groups.py:30` `AgencyGroupUpdate` yalnız `name/members/term_days/kickback_percent`;
`:43` `AgencyGroupResponse` alanı döndürmüyor. Canlıda üç grup (`NORDIC=day_27`,
`MUNFERIT=checkin`, `EXPEDIA=checkin`) doğrudan SQL ile set edilmiş.

**Etki:** Projeksiyonun en önemli davranış anahtarı (Cuma / ay sonu / ayın N'i / girişte)
kullanıcı tarafından görülemiyor ve değiştirilemiyor; audit log'suz, onay akışı dışı, yeni
acente eklenince varsayılan `friday` ile kalır. `docs/modules/nakit-akim.md` alanı belgeliyor ama
"nasıl ayarlanır" kısmı yok.

**Öneri:**
1. `AgencyGroupCreate/Update/Response`'a `payment_alignment: str` (regex
   `^(friday|month_end|checkin|day_([1-9]|[12][0-9]|3[01]))$`) ekle.
2. Acente Mahsup sayfasındaki grup formuna `Select` (Cuma / Ay sonu / Ayın N'i / Girişte) ekle.
3. `agency_groups` mutasyonları bugün `check_approval` çağırmıyor (branch dışı, önceden var) —
   alan eklenirken onay entegrasyonu da tamamlanmalı (executor `sales.acente_mahsup`
   `_make_crud_handler` yeni alanı otomatik geçirir mi doğrulanmalı).
4. Servis literalleri yerine `models/agency_group.py:12-19` sabitlerini kullan (bkz. D4).

### 3.2 Orta

#### O1 — Acente Finans kur tarihi yöntemi diğer görünümlerle tutarsız

**Kanıt:** `services/agency_finance_service.py:65-80` `_to_eur`: EUR kayıtta native tutar,
diğerlerinde `amount_tl / eur_rate` — `eur_rate` **bugünün** TCMB alış kuru (`_latest_rates`).
Buna karşılık `t_account._event_eur`, `runway._event_eur`, `chart` ve `eur_balances.to_eur`
kalemi **kendi tarihindeki** kurla çevirir.

**Canlı veri etkisi:** TL kayıtlar azımsanmayacak: 1.596 TL fatura (₺28,8M), 190 TL tahsilat
(₺14,5M), 23 TL avans hareketi (₺9,9M). Ocak'taki bir TL faturası bugünkü kurla ~%20–25 daha
düşük EUR gösterir; aynı fatura T-Hesap'ta işlem-tarihi kuruyla görünür → iki ekran farklı sayı.
USD 340 hareketleri de `received_tl / bugünkü EUR` yoluna düşer (çapraz kur değil).

**Öneri:** `ExchangeRate` listesini bir kez çekip `bisect` ile işlem-tarihi kuru kullan
(`eur_balances.get_eur` deseni); USD/GBP için `CROSS_EUR_CURRENCIES` çaprazı. Bilinçli olarak
"bugünkü değerleme" isteniyorsa bunu `docs/modules/acente-finans.md`'ye ve UI ipucuna açıkça yaz.

#### O2 — Doküman indeksleri güncellenmemiş

**Kanıt:** `grep -n "acente-finans|cash-flow/chart|sales_advance_transactions" docs/modules/README.md docs/api-haritasi.md CLAUDE.md` → **0 sonuç**.

Eksikler: (a) `docs/modules/README.md` modül→dosya tablosuna `acente-finans.md` satırı
(CLAUDE.md: "Yeni modül dokümanı eklendiğinde o tabloya satır ekle"); (b) `docs/api-haritasi.md`'ye
`GET /api/sales/acente-finans/`, `GET /api/finance/cash-flow/chart`, `GET /banks/accounts/`
ve `/transactions` yeni filtre parametreleri; (c) kök `CLAUDE.md` "Tablolar (85)" listesine
`sales_advance_transactions` (artık 86) ve RBAC "Satış" satırına Acente Finansal Takip sayfası;
(d) `docs/modules/nakit-akim.md`'de `payment_alignment`'ın nasıl set edildiği (Y2 çözülünce).

#### O3 — Rapor ucu koruma ve performans

**Kanıt:** `routers/sales/agency_finance.py:19` — limiter yok, cache yok. Servis her çağrıda
`SalesAdvanceTransaction` tamamı (`:155`), `SalesInvoice` tamamı (5.145 satır) ve
`Reservation`'ları çeker; `_match_advance_group` (`:95`) her avans satırı için tüm cari
token'larıyla skorlama yapar (aynı 340 adı için tekrar tekrar). Frontend `useLiveRefetch`
5 modülün her yayınında yeniden yükler. Emsal `acente_mahsup.py` 60 sn TTL cache kullanıyor.

**Etki:** Bugün 79 × 76 küçük; 340 hareketi yıl içinde büyüdükçe ve WS yayınları sıklaştıkça
maliyet artar; Sedna senkron yayını sırasında ardışık çağrılar birikir.

**Öneri:** ad→gid sonucu için sözlük memo; `(year)` anahtarlı 30–60 sn TTL cache
(`acente_mahsup`/`cc_projection` deseni) + `heavy_limiter`; ilk faz için yeterli.

#### O4 — Sedna snapshot yazımında uzunluk kırpması yok

**Kanıt:** `routers/finance/sales_invoices.py:296-309`: `code` `[:50]` kırpılıyor ama
`name` (String 300), `document_no` (String 60), `description` (String 300) kırpılmıyor.
Canlı max uzunluklar 67/38/4 → bugün risk yok.

**Etki:** Sedna'da tek bir uzun `Remark`/`Remark1` (ör. kopyala-yapıştır açıklama) gelirse
`DataError` → `except` bloğu tüm tazelemeyi geri alır ve yalnız `logger.warning` yazar; rapor
sessizce bayat kalır (`last_advance_sync_at` ilerlemez). `logger.warning` DBLogHandler'a
düşmez (ERROR eşiği) → `error_logs`'ta da görünmez.

**Öneri:** `[:300]`, `[:60]` kırpma + hata dalında `logger.error` (LOG-001 köprüsü yakalasın).

#### O5 — Mutabakat Geçiş 4'te tüketilen satır yeniden aday olabiliyor

**Kanıt:** `services/sedna_recon_service.py:310-347` — `keys` mutlak tutara göre sıralı;
bir çiftte `tax_group` olarak tüketilen `(gün, tutar)` grubu sonraki turda `main_group` olarak
tekrar ele alınıyor; `used_bank_ids` yalnız sonuç listesine uygulanıyor, aday seçiminde
denetlenmiyor. Aynı gün `a`, `0,05a`, `0,0025a` tutarlı eşit adette gruplar olursa `0,05a`
grubu iki kez eşlenir. Canlı olasılık düşük (üç kademe %5 zinciri).

**Öneri:** döngü başında `if any(id(b) in used_bank_ids for b in main_group): continue` ve
`tax_group` için aynı kontrol; `test_sedna_recon.py`'ye üç kademe senaryosu.

### 3.3 Düşük

| # | Bulgu | Kanıt | Öneri |
|---|---|---|---|
| D1 | Acente Finans sayfasında tasarım sistemi sapmaları: ham `<select>` ×2 (yıl, acente) — `Select.svelte` mevcut; `text-gray-400` gövde metni 6 yerde (AA kuralı: en açık ton `gray-500`) | `satis/acente-finans/+page.svelte:174,199` (select), `:268,289,303,308,311,344` | `Select` bileşeni; `gray-400` → `gray-500` |
| D2 | Bankalar filtre paneli: tutar girişi düz `Input type=text` — binlik ayraçlı "1.234,50" regex'e takılır; panel, kanonik iskelette (başlık → stat → filtre) değil, "Banka Hesapları" başlığının üstünde | `bankalar/+page.svelte:196,679-680` | Arama filtresi olduğu için `MoneyInput` zorunlu sayılmayabilir; en azından binlik ayracı kabul et (`replace(/\./g,'')` sonra `,`→`.`) |
| D3 | `date.today()` kullanımı (TZ drop-in'e bağımlı); router yılı İstanbul-açık alırken servis `date.today()` | `chart.py:161`, `agency_finance_service.py:125` (t_account.py:247 de aynı — tutarlı) | Tarih-kritik yeni kodda `datetime.now(tz_istanbul).date()` (CLAUDE.md tercihi) |
| D4 | `PAYMENT_ALIGN_*` sabitleri tanımlı ama servis literal kullanıyor (`"checkin"`, `"month_end"`, `"day_"`, `"friday"`) | `models/agency_group.py:12-19` ↔ `contract_projection_service.py:59-71,231,279` | Sabitleri import et; Y2'deki regex de sabitlerden türesin |
| D5 | Grafik `accounts` alanı `finance.cash_flow view` iznine hesap no + bakiye kırılımı açıyor; bugün her rolde `banks view` de var (12 rol) → fiili sızıntı yok | `chart.py:322`, `_helpers.py:265` | Roller ayrışırsa `accounts`'ı `user_can(banks, view)` şartına bağla |
| D6 | Test boşlukları: acente-finans ucu için 403 (yetkisiz rol) testi yok (chart'ta var); `_to_eur` TL/USD yolu test edilmiyor (tüm seed EUR); `bank_snapshot` kursuz/hareketsiz hesap dalı doğrudan test edilmiyor; geçmiş-yıl görünümü (`year < today.year`) senaryosu yok | `tests/test_agency_finance.py:208` | `no_perm_user_headers` ile 403; TL avans + TL fatura seed'i; `year=2025` senaryosu |
| D7 | Geçmiş yıl görünümünde `open_due/overdue` **bugünkü** açık durumu o yılın vade ayına yazar (yıl sonu durumu değil); önceki yıldan devir yalnız `year == today.year` iken Ocak'a düşer | `agency_finance_service.py:255-263` | Dokümana "açık/gecikmiş kolonları her zaman bugünkü durumu gösterir" notu |
| D8 | Lint (danışma seti): E741 `l` ×6 (`sedna_tag_bridge.py:117,120`, recon ×4), F401 ×5 (4'ü `bank_statement_import.py:33-36` önceden var, 1'i `recurring_vendor_sync.py:43`), I001 ×7 | `ruff check --statistics` | `ruff --fix` (I001/F401), `l` → `leg` |
| D9 | Mutabakat "aktif yıl" penceresi: Ocak başında tarama neredeyse boş; 30 Aralık banka ↔ 2 Ocak Sedna eşleşir (3 gün tampon) ama Aralık'ın **eşleşmeyen** kalemleri Ocak'ta raporlanmaz (tasarım gereği) | `sedna_recon_service.py:422-428` | Yıl devrinde (Mhs2027 geçişi) bir kez "önceki yıl" koşusu seçeneği |

**Branch dışı gözlem (önceden var):** `routers/sales/agency_groups.py` POST/PATCH/DELETE uçları
`check_approval` çağırmıyor — CLAUDE.md "tüm mutasyonlar onay kontrolünden geçer" kuralına aykırı.
Y2 çözülürken kapatılması uygun.

---

## 4. Güçlü Yönler

- **Tek-sayı disiplini:** Grafik dönüşüm/gruplama kurallarını `t_account`'tan import ediyor,
  kopyalamıyor; `bank_snapshot` runway/grafik/başlık için tek kaynak; `TestChartSingleNumberRule`
  4 dönem × 3 kova ile bunu kilitliyor. FIN-001 sınıfı drift'e karşı doğru yapı.
- **Canlı vakadan regresyon:** Her düzeltme gerçek olaya bağlı test taşıyor — 03.08 YK EUR
  iptal-tekrar (`Counter` dedup), YK *7261 oto-ödeme kısmi, 05.08 YKB 8×ücret+BSMV, Temmuz
  elektriği kapanış toleransı, Nordic %2 kesinti, Odeon avans havuzu.
- **Sedna snapshot güvenliği:** kaynak başarıyla çekilmeden mevcut snapshot silinmiyor
  (`fetch` → `delete` sırası); tünel kesintisi raporu boşaltmıyor.
- **WS/istek hijyeni:** `eur-balances` tekil-uçuş + kuyruk (`cashflow.svelte.ts:119`), grafik
  bileşeninde yankı koruması; polling yok, `useLiveRefetch` kullanımı kurala uygun.
- **Yetki/onay:** Yeni uçlar salt-okuma GET → `require_permission(view)` + onaydan muaf
  (doğru); ayrı RBAC kodu açılmayıp `sales.acente_mahsup` altında konsolide edilmesi tutarlı.
- **Dokümantasyon:** modül CLAUDE.md'leri ve `docs/modules/*` "neden böyle" gerekçeleriyle
  güncel; yalnız indeks dosyaları eksik (O2).
- **Güvenlik:** IBAN yalnız son 4 hane; filtre parametreleri tipli (`ge=0`, tarih); Sedna
  sorgusu parametresiz sabit SQL (enjeksiyon yüzeyi yok).

---

## 5. Önerilen Aksiyon Sırası

1. **Y1** — `master`'a fast-forward merge + push (5 dk, risksiz).
2. **Y2** — `payment_alignment` şema + PATCH + UI `Select` + onay entegrasyonu (agency_groups
   `check_approval` eksikliğiyle birlikte) + D4 sabitleri.
3. **O2** — README / api-haritası / kök CLAUDE.md indeksleri (15 dk).
4. **O4** — Snapshot kırpma + `logger.error` (10 dk).
5. **O1** — Kur tarihi kararı: işlem-tarihi kuru (önerilen) ya da "bugünkü değerleme" notu.
6. **O3** — TTL cache + limiter + ad→gid memo.
7. **O5, D1–D9** — fırsat buldukça.

---

## 6. CLAUDE.md Kural Uyumu — Kontrol Listesi

| Kural | Durum |
|---|---|
| Türkçe karakter (kullanıcıya görünen metin) | ✔ (yalnız `nakit-akim/+page.svelte` yorumunda ASCII — görünmez) |
| Python 3.9 (`Optional[...]`) | ✔ |
| `require_permission` | ✔ tüm yeni uçlar |
| `check_approval` + executor handler | ✔ (yeni uçlar GET-only; gerekmiyor) — branch dışı `agency_groups` eksik |
| Audit log | n/a (GET) |
| Polling yasağı / WS | ✔ `useLiveRefetch`, `onWsEvent` |
| Merkezi sabitler (WS/broadcast) | ✔ `BROADCAST_MODULE`, `WS_EVENT` — `PAYMENT_ALIGN_*` kullanılmıyor (D4) |
| Katman yönü (router→service→model) | ✔ `agency_finance_service` HTTP'siz; `chart`→`t_account` paket-içi |
| Pagination kuralı | n/a (12 ay × grup matrisi) |
| Migration (revize zinciri tek head) | ✔ |
| UI tasarım sistemi (PageHeader/StatCard/EmptyState/Skeleton/Lucide) | ✔ büyük ölçüde — D1/D2 sapmaları |
| Dosya-içi düzen (import → sabit → state → fn) | ✔ |
| Değişiklik dokümantasyonu | ✔ modül düzeyi / ✘ indeksler (O2) |
| Test: modül regresyonu | ✔ 441 yeşil; D6 boşlukları |
