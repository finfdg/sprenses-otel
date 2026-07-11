# Nakit Akım — Otomatik Eşleştirme + Gerçek Zamanlılık Denetimi (2026-07-11)

**Amaç:** Kullanıcı hedefi iki cümle: (1) *"Eşleştirmeler mümkün olduğunca otomatik olmalı"* — Sedna ileri tarihli tahminleri (kesin/tahmini) ile banka ekstresi gerçekleşmelerinin nakit akım tablosunda eşleştirilmesi; (2) *"Tüm veri çeken/bağlantılı modüller anlık güncellenebilir ve ekrana yansıyabilir olmalı."*

**Yöntem:** 10 ajanlık çok-aşamalı denetim (Workflow): 6 paralel keşif okuyucusu (eşleştirme mantığı, banka ekstresi hattı, Sedna importları, finance_events+WS backend, frontend WS kapsamı, projeksiyon/tüketim katmanı) → 3 tasarım lensi (eşleştirme motoru, gerçek zamanlılık, veri bütünlüğü/mutabakat) → 1 eksiklik denetçisi. Tüm bulgular dosya:satır kanıtlı, grep ile doğrulanmış.

---

## 1. Mevcut Durum — Güçlü Yanlar (korunacak temel)

- **Merkezi `finance_events` modeli** doğru kurulmuş: `is_matched`/`is_realized`/`matched_event_id` üçlüsüyle çift sayım tek yerden kontrol edilir (`models/finance_event.py:103-105`); nakit akım/runway/T-Hesap aynı kaynaktan okur.
- **4 skorlamalı otomatik matcher** tek serviste (`utils/matching_service.py`): çek (tutar birebir + vade ±10g + çek-no açıklama araması), kredi (vade ±3g + banka adı + para birimi; faiz+vergi ayrı satır için N-1 grup eşleşmesi :656-696), KK (maskeli PAN son-4 çıkarımı + ödeme penceresi + %2 tolerans), avans (acente adı token'ı + erken ödeme sınırı + virman dışlama). Ekstre yüklemesinde SAVEPOINT izolasyonuyla koşar — biri patlarsa diğerleri sürer (`bank_statement_import.py:392-398`).
- Kurallar canlı vakalarla rafine edilmiş; matcher davranışlarının bir kısmı regresyon testli (`test_banks_cc_match.py` 28 test, `test_advances.py` 7 senaryo).
- Eşleşme bozulma yolları temiz: `invalidate()` iki yönlü orphan temizliği (`finance_event_service.py:394-422`), `match_number` sequence + asla-tekrar-kullanılmaz audit kuralı.
- WS altyapısı olgun: tekil store + tipli event kataloğu + 500ms debounce'lu `broadcast_finance_update`; polling yok.

## 2. Bulgular — A) Otomatik Eşleştirme Delikleri

| # | Bulgu | Etki | Kanıt |
|---|---|---|---|
| A1 | **VakıfBank API senkronu 4 matcher'ı HİÇ tetiklemiyor** — yalnız ekstre-yükleme yolu tetikliyor; API'den gelen gerçekleşmeler tahminlerle eşleşmeden kalıyor | Yüksek | `vakifbank.py:127-182`'de `_match_*` referansı yok; matcher tek çağrı yeri `bank_statement_import.py:390-398` |
| A2 | **`match-vendor-tx` finance_events'i senkronlamıyor + `max()+1` match_number** — nakit akım FE'den okuduğu için eşleşme yansımıyor; sequence yerine max()+1 eşzamanlı çakışma + audit kuralı ihlali | Yüksek | `cash_flow/matching.py:40-95`, `:61-63` (kardeşleri `:158`, `:238-252` sync yapıyor) |
| A3 | **Cari↔banka için otomatik matcher yok** — hacimce en büyük kalem; geçiş Sedna import gecikmesine bağlı (FIFO kırpması yalnız cari import'la), aradaki pencerede tahmin+gerçekleşen çifte görünür | Yüksek | `matching_service.py` vendor_payment kapsamıyor; `sync_vendor_fifo.py:42` |
| A4 | **auto_tagger FE'ye sync_tag yazmıyor + yükleme akışına bağlı değil** — otomatik atanan kategori/cari nakit akımda görünmez (manuel yol sync_tag kullanır → iki yol tutarsız); auto-tag yalnız elle butonla koşuyor | Yüksek | `utils/auto_tagger.py` (0 sync_tag referansı); tetik: `nakit-akim/+page.svelte:332` → `transaction_tags.py:451-477` |
| A5 | Planlı giderler (vergi/maaş/SGK/kira) bankayla hiç otomatik eşleşmiyor; etiketleme scheduled_entry'yi kapatmıyor → çift sayım penceresi | Orta | `finance_event_service.py:342` (hep is_matched=False); `transaction_tags.py:37` |
| A6 | 1-N (tek EFT → çok çek) ve çek/avans kısmi/toleranslı eşleşme yok — masraf kesintili havale hiç eşleşmez, elle de bağlanamaz (kısmi yalnız KK'da) | Orta | `matching_service.py:339-343`, `:478`; kısmi: `cash_flow/matching.py:137-144` |
| A7 | Banka↔çek ve banka↔kredi **unmatch endpoint'i yok**; kredi N-1 grubunda yalnız ilk banka satırı iz alıyor | Orta | unmatch yalnız KK (`cash_flow/matching.py:305`) + cari (`cariler/matching.py:150-242`); grup izi `matching_service.py:675-692` |
| A8 | Otomatik eşleşmede öneri/onay katmanı yok — eşik üstü doğrudan uygulanır; yanlış-pozitifler canlı bulguyla yakalandı (KK 13→2, avans yanlış taksit); eşikler koda gömülü | Düşük | `matching_service.py:375/:512/:643` |
| A9 | Kredi/KK/avans için manuel "yeniden eşleştir" tetiği yok (yalnız çekte `/checks/match-bank`) | Orta | `checks.py:421` |

## 3. Bulgular — B) Gerçek Zamanlılık Delikleri

| # | Bulgu | Etki | Kanıt |
|---|---|---|---|
| B1 | **Sedna satış faturası / stok / rezervasyon importları HİÇ broadcast etmiyor** (bilinçli `broadcast: None`) — Sedna'dan veri çekilince hiçbir ekran tazelenmez | Kritik | `sedna_sync.py:48/50/52`; `sales/reservations/sedna_import.py:40`; `sales_invoices.py:322` |
| B2 | `match_credit_payment` ve `unmatch_cc_payment` broadcast'siz (kardeşleri yayınlıyor) | Yüksek | `cash_flow/matching.py:200`, `:305` |
| B3 | **Bütçe 6 mutasyon + onay.py 0 broadcast** — frontend `butce/+page.svelte:348` dinliyor ama event hiç üretilmiyor (ölü abonelik); hakediş `update_term` aynı | Yüksek | `butce.py:77-357`; `onay.py:235`; `hakedis.py:57` |
| B4 | **Satış Faturaları (FIFO) sayfası, Acente Mahsup ana sayfası ve Panel KPI'ları WS dinlemiyor** — tek-seferlik onMount, F5'e kadar bayat | Yüksek | `satis-faturalari/+page.svelte:124`; `acente-mahsup/+page.svelte` (yalnız gömülü ReservationsPanel:827 dinler); `dashboard/+page.svelte:75-196` |
| B5 | **Reconnect 10 denemede kalıcı pes ediyor**; canlandırma (`resetReconnect`) yalnız Mesajlaşma sayfasında — laptop uykusu/ağ kesintisi sonrası finans sayfaları sessizce ölü WS ile bayat çalışır | Yüksek | `websocket.svelte.ts:28,190,229`; `mesajlasma/+page.svelte:102` |
| B6 | Onay executor'dan uygulanan mutasyonlar gerçek modül event'ini üretmiyor (yalnız approval event'leri); sales room_types/agency_groups direkt yolu da broadcast'siz | Orta | `approval/requests.py:49-73`; `approval_executor.py` (0 broadcast); `sales/room_types.py:88/126/171` |
| B7 | Desen kaba tam-refetch: çoğu handler `module` alanına bakmadan komple reload → tek mutasyon tüm açık sayfalarda refetch fırtınası; 3 farklı echo-guard deseni, çoğu sayfada hiç yok (çift reload) | Orta | `cekler:280`, `krediler:719`, `avanslar:263`, `cariler:997` |
| B8 | Stok 4 sayfası + döviz paneli tamamen WS dışı; backend'de stok broadcast'i de yok | Orta | `stok/*/+page.svelte`, `doviz/+page.svelte:97` (0 onWsEvent) |
| B9 | Sedna sync-all tek bloklayan HTTP isteği — ilerleme yok, timeout riski; yayın en sonda toplu | Orta | `sedna_sync.py:119-138` |
| B10 | 7 Sedna adımından yalnız satış faturaları zamanlanmış (2 saatte bir); cari/çek/rezervasyon yalnız Topbar butonuyla; banka cron'ları (YKB/QNB/Garanti) yazılmış ama kimlik boş + timer'a bağlanmamış; VakıfBank sync'in frontend tetiği yok | Yüksek | `systemctl list-timers` (banka fetch yok); `grep 'finance/vakifbank' frontend/src` boş |

## 4. Bulgular — C) Veri Bütünlüğü / Tutarlılık

| # | Bulgu | Etki | Kanıt |
|---|---|---|---|
| C1 | **Kalıcı öteleme (deferral) EUR bakiye eğrisine yansımıyor** — ötelenen çek/taksit runway+T-Hesap'ta yeni, RunwayChart+PDF'te eski tarihte (sessiz drift) | Yüksek | `eur_balances.py:190,209-211,230` (payment_deferrals'a bakmaz) |
| C2 | "Bankadaki nakit EUR" 3 yerde 3 ayrı mantık (Panel KPI client-side yalnız TRY/EUR/USD; runway; eur_balances) — aynı ekranda farklı sayı olası | Orta | `dashboard/+page.svelte:90-96`; `runway.py:129-141`; `eur_balances.py:417-421` |
| C3 | T-Hesap ile eur_balances iki paralel toplama motoru — çift-sayım dışlama kuralları iki yerde tekrar | Orta | `t_account.py:186-201` vs `eur_balances.py:60-113,251-256` |
| C4 | Satış faturası/tahsilat importu insert-only — Sedna'da tutar düzeltmesi eski satırı bırakır → FIFO/hakediş/mahsup şişer (cari+çekte çözülen Sinyal A/B deseni burada yok) | Orta | `sales_invoices.py:113-150` |
| C5 | Banka hesabı silmede FE invalidate yok → orphan FE + "bankasız ödendi" kalan çek/taksit/avans | Orta | `bank_account_service.py:33-34`; `banks.py:213-238` |
| C6 | Ekstre bakiyesi vs sistem bakiyesi mutabakatı hiç yok; hash-seq tükenmesi satırı sessiz atlar; OCR sessiz boş döner; hesaba-özel upload IBAN/para birimi doğrulamasız | Orta | `bank_statement_import.py:299-306`; `bank_parser.py:190-191`; `banks.py:277-299` |
| C7 | Ekstre/tekil işlem DELETE endpoint'i yok — hatalı yükleme kalıcı kirletir (tek yol hesabı komple silmek, o da C5'e düşer) | Orta | `banks.py` (grep doğrulandı) |
| C8 | **Rezervasyon ileri cirosu finance_events dışında** — iki ayrı "nakit akım gerçeği": finans runway'i gelir tarafını görmüyor (gereksiz karamsar), satış projeksiyonu giderlerden habersiz | Yüksek | `reservation_service.py` + `routers/sales/` (0 finance_event çağrısı); `agency_settlement_service` okuma-anı |
| C9 | Rezervasyon EUR'u import-anı kuruyla donuyor; kur yoksa TL/USD rezervasyonun eur_total'ı sessizce 0 | Düşük | `reservation_service.py:100-105` |
| C10 | Tarih-kritik 4 uç naive `date.today()` — TZ drop-in'e örtük bağımlı (git'te değil) | Düşük | `t_account.py:183`, `runway.py:234`, `eur_balances.py:36`, `cc_projection_service.py:129` |

## 5. Bulgular — D) Kesişen Riskler (eksiklik denetçisi)

1. **Çapraz-para eşleştirme yapısal olarak yok:** EUR tahmin → TRY gerçekleşme (otelin en yaygın senaryosu) hiçbir matcher'da aday bile olamaz (çek `matching_service.py:333-343` birebir tutar; avans `:466-478` para birimi anahtarı; kredi `:635-636` currency eşitliği). Kur farkı hiçbir tabloya gelir/gider olarak yazılmıyor. Otomasyonu büyütmeden bu boyut tasarlanmalı.
2. **Onay akışı ↔ eşleştirme politikası tanımsız:** Çek durum değişikliği onaya tabi (`checks.py:392`) ama aynı sonucu üreten otomatik matcher (`matching_service.py:378-386`) ve TÜM manuel eşleştirme endpoint'leri (`cash_flow/matching.py`, `cariler/matching.py`, `transaction_tags.py` — 0 check_approval) onaysız. "Eşleştirme onaydan muaf mıdır" kararı verilip `docs/modules/onay-akisi.md`'ye yazılmalı; yoksa ileride eklenen onay kapısı otomasyonu 202'ye kilitler.
3. **Yarış koruması sıfır:** matcher'larda/manuel eşleştirmede `FOR UPDATE`/advisory lock yok; çift-atama koruması istek-içi bellek set'leri. Tetik sayısı artınca (API sync + cron + manuel) aynı çek iki banka satırına bağlanabilir; `Check.bank_transaction_id` üzerinde unique kısıt da yok.
4. **Test güvenlik ağı eksik:** `cash_flow/matching.py`'nin 4 endpoint'i tamamen testsiz; `_match_credits_to_bank` (N-1 grubu dahil) hiçbir testte çağrılmıyor. Bu koda dokunmadan önce mevcut davranış test altına alınmalı.
5. **Mobil/iPad boyutu:** Eşleştirme işçiliği fiilen iPad'de yapılıyor; nakit-akım sayfasında `<md` kart kırılımı/overflow-x yok. Yeni eşleştirme UI'ları (öneri kuyruğu vb.) tablet GEÇER/KALIR kriteriyle tasarlanmalı.

---

## 6. Yol Haritası

### Faz 0 — Kanıtlı hataları kapat (hepsi küçük/orta efor, hızlı kazanç)
1. **Matcher orkestratörü:** SAVEPOINT'li 4-matcher bloğunu `run_all_matchers(db, ...)` olarak servise çıkar; ekstre yolu + VakıfBank API sync + yeni `POST /cash-flow/rematch` endpoint'i (UI'da "Yeniden Eşleştir" butonu) aynı fonksiyonu çağırsın. (A1, A9)
2. **match-vendor-tx düzeltmesi:** `sync_tag` + `sync_vendor_finance_events` ekle; `max()+1` → `match_number_seq`. (A2)
3. **auto_tagger düzeltmesi:** category/vendor yazan noktalara `sync_tag`; auto-tag'i upload/API akışına bağla (matcher'lardan önce); `run_auto_match_vendors`'a broadcast. (A4)
4. **Broadcast delik-kapatma turu:** sedna_sync 3 adımı (SALES_INVOICES/STOK sabitleri + sales broadcast), `match_credit_payment` + `unmatch_cc_payment`, bütçe 6 mutasyon + `onay.py`, `hakedis.update_term`, sales room_types/agency_groups. Sabitler iki tarafta birebir (constants.py ↔ realtime.ts). (B1-B3, B6 direkt yol)
5. **Global reconnect:** `+layout.svelte`'e `online`/`visibilitychange` → `resetReconnect`; Topbar'a bağlantı göstergesi; sentetik yeniden yayına `synthetic: true` bayraklı `sales_updated`. (B5)
6. **Deferral → eur_balances:** öteleme haritasını çek/kredi/KK toplama döngüsüne uygula; runway↔eur-balances aynı ayı gösteren regresyon testi. (C1)
7. **Eşleştirme çekirdeğine test ağı:** 4 manuel endpoint + `_match_credits_to_bank` (N-1 dahil) mevcut davranış testleri — Faz 1 değişikliklerinin ön koşulu. (D4)

### Faz 1 — Otomatik eşleştirmeyi büyüt
8. **Cari↔banka matcher'ı** (`_match_vendors_to_bank`): avans matcher'ı şablon; tutar (FIFO kalanı) + vade penceresi + `_norm_tokens` cari adı kesişimi; eşleşince sync_tag + FIFO sync. (A3)
9. **İki-eşikli güven + öneri kuyruğu:** yüksek skor otomatik uygula (mevcut davranış), orta skor `match_suggestions`'a düş; nakit-akım sayfasında "Eşleşme Önerileri (N)" paneli (Onayla/Reddet, skor+gerekçe); eşikler tek sabit bloğunda/config'te. iPad-uyumlu tasarım. (A8, D5)
10. **Unmatch endpoint'leri** (banka↔çek, banka↔kredi) + kredi N-1 grubunda tüm satırlara ortak match_number izi. (A7)
11. **Planlı gider köprüsü:** etiketleme (Vergi/SGK/Personel/Kira) tek aday scheduled_entry'yi kapatsın (scheduled_service üzerinden); ikinci faz `_match_scheduled_to_bank`. (A5)
12. **Kısmi + 1-N:** önce manuel (paid_amount desenini çek/avansa genişlet, çoklu-kaynak payload), sonra otomatik (kredi grup deseni çeke uyarlanır; toleranslı adaylar öneri kuyruğuna). (A6)
13. **Çapraz-para tasarımı:** EUR tahmin ↔ TRY gerçekleşme için event-tarihi kuruyla beklenen-TL bandı + kur farkı kaydı (tasarım kararı gerektirir — aşağıda "karar gereken konular"). (D1)
14. **Öğrenen kurallar (P3):** accept/reject sinyalinden `learned_match_rules` (2+ onayda aktif, ret pasifleştirir); skorlamaya "+öğrenilmiş kural" bileşeni. ML'siz, dış servissiz.

### Faz 2 — Gerçek zamanlılığı yapısal hale getir
15. **after_commit sigortası:** FinanceEventService yazma yolları source_type→BroadcastModule haritasıyla pending set'e eklesin; `after_commit`'te mevcut debounce ile yayınla → FE yazan HER yol (router/executor/import/auto_tagger) otomatik broadcast. + AST bekçi testi (broadcast'siz finans mutasyonu listeler, whitelist'li). (B sınıfının kalıcı çözümü)
16. **`useLiveRefetch` composable'ı:** tipli abonelik + module filtresi + tek echo-guard deseni; Satış Faturaları, Acente Mahsup (3 panel), Panel KPI'ları bağlanır; kural olarak ui-kurallari.md + CLAUDE.md'ye eklenir. (B4, B7)
17. **Onay executor gerçek modül event'i** (module_code→broadcast eşlemesi; hook kabul edilirse kapsam daralır). (B6)
18. **Sedna sync arka plana + ilerleme:** 202 + `SEDNA_SYNC_PROGRESS` event'i (adım adım yayın; modül broadcast'i anında); cari/çek senkronuna satış-cron deseninde timer (sales-sync ile faz farklı — EC2 bellek koruması); Topbar'da "Son senkron: X önce" tazelik rozeti (24s+ amber). (B9, B10)
19. **Stok + döviz canlıya** (STOK broadcast sabiti + useLiveRefetch ile sayfa başına ~5 satır). (B8)
20. **WS izin filtresi (P3):** `send_to_module_viewers` — can_view kümesine hedefli yayın (refetch fırtınasını doğal daraltır). (B7 ölçek ayağı)

### Faz 3 — Mutabakat ve tek gerçek
21. **Yaşlanan eşleşmemişler raporu:** `GET /cash-flow/reconciliation/aging` + nakit-akımda StatCard + günlük timer'la bildirim (İstanbul-açık tarih). (mutabakatın erken uyarısı)
22. **Günlük banka mutabakatı:** ekstre son bakiyesi vs sistem türevi bakiye; hesap kartında Mutabık/Sapma rozeti; upload'a IBAN/para-birimi doğrulaması; ekstre/işlem geri-alma (DELETE) endpoint'leri. (C6, C7)
23. **Satış faturası bayat-satır süpürmesi** (cari Sinyal A/B deseni; 2 saatlik cron'da drift en hızlı burada birikiyor). (C4)
24. **Banka hesabı silmede FE invalidate + kaynak durum geri alma** (service katmanında tek yerden). (C5)
25. **Tahmin doğruluğu raporu:** matched çiftlerden cari/acente bazında medyan gün/tutar sapması; "payment_days'i X yap" önerisi (uygulama kullanıcı kararıyla). (tahminleri zamanla iyileştiren geri besleme)
26. **Rezervasyon gelirini finance_events'e taşı** (`reservation_income` source_type; acente-grubu×ay granülaritesi; avans eşleşince FIFO-kırpma deseniyle kalan güncellenir) → runway/T-Hesap kod değişikliği olmadan geliri görür; "iki nakit akım gerçeği" kapanır. Önce çift-sayım matrisi kullanıcıyla netleştirilmeli. (C8)
27. **eur_balances'ı FE'den okumaya geçir** (T-Hesap gibi) — çift motor (C3) ve deferral sınıfı sorunların kökten çözümü; davranış-eşitliği doğrulamasıyla ayrı iş.
28. **Yarış koruması:** matcher girişinde `SELECT ... FOR UPDATE SKIP LOCKED` / durum yeniden-doğrulama + `Check.bank_transaction_id` benzeri kolonlara partial unique index. Tetikler çoğalmadan (Faz 1 sonu) tamamlanmalı. (D3)

## 7. Karar Gerektiren Konular (kullanıcı kararı)

1. **Eşleştirme onay politikası:** Eşleştirme/unmatch endpoint'leri onay akışından **muaf mı** (dosya-yükleme istisnası sınıfı gibi)? Önerimiz: muaf + `docs/modules/onay-akisi.md`'ye kapsam listesi olarak yazılması; aksi durumda otomatik matcher'lar onay kapısına takılır.
2. **Çapraz-para kur farkı:** EUR tahmin TRY gerçekleşince aradaki kur farkı ayrı bir kalem (kur farkı gelir/gideri) olarak mı kaydedilsin, yoksa yalnız eşleşme mi kurulsun? Muhasebe tarafını etkiler.
3. **Rezervasyon-FE çift sayım matrisi:** İleri rezervasyon cirosu FE'ye taşınırken avans mahsubu/acente vadesi kuralları (hangi kalem hangisini kırpar) birlikte netleştirilmeli.

## 8. İzleme

- Bu rapor uygulandıkça maddeler işaretlenmeli; UI sapmaları `docs/ui-degisiklik-gunlugu.md` geleneğiyle izlenir.
- İlgili önceki denetimler: `2026-07-01-tam-modul-denetimi.md` (modül kuralları), `2026-07-05-v3-kurumsal-denetim.md` (altyapı).

---

## 9. Yeniden Değerlendirme (2026-07-11 gece — Sedna Mutabakat Faz A+B+C sonrası)

Bu rapor yazıldıktan sonra aynı gün ikinci raporun (Sedna mutabakat) üç fazı tamamen uygulandı.
28 madde + 3 karar, 4 paralel denetçiyle güncel koda karşı dosya:satır kanıtıyla yeniden doğrulandı.

### Durum özeti

| Durum | Maddeler |
|---|---|
| ✅ **YAPILDI** | **#23** satış faturası süpürmesi (Faz B tam aynalama, `_MIRROR_SWEEP_CAP`) · **Karar-2** çapraz-para kur farkı kaydı (`fx_differences` + `ledger_rate`, FE dışı) |
| 🟡 **KISMEN** | **#4** broadcast turu (SALES_INVOICES + RECON kapandı; stok/rezervasyon/bütçe/onay/hakediş/sales/2 matching endpoint'i açık) · **#9** öneri kuyruğu (`event_matches` `method='suggestion'` altyapısı hazır — ayrı `match_suggestions` tablosu artık GEREKSİZ; iş mantığı+UI açık) · **#13** çapraz-para (kur kaydı+alış hizası tamam; matcher'ların çapraz-para ADAY üretmesi açık) · **#25** tahmin doğruluğu (event_matches tahmin↔gerçekleşme çiftlerini artık saklıyor; rapor endpoint'i açık) · **Karar-1** (mutabakat modülü için belgelendi; eşleştirme endpoint'leri kapsam listesi onay-akisi.md'de hâlâ yok) |
| 🔴 **AÇIK** | Kalan 22 madde (Faz 0'ın 6'sı, Faz 1'in 5'i, Faz 2'nin 6'sı, Faz 3'ün 5'i) + Karar-3 |

### Mutabakat altyapısının getirdiği tasarım revizyonları

1. **#2 match-vendor-tx** genişledi: sequence + sync_tag + FIFO senkronuna ek, `event_matches`'e
   `method='manual'` iz yazılmalı — ama `finance_event_svc.match()` üzerinden DEĞİL (cari
   eşleştirmesi `is_matched`'ı değiştirmez kuralı korunur; doğrudan EventMatch kaydı).
2. **#9 öneri kuyruğu**: yeni tablo yerine `event_matches(method='suggestion', score=...)` kullanılır —
   Faz B şeması bunun için tasarlandı; kabul = method'u auto/manual'a çevirip match() çağırmak.
3. **#6 deferral-EUR**: kısa vadeli yama (deferral haritası) Faz 0'da kalır; kökten çözüm **#27**
   (eur_balances'ın FE'den okuması) Faz B'nin FE-otoritesi güçlendirmesiyle daha cazip — Faz 2'ye öne alındı.
4. **#1 orkestratör** daha da önemli: API-sync'te matcher koşmaması artık mutabakat ekranında da
   gürültü üretiyor (eşleşmeyen kalemler recon'a düşüyor); ayrıca `sedna_sync._STEPS` + `bank_recon`
   adımı hazır şablon.
5. **#28 yarış koruması**: orkestratör tetikleri çoğaltacağı için hafif kısmı (matcher girişinde durum
   yeniden-doğrulama) Faz 1 başına alınmalı.
6. **#18**: sync-all'a bank_recon 8. adımı eklendiğinden koşu süresi uzadı — arka plan + ilerleme ihtiyacı arttı.

### REVİZE FAZ 0 (uygulanacak sıra)

| # | İş | Not |
|---|---|---|
| R1 | `run_all_matchers` orkestratörü (utils/matching_service) + auto-tag'in akışa bağlanması + auto_tagger `sync_tag` düzeltmesi + `POST /cash-flow/rematch` + VakıfBank sync bağlantısı + UI "Yeniden Eşleştir" | Eski #1+#3 birleşik (aynı dosyalar) |
| R2 | match-vendor-tx: sequence + sync_tag + sync_vendor_finance_events + EventMatch 'manual' izi (is_matched'a dokunmadan) | Eski #2 genişletilmiş |
| R3 | Broadcast delik kapatma (küçülmüş kapsam): STOK sabiti + stok/rezervasyon adımları + tekil sedna-import'lar + match_credit_payment/unmatch_cc_payment + bütçe 6 + onay 4 + hakediş + sales CRUD 7 | Eski #4 kalanı |
| R4 | Global reconnect (+layout online/visibility → resetReconnect) + Topbar bağlantı göstergesi + synthetic sales_updated | Eski #5 |
| R5 | Deferral → eur_balances yaması + runway↔eur-balances regresyon testi | Eski #6 (kökten çözüm #27 Faz 2'de) |
| R6 | Eşleştirme çekirdeği test ağı: 4 manuel endpoint + `_match_credits_to_bank` (N-1) + rematch | Eski #7 |
| R7 | Karar-1 belgeleme: eşleştirme endpoint'leri onay-muafiyet kapsam listesi → docs/modules/onay-akisi.md | Doküman |

**Durum: REVİZE FAZ 0 (R1-R7) UYGULANDI (2026-07-11 gece).** Sıradaki: **Faz 1** — cari↔banka
matcher, iki-eşikli öneri paneli (`event_matches` üzerinde), unmatch endpoint'leri, planlı gider
köprüsü, kısmi/1-N eşleştirme, çapraz-para aday üretimi; başında hafif yarış koruması (matcher
girişinde durum yeniden-doğrulama).
