# Sprenses API Haritası (Endpoint Kataloğu)

Sistemdeki tüm HTTP/WS endpoint'lerinin **referans kataloğu** — method · path · izin seviyesi · satır-içi iş-kuralı notları. Kök [`CLAUDE.md`](../CLAUDE.md)'den buraya taşındı (ana dosyayı yaşayan-kural odaklı + küçük tutmak için).

> **Drift uyarısı:** Bu katalog **elle** tutulur. Tek doğru kaynak **kod** (`backend/app/routers/`) + canlı **`/docs`** (FastAPI OpenAPI/Swagger). Endpoint ekler/değiştirirken bu dosyayı da güncelle ("Değişiklik Dokümantasyonu — Zorunlu" kuralı). Endpoint **tasarım kuralları** kök CLAUDE.md "API Endpoints" bölümündedir.

---

### Kimlik Doğrulama
- `POST /api/auth/login` — Giriş (rate limited: 5/dk)
- `GET /api/auth/me` — Mevcut kullanıcı bilgisi
- `POST /api/auth/change-password` — Şifre değiştirme (kendi şifresi)
- `POST /api/auth/logout` — Çıkış (cookie temizle + oturum sonlandır)
- `POST /api/auth/verify-email` — **PUBLIC** e-posta teyit bağlantısını doğrula (imzalı token; 400=geçersiz/süresi dolmuş/e-posta değişti). UI: `/eposta-teyit?token=…`
- **NOT:** Public self-service `POST /api/auth/register` **güvenlik nedeniyle kaldırıldı** (2026-06-19) — internete açık kayıt yetkisiz veri okuma yüzeyi yaratıyordu. Kullanıcılar yalnızca admin tarafından `POST /api/system/users/` ile oluşturulur.

### Sistem Yönetimi
- `GET/POST/PATCH/DELETE /api/system/users/` — Kullanıcı CRUD (paginated)
- `POST /api/system/users/{id}/reset-password` — Şifre sıfırlama (admin)
- `POST /api/system/users/{id}/send-verification` — E-posta teyit bağlantısı gönder (izin: `system.users` use; 400=e-posta yok, 503=SMTP kapalı; onaydan muaf)
- `GET/POST/PATCH/DELETE /api/system/roles/` — Rol CRUD (izin matrisi dahil)
- `GET/POST/PATCH/DELETE /api/system/modules/` — Modül CRUD
- `GET /api/system/modules/tree` — Modül ağacı (hiyerarşik)
- `GET /api/system/audit-logs/` — Audit logları (paginated, filtrelenebilir)

### Mesajlaşma
- `GET /api/messages/conversations` — Konuşma listesi
- `POST /api/messages/conversations` — Yeni konuşma başlat
- `GET /api/messages/conversations/{id}` — Konuşma mesajları
- `POST /api/messages/conversations/{id}` — Mesaj gönder
- `PATCH /api/messages/conversations/{id}/messages/{msg_id}` — Mesaj düzenle
- `DELETE /api/messages/conversations/{id}/messages/{msg_id}` — Mesaj sil (soft delete)
- `PATCH /api/messages/conversations/{id}/read` — Okundu olarak işaretle
- `GET /api/messages/unread-count` — Okunmamış mesaj sayısı
- `GET /api/messages/users` — Mesajlaşılabilir kullanıcı listesi

### Finans — Nakit Akım
- `GET /api/finance/cash-flow/` — Kayıt listesi (paginated, type/source/start_date/end_date/search filtresi)
- `GET /api/finance/cash-flow/mobile-dashboard` — Mobil dashboard özeti (banka bakiyeleri dahil)
- `GET /api/finance/cash-flow/summary` — Toplam gelir, gider, bakiye
- `GET /api/finance/cash-flow/monthly-summary` — Aylık gelir/gider/bakiye özeti
- `GET /api/finance/cash-flow/eur-balances` — EUR bakiye özeti (günlük/aylık gidere **tahmini KK ekstre rezervi** [cari ay limit] dahil — `due_reserve_projections`)
- `GET /api/finance/cash-flow/cc-projections` — Tahmini kredi kartı ekstresi kalemleri (view; yüklü ekstresi olmayan aylar için: **cari ay** = kart limiti [`total_amount`] worst-case rezerv, **ileri aylar** = 0 tutar/yalnız kesim+son-ödeme tarih göstergesi; kesim/son-ödeme günü en son yüklü ekstreden türetilir, yoksa `details`; yalnız aktif kartlar; 12 ay ufuk; okuma-anında, kalıcı FE yazmaz). Frontend nakit akım ay akordiyonuna karıştırır (`is_projected` kalemler, toplama DAHİL — kullanıcı kararı 2026-07-04). Detay: `docs/modules/nakit-akim.md`
- `GET /api/finance/cash-flow/report/pdf` — Ay/gün bazlı nakit akım PDF raporu (view; `start_date`/`end_date` opsiyonel; sayılar `compute_eur_balances` ile ekranla ortak)
- `GET /api/finance/cash-flow/t-account` — T hesap cetveli (view; `period=daily|weekly|monthly|yearly` + `offset<=0`; dönemin giriş/çıkış grupları EUR karşılığıyla, transfer kategorileri hariç, kur bulunamayan kalem `skipped_no_rate` sayacına düşer; **tahmini KK ekstre rezervi** [cari ay limit] ÇIKIŞ "KK Borç Ödemeleri" grubuna eklenir — `due_reserve_projections`; her grupta `section` faaliyet/finansman + yanıtta `faaliyet_net_eur`/`finansman_net_eur` — SALT yeniden-mercek, Net değişmez)
- `GET /api/finance/cash-flow/runway` — Nakit koruma / runway projeksiyonu (view; `runway_limiter` 30/dk — Beklet/Geri al + WS tazelemesi meşru sık trafik, 2026-07-07; içinde bulunulan ay için `start_eur` bugünkü toplam banka nakdi + bugün→ay sonu planlı [gerçekleşmemiş+eşleşmemiş] `inflows`/`outs` EUR kalemleri, transfer hariç, kur yok→`skipped_no_rate`; ayrıca `overdue` = vadesi geçen ödenmemiş kalemler orijinal tarihlerinde; her out/overdue/inflow kaleminde `deferred: bool` + `original_date`; **tahmini KK ekstre rezervi** [cari ay limit] `projected:true` OUT olarak eklenir — `due_reserve_projections`)
- `POST /api/finance/cash-flow/defer` — Bir ödeme kalemini KALICI öteler / öteleme kaldırır (use; onaysız+audit+WS; body `{source_type, source_id, deferred_to: "YYYY-MM-DD"|null}`; null→öteleme siler; `source_type` deferrable kümede [bank HARİÇ]; yanıt `{ok, deferred_to, cleared}`)
- `GET /api/finance/cash-flow/credit-payments-unpaid` — Ödenmemiş kredi taksitleri
- `GET /api/finance/cash-flow/cc-statements-unpaid` — Ödenmemiş kredi kartı ekstreleri
- `POST /api/finance/cash-flow/match-vendor-tx` — Cari işlem eşleştirme
- `POST /api/finance/cash-flow/match-cc-payment` — Kredi kartı ödeme eşleştirme
- `POST /api/finance/cash-flow/match-credit-payment` — Kredi taksit ödeme eşleştirme
- `POST /api/finance/cash-flow/unmatch-cc-payment` — Kredi kartı eşleştirme iptali
- `POST /api/finance/cash-flow/rematch` — Otomatik etiketleme + 5 eşleştiriciyi elle tetikler (use; ekstre yüklemesi/banka API senkronuyla AYNI orkestratör `run_post_ingest_processing`; onaydan MUAF — operasyonel eşleştirme, kapsam listesi `docs/modules/onay-akisi.md`; audit + BANKS/ADVANCES WS yayını; yanıt eşleşme sayaçları)
- `GET /api/finance/cash-flow/match-suggestions` — Eşleşme önerileri listesi (view; otomatik eşik altındaki en iyi adaylar `event_matches method='suggestion'`; skor sıralı, paginated `{items,total,page,page_size,pages}`; bantlar: çek 8-19 · kredi 20-39 · avans 8-19 · cari 50-79 · çapraz-para sabit 40; bayat öneriler her orkestratör koşusunda süpürülür — Faz 1, 2026-07-11)
- `POST /api/finance/cash-flow/match-suggestions/{id}/accept` — Öneriyi onayla (use; türe uygun `apply_*` / planlı giderde `close_entry_via_bank` ile gerçek eşleşme kurulur; hedef bu arada eşleşmiş/kapanmışsa 409 + öneri düşer; onaydan MUAF — kapsam listesi `docs/modules/onay-akisi.md`; audit + CASH_FLOW WS)
- `POST /api/finance/cash-flow/match-suggestions/{id}/reject` — Öneriyi reddet (use; öneri silinir — sonraki koşuda aynı çift yeniden önerilebilir; onaydan MUAF; audit + CASH_FLOW WS)
- `POST /api/finance/cash-flow/unmatch-check` — Banka↔çek eşleşmesini geri al (use; body `{check_id}`; çek `pending`'e döner, banka hareketi serbest kalır, `event_matches` izi silinir; onaydan MUAF; audit + CHECKS WS)
- `POST /api/finance/cash-flow/unmatch-credit-payment` — Banka↔kredi taksit eşleşmesini geri al (use; body `{payment_id}`; N-1 grupta `event_matches` izinden bağlı TÜM banka satırları çözülür + anapara `remaining_amount`'a iade edilir; banka FE'si realized kalır; onaydan MUAF; audit + CREDITS WS)
- `POST /api/finance/cash-flow/match-checks-batch` — Tek banka gideriyle birden çok çeki kapat (use; body `{bank_transaction_id, check_ids[]}` — 1-20 çek; toplam ±0.02 doğrulamalı, çeklerden biri bu arada eşleşirse 409; onaydan MUAF; audit + CHECKS WS)
- `GET /api/finance/cash-flow/reconciliation/aging` — Yaşlanan eşleşmemişler raporu (view; `?days=7` [1-180]; `stale_forecasts` = vadesi geçmiş açık tahminler kaynak-türü gruplu [FE `is_matched=F ∧ is_realized=F`, banka hariç] + `unmatched_bank` = etiketsiz/eşleşmesiz eski banka hareketleri; `compute_aging` çekirdeği cron günlük-özet bildirimiyle ORTAK — Faz 3 #21, 2026-07-12)
- `GET /api/finance/cash-flow/forecast-accuracy` — Tahmin doğruluğu raporu (view; `?months=6` [1-24]; `event_matches` izlerinden tahmin-tarih↔gerçekleşme sapması: tür bazında + cari bazında medyan/ortalama gecikme + `suggested_payment_days` [mevcut vade + medyan, |medyan|≥3 günse] — **YALNIZ öneri, otomatik ayar yok**; uygulama mevcut cari-vade PATCH'iyle elle — Faz 3 #25, 2026-07-12)
- Detaylı bilgi: `docs/modules/nakit-akim.md`

### Finans — Satış Faturaları (Otel oda satışları + tahsilat)
- `GET /api/finance/sales-invoices/` — Satış faturaları listesi (FIFO tahsil durumu; filtre: `customer_type` munferit/agency, `status` paid/partial/open, `start_date`/`end_date`/`search`, paginated). 120/Alıcılar = cariler'in (320) aynası
- `GET /api/finance/sales-invoices/summary` — Özet: toplam faturalanan/tahsil/açık + münferit/acente kırılımı + durum sayıları + **kullanılmamış net avans** bakiyesi
- `GET /api/finance/sales-invoices/advances` — **Acente avans bakiyeleri** (acentelerin yatırıp henüz fatura ile kapatmadığı net avans; yatırılan/kapanan/kalan). Acente avansı = 120 hesabına ALACAK, faturalarla (Borç) FIFO mahsup. Liste `by_advance` rozeti taşır
- `POST /api/finance/sales-invoices/sedna-import` — **Sedna'dan satış faturası + tahsilat içe aktarma** (120 Borç=fatura DocumentType=1, 120 Alacak=tahsilat; FIFO ile fatura bazında ödendi/kısmi/açık). finance.sales_invoices use, audit'li, onaydan muaf. Merkezi Sedna sync'in adımı. Detay: `docs/modules/satis-faturalari.md`

### Finans — Hak Ediş Takibi (acente fatura alacakları, 30/45 gün vade)
- `GET /api/finance/hakedis/` — Firma bazlı açık hak ediş + yaşlandırma kovaları + özet (vade = fatura + firma `term_days`; Sedna'da vade olmadığından yerel `receivable_terms`, varsayılan 30 gün). Aggregate — pagination yok
- `GET /api/finance/hakedis/firms/{customer_code}/invoices` — Firmanın açık/kısmi faturaları (vade, gecikme günü, kalan native+TL)
- `GET /api/finance/hakedis/firms/{customer_code}/collections` — Firmanın (veya `group-{id}`) tahsilat dökümü, yeniden eskiye (tarih, native+TL tutar, açıklama)
- `PATCH /api/finance/hakedis/terms/{customer_code}` — Firma vade tanımı upsert (0-365 gün) — finance.hakedis use, `check_approval` + audit. Detay: `docs/modules/hakedis.md`

### Finans — Sedna Senkronizasyonu (Merkezi)
- `POST /api/finance/sedna/sync-all` — **Tek noktadan tüm Sedna içe aktarmaları** (cari hareketleri + cari IBAN'ları + verilen çekler + **satış faturaları** + **stok/depo** + **otel rezervasyonları** + düzenli ödeme cari senkronu + banka↔Sedna mutabakatı). Topbar'daki tek "Sedna" butonu bunu çağırır. Her adım izin kontrollü (kullanıcının `use` izni olmayan adım "Yetki yok" atlanır), adım-bazlı izole (biri hata verirse diğerleri sürer). **Davranış değişikliği (Faz 2 #18, 2026-07-12): artık BLOKLAMAZ** — anında `{started: true, total, steps:[{key,label}]}` döner (izinli adımlar); adımlar arka plan işinde koşar, ilerleme adım adım **`sedna_sync_progress`** WS event'iyle yayınlanır (running/ok/error + koşu sonunda `{status:"done", ok_count, total, steps}`), her adımın modül broadcast'i **adım biter bitmez** gider. Sedna kapalıysa 503, hiçbir adıma yetki yoksa 403. Detay: `docs/modules/websocket.md`
- `GET /api/finance/sedna/status` — Merkezi sync etkin mi + kullanıcının çalıştırabileceği adımlar (buton gösterimi)
- `GET /api/finance/sedna/last-sync` — **Sedna verisi tazeliği** (Faz 2 #18): `{last_cari_sync, last_check_sync, last_bank_recon, oldest_hours}` — cari (`VendorUpload` `sedna://import`) + çek (`CheckUpload` `sedna://import`) son yükleme zamanları + son mutabakat koşusu (`sedna_recon_runs`); `oldest_hours` = kritik cari+çek adımlarının en eskisinin yaşı (saat). Topbar "Son: X sa önce" rozetini besler (>24 saat amber). Giriş yeterli (izin adımı yok — salt-okuma tazelik bilgisi)
- **Genişletme:** Yeni Sedna içe aktarma = `run_xxx_import(db, user, ip)` servis fonksiyonu yaz + `sedna_sync.py:_STEPS`'e ekle → Topbar butonu otomatik kapsar. **Sayfa-içi ayrı Sedna butonu eklenmez** (eski cariler/çekler kutuları kaldırıldı). Tekil endpoint'ler (`/cariler/sedna-import`, `/cariler/sedna-import-ibans`, `/checks/sedna-import`) orchestrator + hedefli kullanım için korunur.

### Finans — Cariler
- `POST /api/finance/cariler/upload` — Excel dosya yükleme (response içinde `removal_candidates` döner: kapsamda olup Excel'de bulunmayan kayıtlar)
- `POST /api/finance/cariler/sedna-import` — **Sedna (muhasebe SQL Server) doğrudan içe aktarma** (ters SSH tüneli `127.0.0.1:11433` üzerinden 320/satıcı cari hareketleri). Excel yükleme ile **aynı upsert + tx_hash dedup** → mükerrer olmaz. Yanıt Excel ile aynı (`removal_candidates` dahil). Tünel kapalıysa 503. finance.cariler use, audit'li, onaydan muaf
- `POST /api/finance/cariler/sedna-import-ibans` — **Sedna cari IBAN içe aktarma** (`dbo.Bank` → `vendor_bank_accounts`; cari koduna bağlı, firma başına çok IBAN). Yalnız mevcut carilere işler, dedup + ilk varsayılan + boş banka adını doldurur (idempotent). Ödeme talimatı IBAN'larını besler. finance.cariler use, audit'li, onaydan muaf
- `GET /api/finance/cariler/sedna-status` — Sedna içe aktarma etkin mi (`{configured}`; buton gösterimi). Detay: `docs/modules/cariler.md`
- `GET /api/finance/cariler/uploads` — Yükleme geçmişi
- `DELETE /api/finance/cariler/uploads/{id}` — Yükleme sil
- `POST /api/finance/cariler/transactions/bulk-delete` — Toplu işlem silme (kaynakta olmayan kayıtlar için; korumalı kayıtlar atlanır)
- `GET /api/finance/cariler/vendors` — Cari listesi (paginated, arama)
- `GET /api/finance/cariler/vendors` — Cari listesi (paginated, arama, `sort_by`/`sort_dir`, `hide_zero`, **`overdue_only`** = yalnız vadesi geçmiş eşleşmemiş faturalı cariler — master-detail "Vadesi Geçmiş" çipi)
- `GET /api/finance/cariler/vendors/{id}` — Cari detay + işlemler (+ `contact_person/phone/email` + özet metrikler `overdue`/`overdue_count`/`last_payment_amount`/`last_payment_date`)
- `PATCH /api/finance/cariler/vendors/{id}/contact` — **Firma iletişim** (yetkili/telefon/e-posta) güncelle. Finansal etkisi yok → **onaydan muaf** (use + audit + broadcast)
- `GET/POST /api/finance/cariler/vendors/{id}/notes` · `PATCH/DELETE /api/finance/cariler/vendors/{id}/notes/{note_id}` — **Cari notları** (görüşme/takip; ekle/düzenle/sil/`done` toggle). Onaydan muaf; use + audit (`vendor_note`) + broadcast
- `GET /api/finance/cariler/notes` — **Toplu firma notları** (tüm cariler tek listede, vendor join'li `vendor_name`/`vendor_code`; `done` + `search` filtreleri, paginated + `open_total`). Cariler sayfası "Notlar" sekmesi kartını besler; view yeterli
- `GET/POST/PATCH/DELETE /api/finance/cariler/vendors/{id}/bank-accounts[/{ba_id}]` — **Cari banka hesapları (IBAN)** — bir cari → 0..N IBAN; biri varsayılan. Sedna'da cari IBAN'ı boş olduğundan burada yönetilir; ödeme talimatında kullanılır. IBAN normalize + mükerrer 409 + varsayılan devri. finance.cariler use, audit'li
- `GET /api/finance/cariler/payment-schedule` — Haftalık ödeme planı
- Detaylı bilgi: `docs/modules/cariler.md`

### Finans — Ödeme Talimat Listeleri
- `GET/POST /api/finance/payment-instructions/` — Talimat listesi listele/oluştur
- `GET/PATCH/DELETE /api/finance/payment-instructions/{id}` — Liste detay/güncelle/sil
- `POST /api/finance/payment-instructions/{id}/items` — Cari kalem(ler) ekle (tutar bakiyeden gelir, mükerrer vendor atlanır; **carinin varsayılan banka/IBAN'ı otomatik gelir**, kalemde override edilebilir). Kalem `bank_name`+`iban` snapshot'ı taşır; PDF/Excel dökümünde **Banka + IBAN sütunları** yer alır
- `PATCH/DELETE /api/finance/payment-instructions/{id}/items/{item_id}` — Kalem tutarı güncelle / çıkar
- `GET /api/finance/payment-instructions/{id}/export/excel` — Excel dökümü (okunur liste)
- `GET /api/finance/payment-instructions/{id}/export/pdf` — PDF dökümü
- `GET /api/finance/payment-instructions/{id}/export/ykb-excel?debtor_account=` — **Yapı Kredi toplu ödeme** Excel'i (bankanın yükleme şablonu birebir: sayfa `ykb excel`, 11 kolon, IBAN boşluksuz, TUTAR düz ondalık, DÖVİZ=TL; BORÇLU HESAP = `debtor_account` param)
- Frontend: Cariler sayfasında "Ödeme Talimatı" sekmesi · İzin: `finance.cariler`
- Detaylı bilgi: `docs/modules/cariler.md` (Ödeme Talimat Listeleri bölümü)

### Finans — Onay (Departman Onay İş Akışı)
- `POST /api/finance/onay/assign/{vtx_id}` — Cari kaydına departman ata
- `GET /api/finance/onay/my-approvals` — Onay bekleyen kayıtlar
- `GET /api/finance/onay/pending-count` — Onay bekleyen sayısı (badge)
- `POST /api/finance/onay/approve/{vtx_id}` — Onayla
- `POST /api/finance/onay/reject/{vtx_id}` — Reddet
- `POST /api/finance/onay/remove/{vtx_id}` — Atamayı kaldır
- Detaylı bilgi: `docs/modules/onay.md`

### Muhasebe — Vergiler, Düzenli Ödemeler, Kiralar
- `GET/POST/PATCH/DELETE /api/accounting/taxes/` — Vergi tanım CRUD + giriş üretimi
- `PATCH /api/accounting/taxes/entries/{id}` — Vergi girişi güncelle (tutar, ödendi)
- `GET /api/accounting/taxes/summary/totals` — Vergi özeti
- `GET/POST/PATCH/DELETE /api/accounting/recurring/` — Düzenli ödeme CRUD (tanım `vendor_id` ile cariye bağlanabilir)
- `PATCH /api/accounting/recurring/entries/{id}` — Düzenli ödeme girişi güncelle
- `GET /api/accounting/recurring/summary/totals` — Düzenli ödeme özeti
- `POST /api/accounting/recurring/sync-vendors` — **Cari senkronu**: cari-bağlı kalemleri (Elektrik→CK, Su→ASAT) cari gerçek fatura + FIFO ödeme durumuyla senkronla. Faturası gelen ay tahmini→gerçek + recurring FE silinir (çift sayım önleme), gelecek aylar tahmini kalır. Merkezi Sedna butonu da çağırır (`recurring_sync` adımı). Detay: `docs/modules/muhasebe-ik.md`
- `GET/POST/PATCH/DELETE /api/accounting/rent-income/` — Alınan kira CRUD (gelir, direction=+1)
- `PATCH /api/accounting/rent-income/entries/{id}` — Alınan kira girişi güncelle
- `GET /api/accounting/rent-income/summary/totals` — Alınan kira özeti
- `GET/POST/PATCH/DELETE /api/accounting/rent-expense/` — Verilen kira CRUD (gider, direction=-1)
- `PATCH /api/accounting/rent-expense/entries/{id}` — Verilen kira girişi güncelle
- `GET /api/accounting/rent-expense/summary/totals` — Verilen kira özeti
- `GET/POST/PATCH/DELETE /api/accounting/dividend/` — Temettü tanım CRUD
- `PATCH /api/accounting/dividend/entries/{id}` — Temettü girişi güncelle
- `GET /api/accounting/dividend/summary/totals` — Temettü özeti
- Detaylı bilgi: `docs/modules/muhasebe-ik.md`

### Muhasebe — Kullanıcı Fiş İcmali (Sedna canlı)
- `GET /api/accounting/fis-icmali/summary?start_date&end_date&granularity&date_field` — **Sedna muhasebe fişlerini KESEN kullanıcıya göre gün/ay icmali** (kim ne zaman ne kadar fiş kesmiş). `AccountingOwner.RecordUser` + `Users` (ad); kullanıcı × dönem pivot. `granularity`=month|day, `date_field`=record (kayıt tarihi)|fiche (fiş tarihi). Canlı sorgu (model/import yok); ≤400 gün; tünel kapalı→503. accounting.fis_icmali view
- `GET /api/accounting/fis-icmali/vouchers?user_code&start_date&end_date&date_field` — **Drill-down:** bir kullanıcının aralıkta kestiği fişler (rec_id/no/tarih/tutar/açıklama)
- `GET /api/accounting/fis-icmali/voucher-detail?rec_id` — **Drill-down:** tek fişin muhasebe satırları (hesap kodu/adı, borç, alacak, toplam, kesen/değiştiren)
- `GET /api/accounting/fis-icmali/status` — Sedna etkin mi (`{configured}`)
- Detaylı bilgi: `docs/modules/fis-icmali.md`

### Muhasebe — Mizan (Geçici Mizan / Sedna canlı)
- `GET /api/accounting/mizan/summary?start_date&end_date&level&parent&search` — **Sedna hesaplarının dönem borç/alacak/bakiye mizanı** (kademe bazında: 1=ana hesap → alt hesap). `AccountingTrans` (borç/alacak) + `Accounting` (ad); leaf bazında çekilip kademe Python'da toplanır. `level`=kademe, `parent`=drill (alt hesaplar), `search`=Türkçe-duyarsız kod/ad. Yanıt `grand_total_borc/alacak` + `balanced` (denge: borç=alacak). Canlı sorgu (model/import yok); ≤800 gün; 60sn TTL cache; tünel kapalı→503. accounting.mizan view
- `GET /api/accounting/mizan/transactions?code&start_date&end_date` — **Drill-down:** hesabın (+ alt hesapları) hareketleri (defter) + yürüyen bakiye (ilk 1000)
- `GET /api/accounting/mizan/status` — Sedna etkin mi (`{configured}`)
- Detaylı bilgi: `docs/modules/mizan.md`

### Muhasebe — Sedna Mutabakat (Uyuşmayan Veriler / banka ↔ Sedna 102 defteri)
- `GET /api/accounting/mutabakat/summary` — Açık durum sayıları + en eski açık tarih + son koşu + hesap eşleme kapsamı + **`lock_date`** (Faz C dönem kilidi; yoksa null). accounting.mutabakat view
- `GET /api/accounting/mutabakat/items` — Uyuşmazlık listesi (**sayfalı** `page`/`page_size≤200`; `sort_by` **whitelist'li**: `event_date|amount|status|detected_at` + `sort_dir`; filtre: `status`, `account_id`, **`entity_type` `bank|check|vendor_tx|vendor_balance`** [Faz B — eşleşmiş çek/cari `sedna_diff` sapmaları; Faz C — cari `balance_diff` bakiye farkları; `bank` = entity_type'ı NULL banka satırları için takma değer], `include_closed`, `q`; yanıt satırında `entity_type`/`entity_id`). accounting.mutabakat view
- `POST /api/accounting/mutabakat/run` — Mutabakat taramasını elle tetikle (`window_days` 7–365, varsayılan 45; Sedna canlı sorgulanır, tünel kapalı→503). **Onaydan MUAF** — veri mutasyonu değil sınıflandırma (banka verisi HER ZAMAN otorite, motor banka satırını değiştirmez); audit + WS broadcast var. Merkezi Sedna sync'in `bank_recon` adımı da bunu çağırır. **Faz C:** cari bakiye taraması da best-effort koşulur → özete `vendors_scanned`/`balance_diffs`/`vendor_auto_closed` (hata halinde `vendor_error`) + `locked_period_new` (kilit-öncesi tarihli yeni uyuşmazlık) + `negative_balances` (KMH-harici mevduatta ters bakiye) eklenir. accounting.mutabakat use
- `PATCH /api/accounting/mutabakat/items/{id}` — Kaydı çöz/yoksay/yeniden aç (`action: resolve|ignore|reopen` + not). accounting.mutabakat use + **`check_approval`** (op=`resolve_item`; executor `_handle_accounting_mutabakat`)
- `GET /api/accounting/mutabakat/account-mappings` — Hesap eşleme durumu + **canlı Sedna** önerileri (102 leaf, Remark-numara + banka adı + para birimi skorlaması) — tünel kapalıysa **503 olabilir**. accounting.mutabakat view
- `PATCH /api/accounting/mutabakat/account-mappings/{account_id}` — Banka hesabına Sedna 102 kodu ata/onayla/temizle (`sedna_code_confirmed` insan onayı). accounting.mutabakat use + **`check_approval`** (op=`account_mapping`)
- `GET /api/accounting/mutabakat/fx-revaluation` — **Faz B (2026-07-11):** aylık kur değerlemesi raporu (`year`+`month`) — eşlenmiş döviz hesapları: bizim ay sonu bakiye × `ledger_rate` ↔ Sedna Type=4 değerleme fişi yan yana (`mutabik|sapma|sedna_bekliyor|veri_eksik`). **Salt rapor — deftere/finance_events'e YAZMAZ.** Sedna canlı → tünel kapalıysa 503. accounting.mutabakat view
- `GET /api/accounting/mutabakat/fx-differences` — **Faz B:** kur farkı kayıtları (Sedna 646/656 eşleniği; çapraz-para eşleşmelerden otomatik birikir, `amount_try` işaretli: +kar/−zarar). Sayfalı + `total_amount_try` genel toplam. accounting.mutabakat view
- `GET /api/accounting/mutabakat/credit-mappings` — **Faz C (2026-07-11):** kredi ürünleri ↔ Sedna **300** hesap eşleme durumu + **canlı öneriler** (banka adı +30 · para birimi +15 · kredi tutarı leaf adında +40; eşik ≥45) + `unmatched_sedna`. Tünel kapalıysa 503. accounting.mutabakat view
- `PATCH /api/accounting/mutabakat/credit-mappings/{product_id}` — Kredi ürününe Sedna 300 kodu ata/temizle (`sedna_account_code` unique; `300` öneki zorunlu, null=temizle). accounting.mutabakat use + **`check_approval`** (op=`credit_mapping`)
- `GET /api/accounting/mutabakat/agency-mappings` — **Faz C:** acente grupları ↔ Sedna **340** avans hesabı eşleme durumu + öneriler (grup adı/üyeleri token kesişimi; öneri LİSTE — acente başına para birimi ayrı hesap, ör. ANEX EUR≠USD). Tünel kapalıysa 503. accounting.mutabakat view
- `PATCH /api/accounting/mutabakat/agency-mappings/{group_id}` — Acente grubuna Sedna 340 kod **listesi** ata/temizle (`sedna_account_codes` JSON; `340` öneki zorunlu, boş=temizle). accounting.mutabakat use + **`check_approval`** (op=`agency_mapping`)
- `PATCH /api/accounting/mutabakat/period-lock` — **Faz C:** dönem kilidi tarihini ata/kaldır (`lock_date` ISO ya da null; **UYARI modu — senkronu bloklamaz**, kilit-öncesi yeni uyuşmazlık ayrı bildirilir). accounting.mutabakat use + **`check_approval`** (op=`period_lock`, entity_id=0)
- Detaylı bilgi: `docs/modules/sedna-mutabakat.md`

### İnsan Kaynakları — Maaş & Stopaj
- `GET/POST/PATCH/DELETE /api/hr/salary/` — Maaş tanım CRUD + giriş üretimi
- `PATCH /api/hr/salary/entries/{id}` — Maaş girişi güncelle
- `GET /api/hr/salary/summary/totals` — Maaş özeti
- `GET/POST/PATCH/DELETE /api/hr/withholding/` — Stopaj tanım CRUD
- `PATCH /api/hr/withholding/entries/{id}` — Stopaj girişi güncelle
- `GET /api/hr/withholding/summary/totals` — Stopaj özeti
- `GET/POST/PATCH/DELETE /api/hr/sgk/` — SGK tanım CRUD
- `PATCH /api/hr/sgk/entries/{id}` — SGK girişi güncelle
- `GET /api/hr/sgk/summary/totals` — SGK özeti
- Detaylı bilgi: `docs/modules/muhasebe-ik.md`

### İnsan Kaynakları — Devam Takip (PDKS)
- `GET /api/attendance/kiosk/qr?key=` — Girişteki ekranın dönen QR'ı (SVG, KIOSK_KEY gerekli; token panelden ayarlanan süre kadar geçerli)
- `GET /api/attendance/kiosk/config?key=` — Kiosk ekran yenileme süresi (KIOSK_KEY; ~15sn'de bir otomatik uyarlanır)
- `GET /api/attendance/kiosk/recent?key=` — Kiosk sağ paneli için son giriş/çıkış hareketleri (KIOSK_KEY)
- `GET /api/attendance/kiosk-link` — Kiosk ekranı linki (admin; KIOSK_KEY dahil)
- `GET/PATCH /api/attendance/settings` — QR yenileme süresi ayarı (hr.attendance; 2-120sn; geçerlilik=yenileme+3sn; panelden Ayarlar)
- `POST /api/attendance/setup` — Kişisel kurulum (enrollment): access_token ile **bu cihazı bağlar**, cihaza özel `device_token` döndürür (anti-buddy-punch). Zaten başka cihaza bağlıysa **409** → admin "Cihaz Sıfırla" gerekir
- `GET /api/attendance/pdks-manifest?t=` — Kişiye özel PWA manifest'i (public): "Ana Ekrana Ekle" ikonu kişisel basış sayfasını (token'lı start_url, standalone) açar — login'e değil. Global manifest `/devam`'da kullanılmaz; geçmiş silinse de token URL'de kalır
- `GET /api/attendance/me` — Personelin durumu (`X-Pdks-Device` başlığı)
- `POST /api/attendance/punch` — Giriş/çıkış kaydet (`X-Pdks-Device` cihaz token'ı + canlı kiosk token `k`)
- `POST /api/attendance/personnel/{id}/reset-device` — Bağlı cihazı çöz (hr.attendance use; audit'li) → yeni telefon/veri-silme sonrası tekrar kurulum için
- `GET/POST/PATCH/DELETE /api/attendance/personnel[/{id}]` — Personel CRUD (hr.attendance; sicil no=employee_code, departman, **görev**; liste `device_bound` durumu döner)
- `POST /api/attendance/personnel/import` — Excel sicil listesi içe aktar (Sicil No/Ad Soyad/Departman/Görev; upsert; .xls+.xlsx)
- `GET /api/attendance/personnel/{id}/qr` — Kişisel kurulum QR (kart)
- `GET /api/attendance/personnel/cards.pdf` — Tüm aktif personelin QR kartları tek PDF (yazdırılıp kesilebilir)
- `GET /api/attendance/status` — Şu an içeride kim
- `GET /api/attendance/logs` — Giriş/çıkış geçmişi (filtreli)
- `GET /api/attendance/summary?month=` — Aylık puantaj
- `POST /api/attendance/manual` — Yönetici elle giriş/çıkış (zaman seçilebilir; çift giriş/çıkış engelli; hr.attendance workflow'u varsa onaya düşer → `_handle_attendance` executor)
- `PATCH /api/attendance/logs/{id}` — Kaydı elle düzenle (tip/zaman/not; çift engelli; audit + onay)
- `DELETE /api/attendance/logs/{id}` — Kaydı sil (soft delete: deleted_at; Geçmiş'te soluk kalır, aktif hesaplara girmez; audit + onay)
- `GET /api/attendance/logs/{id}/history` — Kaydın değişiklik tarihçesi (audit) + bekleyen işlem
- `GET /api/attendance/pending` — Bekleyen onay talepleri (ekle/düzenle/sil; can_cancel)
- `POST /api/attendance/pending/{request_id}/cancel` — Kendi bekleyen talebini iptal (modül-içi)
- Gerçek zamanlı: basış/düzenleme/silme sonrası `attendance_updated`; onay verilince `approval_status_changed` → panel canlı tazelenir (polling yok)
- Public sayfalar: `/devam/ekran` (kiosk), `/devam/kur` (kurulum), `/devam` (basış)
- Detaylı bilgi: `docs/modules/devam-takip.md`

### İnsan Kaynakları — Vardiyalar (Shift)
- `GET /api/hr/shifts` — Vardiya tanımları (süre + gece/split bilgisi dahil)
- `POST /api/hr/shifts` — Yeni vardiya (ad, renk, başlangıç/bitiş, split 2. segment, açıklama; onay akışına tabi)
- `PATCH /api/hr/shifts/{id}` — Vardiya güncelle
- `DELETE /api/hr/shifts/{id}` — Vardiya sil
- Model: `shift_definitions` (start_time/end_time, split için start_time2/end_time2; gece vardiyası end<=start). Frontend: `/dashboard/ik/vardiyalar`. İzin: `hr.shifts`. Onay executor: `_handle_shifts`.

### İnsan Kaynakları — Vardiya Çizelgesi (Rota)
- `GET /api/hr/shift-schedule?start&end&department` — Aralık rota: aktif vardiyalar + aktif personel + atamalar + departman listesi (tek çağrı, ≤45 gün)
- `POST /api/hr/shift-schedule` — Tek hücre ata (upsert; `(personnel_id, work_date)` benzersiz) — onay akışına tabi
- `DELETE /api/hr/shift-schedule/{id}` — Hücreyi sil (çıkar) — onay akışına tabi
- `POST /api/hr/shift-schedule/bulk` — Toplu ata/temizle (`shift_id=null` → sil; ≤2000 hücre) — onaydan muaf (toplu işlem)
- `POST /api/hr/shift-schedule/copy-week` — Kaynak haftayı hedef haftaya kopyala — onaydan muaf
- Model: `shift_assignments` (personnel_id+shift_id+work_date; unique (personnel_id, work_date); CASCADE). Frontend: `/dashboard/ik/vardiya-cizelgesi` (haftalık grid + fırça boyama). İzin: `hr.shift_schedule`. Onay executor: `_handle_shift_schedule`. WS: `shift_schedule_updated`. Detay: `docs/modules/vardiyalar.md` (Rota bölümü)

### Finans — Bankalar
- `GET /api/finance/banks/accounts/` — Banka hesap listesi
- `POST /api/finance/banks/accounts/` — Banka hesabı oluştur
- `PATCH /api/finance/banks/accounts/{id}` — Banka hesabı güncelle
- `DELETE /api/finance/banks/accounts/{id}` — Banka hesabı sil (işlemlerinin TÜM eşleşme/FE temizliğiyle — `bank_release_service.delete_account_with_cleanup`; Faz 3 #24)
- `POST /api/finance/banks/upload` — Ekstre yükleme (otomatik tanıma — IBAN'dan hesap bulunur)
- `POST /api/finance/banks/accounts/{id}/upload` — Hesaba özel ekstre yükleme. **Faz 3 #22b:** ekstre başlığındaki IBAN/para birimi seçili hesapla uyuşmazsa **400** (yanlış hesaba sessiz yükleme kapandı; başlıkta bilgi yoksa doğrulama atlanır)
- `POST /api/finance/banks/accounts/{id}/manual-transaction` — Ekstre-dışı (manuel) hareket ekle (`source='manual'`; işaretli tutar; bakiye=son+tutar). İlgili ekstre yüklenince o tarih aralığında **otomatik silinir** → çift kayıt olmaz. finance.banks use, audit'li, onaydan muaf (özel/düzeltme endpoint'i)
- `GET /api/finance/banks/accounts/{id}/transactions` — Hesap işlemleri (yanıt `source` alanı döner: statement/manual)
- `GET /api/finance/banks/accounts/{id}/statements` — Ekstre listesi
- `DELETE /api/finance/banks/statements/{id}` — Ekstreyi + TÜM işlemlerini sil (use; her işlemin bağlı eşleşmeleri çözülür [çek→pending, taksit→unpaid+anapara iadesi, avans→pending, KK paid_amount geri, cari çifti] + FE invalidate — `bank_release_service.delete_bank_statement`; **onaya TABİ** [gerçek veri silme — eşleştirme muafiyeti DEĞİL]; audit + BANKS WS — Faz 3 #22c)
- `DELETE /api/finance/banks/transactions/{id}` — Tekil banka işlemini sil (use; **yalnız eşleşmemiş satır** — eşleşmişse 400 "önce eşleşmeyi geri alın" [bilinçli sürtünme]; **onaya TABİ**; audit + BANKS WS — Faz 3 #22c)
- Detaylı bilgi: `docs/modules/bankalar.md`

### Finans — Çekler
- `GET /api/finance/checks/` — Çek listesi (paginated, filtrelenebilir)
- `POST /api/finance/checks/upload` — Çek Excel yükleme
- `POST /api/finance/checks/sedna-import` — **Sedna (muhasebe SQL Server) verilen çek içe aktarma** (ters SSH tüneli; `AccCheckTrans`+`AccCheck` → **320 satıcı + 159 avans + 335 personel/ortak** verilen çekleri). Excel ile **aynı dedup** (check_no+vendor_code+currency+native tutar) → mükerrer olmaz. Durum Sedna pozisyonundan: Verilen Çek=bekliyor, Bankadan/Kasadan Ödeme=ödendi, Geri Al=iptal — eşleşmemiş çeklerde **durum + vade senkronize edilir**. **Tutar-kayması heal:** aynı (no,cari,vade) UNIQUE'inde tutarı bozuk eşleşmemiş kayıt Sedna'ya hizalanır (eşleşmişe dokunulmaz). finance.checks use, audit'li, onaydan muaf
- `GET /api/finance/checks/sedna-status` — Sedna çek içe aktarma etkin mi (`{configured}`; buton gösterimi)
- `GET /api/finance/checks/uploads` — Yükleme geçmişi
- `DELETE /api/finance/checks/uploads/{id}` — Yükleme sil
- `PATCH /api/finance/checks/{id}/status` — Çek durumu güncelle
- `GET /api/finance/checks/summary` — Çek özeti
- `POST /api/finance/checks/match-bank` — Otomatik banka eşleştirme
- `GET /api/finance/checks/number-anomalies` — Çek no ↔ açıklama-no uyuşmazlıkları (yalnız tespit)
- `GET /api/finance/checks/number-anomalies` — Olası çek-no giriş hataları (açıklamadaki no ≠ check_no; salt rapor)
- **Banka bilgisi:** çekin ödeneceği banka `checks.bank_name` (Sedna `AccCheck.Bank`); boşsa ardışık çek-no komşularından **tahmin** (`bank_name_inferred`, "~banka" rozeti) — Nakit Akım + Çekler'de gösterilir
- Detaylı bilgi: `docs/modules/cekler.md`

### Finans — Krediler
- `GET/POST /api/finance/krediler/` — Kredi ürünü listele/oluştur
- `GET/PATCH/DELETE /api/finance/krediler/{id}` — Kredi ürünü detay/güncelle/sil
- `POST /api/finance/krediler/{id}/payments` — Ödeme planı ekle (toplu)
- `PATCH /api/finance/krediler/payments/{id}` — Ödeme güncelle
- `DELETE /api/finance/krediler/payments/{id}` — Ödeme sil
- `POST /api/finance/krediler/{id}/close` — Krediyi kapat (erken tahsil; ödenmemiş taksitler nakit akımdan çıkar)
- `POST /api/finance/krediler/{id}/reopen` — Kapalı krediyi yeniden aç (geri al)
- `GET /api/finance/krediler/summary/by-type` — Tip bazlı kredi özeti
- `GET /api/finance/krediler/upcoming-payments` — Yaklaşan ödemeler
- `GET /api/finance/krediler/{id}/kmh-status` — KMH için anlık adat/faiz/projeksiyon (sadece type='kmh')
- `GET /api/finance/krediler/export/pdf` — Kredi PDF raporu (açılış + vade tarihleri dahil; tip/durum/arama filtreli; landscape A4, para-birimi-bazında toplam; EUR kredileri mavi vurgulu; ₺ sembolü DejaVuSans ile düzgün render)
- Detaylı bilgi: `docs/modules/krediler.md`

### Finans — Avanslar
- `GET/POST/PATCH/DELETE /api/finance/avanslar/` — Avans CRUD (elle/planlama; beklenen avanslar)
- `GET /api/finance/avanslar/summary` — Avans özeti
- `GET /api/finance/avanslar/sedna-reconciliation` — **Manuel avans ↔ Sedna mutabakatı**. Acente avansları Sedna'da **340 "Alınan Sipariş Avansları"** hesabındadır (159=bizim verdiğimiz; 320/120 ile karıştırma). **Faz C (2026-07-11): KOD-ÖNCELİKLİ eşleşme** — `agency_groups.sedna_account_codes` eşlemesi varsa (grup adı + üyeleri anahtar) deterministik eşleşir; kod yoksa eski ad-fuzzy (token + para birimi) fallback: manuel alınan vs Sedna alınan + kalan avans + fark + Sedna'da olup manuelde olmayan avanslar. Canlı 340 çekilir (tünel kapalıysa 503). Frontend: avanslar sayfasında "Sedna Mutabakatı" butonu. İlk canlı: Alltours manuel 4,75M € = Sedna 340 4,75M € (birebir)
- Detaylı bilgi: `docs/modules/avanslar.md`

### Finans — Döviz
- `GET /api/finance/exchange-rates/latest` — Güncel kurlar
- `GET /api/finance/exchange-rates/history` — Kur geçmişi
- Detaylı bilgi: `docs/modules/doviz.md`

### Finans — Bütçe
- `GET/POST/PATCH/DELETE /api/finance/butce/kategoriler` — Bütçe kategorisi CRUD
- `GET /api/finance/butce/` — Bütçe kayıtları (yıl zorunlu)
- `POST /api/finance/butce/` — Bütçe kaydı oluştur/güncelle (upsert)
- `POST /api/finance/butce/bulk` — Toplu bütçe kaydı
- `DELETE /api/finance/butce/{id}` — Bütçe kaydı sil
- `GET /api/finance/butce/summary` — Yıllık bütçe özeti
- `GET /api/finance/butce/monthly-summary` — Aylık bütçe özeti
- Detaylı bilgi: `docs/modules/butce.md`

### Finans — Departmanlar
- `GET/POST/PATCH/DELETE /api/finance/departmanlar/` — Departman CRUD


### Diğer
- `GET /api/health` — Sağlık kontrolü
- `WS /api/ws?token=JWT` — WebSocket bağlantısı
- `GET /api/push/vapid-key` — VAPID public key
- `POST /api/push/subscribe` — Push aboneliği
- `DELETE /api/push/unsubscribe` — Push abonelik iptali
- `GET /api/uploads/{path}` — Dosya sunma (auth gerekli)
- `GET /api/notifications/` — Bildirim listesi
- `PATCH /api/notifications/{id}/read` — Bildirimi okundu işaretle
- `GET /api/notifications/test-email/recipients` — Deneme alıcıları (aktif kullanıcılar; izin: `system.server` use)
- `POST /api/notifications/test-email` — SMTP deneme e-postası; body `{user_id?}` (verilirse o kullanıcının e-postasına, yoksa sistem kutusuna). İzin: `system.server` use; UI: Sistem→Sunucu; 503=SMTP kapalı, 502=gönderim hatası, 404=kullanıcı yok
- `GET /api/system/error-logs/` — Hata logları
- `GET /api/system/server/info` — Sunucu durumu (CPU/RAM/disk/servisler/DB boyutu)
- `POST /api/system/server/services/{name}/restart` — Servisi yeniden başlat (whitelist + sudo NOPASSWD)
- `GET /api/system/server/services/{name}/logs?lines=N` — Servis journalctl logu (son N satır)
- `GET /api/system/backup/status` — Git/GitHub yedek durumu (son commit, bekleyen değişiklik, senkron, geçmiş)
- `POST /api/system/backup/run` — Manuel yedek (commit + GitHub push)
- `POST /api/system/backup/restore` — Seçilen commit'e güvenli geri yükleme (ileri-commit, force-push yok). Detay: `docs/modules/yedekleme.md`

### Sistem — Dokümanlar (proje .md dokümanları — görüntüle/indir)
- `GET /api/system/docs/` — Doküman listesi (path, title, category, size, modified)
- `GET /api/system/docs/raw?path=` — Tek dokümanın ham markdown içeriği (panelde render)
- `GET /api/system/docs/download?path=` — Tek dokümanı `.md` indir
- `GET /api/system/docs/export/word` — **Tüm dokümanları tek `.docx`** üret + indir
- İzin `system.docs` view; salt-okunur (onay/audit kapsam dışı). Path traversal imkânsız (allowlist birebir eşleşme). Detay: `docs/modules/sistem-dokumanlar.md`

### Satış — Otel Rezervasyon
> **2026-07-09 birleştirme:** Tüm satış endpoint'lerinin izni artık **`sales.acente_mahsup`**'tur
> (eski `sales.hotel_reservation` / `sales.daily_reservations` / `sales.room_types` modülleri kaldırıldı;
> UI tek sayfada: `/dashboard/satis/acente-mahsup`). GET=view, mutasyon=use.
- `POST /api/sales/reservations/upload` — Crystal Reports XLS/XLSX yükleme (RecId bazlı upsert). Response'a `removal_candidates: RemovalCandidate[]` eklenir — yüklemenin check-in + record-date kapsamı içinde olup dosyada bulunmayan kayıtlar (olası iptaller)
- `GET /api/sales/reservations/uploads` — Yükleme geçmişi
- `DELETE /api/sales/reservations/uploads/{id}` — Yüklemeyi sil (rezervasyon satırları korunur, FK SET NULL)
- `POST /api/sales/reservations/bulk-delete` — `removal_candidates` listesinden seçilen ID'leri toplu sil (max 5000, audit loglu)
- `POST /api/sales/reservations/sedna-import` — **SednaPrenses önbüro/PMS DB'sinden canlı rezervasyon senkronu** (XLS'siz doluluk). `Reservation` join `Agency`; `RecId` aynı ID uzayı → mükerrer yapmaz. Pencere=cari yıl+; aktif (Status≠−1) upsert, iptal/silinmiş süpürülür → tablo Sedna aktif rezervasyonlarının aynası (`occupancy_metrics` aktif-yalnız değişmezliği). Merkezi Sedna sync'in adımı. sales.acente_mahsup use, audit'li, onaydan muaf. Detay: `docs/modules/otel-rezervasyon.md`
- `GET /api/sales/reservations/sedna-status` — Sedna rezervasyon senkronu etkin mi (`{configured}`)
- `GET /api/sales/reservations/` — Paginated liste (start_date, end_date, agency, nation, room_type, rez_status, search)
- `GET /api/sales/reservations/summary` — Dashboard KPI + dağılımlar + **doluluk metrikleri** (total_capacity, occupancy_pct, aylık/tip başına doluluk)
- `GET /api/sales/reservations/daily-occupancy?month=YYYY-MM` — Aylık drill-down: günlük doluluk + check-in/out sayıları (takvim heatmap için)
- `GET /api/sales/reservations/occupancy-overview?year=` — Doluluk sekmesi genel bakışı (2026-07-19): 12 ayın oda-gece toplamı gerçekleşen/ileri kırılımıyla (`past_nights`/`future_nights`, İstanbul-TZ bugün) + bugün/cari ay/yıl ortalaması chip verileri
- Detaylı bilgi: `docs/modules/otel-rezervasyon.md`

### Satış — Günlük Hareketler (gelen rezervasyon / iptal akışı)
- `GET /api/sales/daily-activity/summary?start_date&end_date` — **Gün gün gelen rezervasyon + iptal özeti** (adet/gece/misafir/EUR ciro, net, `cancel_rate`; hareketsiz günler 0'larla, en yeni üstte; ≤92 gün). **Sedna canlı** (Mizan/Fiş İcmali kalıbı): yerel tabloda iptal tarihçesi yoktur (senkron iptalleri siler) — `RecordDate` ekseni=gelen, `CancelDate` ekseni=iptal. 60sn TTL cache. sales.acente_mahsup view
- `GET /api/sales/daily-activity/details?activity_date&type=new|cancelled` — **Drill-down:** günün rezervasyon satırları (voucher/acente/ülke/oda/konaklama/pax/EUR; gelenlerde sonradan-iptal `is_cancelled` rozeti, iptallerde kayıt tarihi). **Misafir adı bilinçli yer almaz** (kişisel veri — Sedna sorgusu `Guests` kolonunu çekmez)
- `GET /api/sales/daily-activity/status` — Sedna etkin mi (`{configured}`); tünel kapalı→503
- Salt-okunur (yalnız GET) → onay akışı kapsam dışı. Detaylı bilgi: `docs/modules/gunluk-hareketler.md`

### Satış — Kontratlar (sales.kontratlar)

> Acente kontrat arşivi + metadata (16 tur operatörü). Mutasyonlar onay akışlı;
> alt varlıklar tek `kind` ucu (periods/room-types/plans/installments/actions/tiers/
> allotments/deductions). Detay: `docs/modules/kontratlar.md`.

- `GET /api/sales/kontratlar/` — Liste (sayfalı; `group_id`/`season`/`status` filtre) · view
- `GET /api/sales/kontratlar/summary` — Stat kartları (bekleyen/30 gün/geciken taksit) · view
- `GET /api/sales/kontratlar/{id}` — İç içe tam detay · view
- `POST /api/sales/kontratlar/` — Yeni kontrat · use + onay
- `PATCH /api/sales/kontratlar/{id}` — Güncelle · use + onay
- `DELETE /api/sales/kontratlar/{id}` — Sil (banka-eşleşmeli taksit varsa 400) · use + onay
- `POST /api/sales/kontratlar/{id}/children/{kind}` — Alt varlık ekle · use + onay (`_kind` payload)
- `PATCH /api/sales/kontratlar/children/{kind}/{child_id}` — Alt varlık güncelle · use + onay
- `DELETE /api/sales/kontratlar/children/{kind}/{child_id}` — Alt varlık sil · use + onay
- `POST /api/sales/kontratlar/documents` — Belge yükle (multipart, pdf+excel) · use (onay DIŞI — dosya istisnası)
- `GET /api/sales/kontratlar/documents/{id}/download` — Belge indir · view
- `PATCH /api/sales/kontratlar/documents/{id}` — Belge metadata · use
- `DELETE /api/sales/kontratlar/documents/{id}` — Belge sil · use

### Satış — Oda Tipleri
- `GET /api/sales/room-types/` — Oda tipi listesi + toplam kapasite (`total_capacity`)
- `GET /api/sales/room-types/{id}` — Tek kayıt
- `POST /api/sales/room-types/` — Yeni oda tipi
- `PATCH /api/sales/room-types/{id}` — Güncelle
- `DELETE /api/sales/room-types/{id}` — Sil (bağlı rezervasyon varsa engellenir; pasif yapma önerilir)
- Detaylı bilgi: `docs/modules/oda-tipleri.md`

### Satış — Acente Grupları
- `GET /api/sales/agency-groups/` — Grup listesi (üye acenteler dahil)
- `POST /api/sales/agency-groups/` — Yeni grup
- `PATCH /api/sales/agency-groups/{id}` — Grup adı / üyeleri + **`term_days` (vade) / `kickback_percent`** güncelle (Acente Mahsup konfigü)
- `DELETE /api/sales/agency-groups/{id}` — Grubu sil
- `POST /api/sales/agency-groups/assign` — Atomik atama (acente ↔ grup) — drag-drop için
- Detaylı bilgi: `docs/modules/otel-rezervasyon.md` (acente gruplama bölümü)

### Satış — Acente Mahsup & Nakit Akım (projeksiyon panosu — birleşik satış sayfasının projeksiyon sekmeleri)
- `GET /api/sales/acente-mahsup/` — Rezervasyon cirosu (EUR, çıkış ayında tanınır) + acente konfigü (vade/kickback) + gerçek avanslar → projeksiyon payload'ı; **2026-07-19 ekleri:** `cashflow.calendar` (Tahsilat Takvimi — 12 ay collected/overdue/pending + kümülatif + devreden) ve `overdue` (grup bazlı GERÇEK vadesi geçen alacaklar, hak ediş gecikmesinden EUR). Query: `year`, `year_target` (boş=gerçek), `opening_cash` — son ikisi artık UI'dan gönderilmez (geri-uyumlu). Salt-okuma (`sales.acente_mahsup` view), 60sn TTL cache, onaydan muaf. Hak Ediş'ten bağımsız ileri projeksiyon. Detay: `docs/modules/acente-mahsup.md`

### Finans — Banka Talimatları (PDF üretim)
- `POST /api/finance/bank-instructions/transfer` — EFT/Havale/Transfer PDF'i (kaynak/hedef hesap + tutar)
- `POST /api/finance/bank-instructions/currency-exchange` — Döviz bozma talimatı PDF'i
- `GET /api/finance/bank-instructions/accounts` — Aktif banka hesapları (PDF formunda dropdown için)
- Detaylı: `backend/app/routers/finance/CLAUDE.md` (Banka Talimatları bölümü)

### Finans — Etiketleme ve Kategoriler
- `GET /api/finance/tags/categories` — Kategori listesi (etiket havuzu)
- `POST /api/finance/tags/categories` — Yeni kategori
- `GET /api/finance/tags/payment-methods` — Standart ödeme yöntemleri haritası
- `GET /api/finance/tags/untagged-count` — Etiketlenmemiş işlem sayısı (badge)
- `PATCH /api/finance/tags/transactions/{tx_id}` — Tek işlemi etiketle (banka/cari/kategori)
- `POST /api/finance/tags/transactions/bulk` — Toplu etiketleme
- `POST /api/finance/tags/auto-tag` — Otomatik etiketleme (geçmiş eşleşmelere göre)
- `POST /api/finance/tags/auto-match-vendors` — Açıklamadan cari eşleştirme önerisi
- Detaylı: `docs/modules/transaction-tags.md`

### Sistem — Onay Akışı (Workflow Yönetimi)
- `GET /api/system/approval/modules-with-roles` — Onay tanımlanabilir modüller + roller
- `GET /api/system/approval/workflows` — Tüm workflow'lar
- `GET /api/system/approval/workflows/{id}` — Tek workflow
- `POST /api/system/approval/workflows` — Yeni workflow (modül + requestor rolleri + approver rolleri + adımlar)
- `PATCH /api/system/approval/workflows/{id}` — Workflow güncelle
- `DELETE /api/system/approval/workflows/{id}` — Workflow sil
- `GET /api/system/approval/requests/pending` — Onayım bekleyen talepler
- `GET /api/system/approval/requests/pending/count` — Bekleyen sayı (badge)
- `GET /api/system/approval/requests/my-submissions` — Kendi taleplerim
- `GET /api/system/approval/requests/history` — Onay geçmişi
- `GET /api/system/approval/requests/{id}` — Tek talep detayı
- `POST /api/system/approval/requests/{id}/approve` — Onayla
- `POST /api/system/approval/requests/{id}/reject` — Reddet
- `POST /api/system/approval/requests/{id}/return` — İade et
- `POST /api/system/approval/requests/{id}/cancel` — Kendi talebimi iptal
- `POST /api/system/approval/requests/{id}/resubmit` — İade edilenı tekrar gönder
- `POST /api/system/approval/trigger` — Internal: modüllerin `check_approval()` tetiklediği endpoint
- `POST /api/system/approval/status/bulk` — Toplu durum sorgu
- `GET /api/system/approval/status/{entity_type}/{entity_id}` — Tek kaydın onay durumu

### Stok / Depo (Maliyet Kontrol) — prefix `/api/stok`
- `GET /sedna-status` — Sedna stok içe aktarma etkin mi (`{configured}`)
- `POST /sedna-import` — **Sedna depo/stok hareketleri içe aktarma** (ürün + depo + hareket; stok.maliyet use, audit'li, onaydan muaf — Sedna import)
- `GET /summary` — Stok özeti (ürün/depo/hareket sayıları, toplam değer)
- `GET /cost-by-department` — Departman bazlı tüketim maliyeti
- `GET /monthly-trend` — Aylık tüketim trendi
- `GET /by-supplier` — Tedarikçi bazlı kırılım
- `GET /operational-kpi` — Operasyonel KPI (kişi başı maliyet, CPOR, devir hızı, fire % — doluluk füzyonu)
- `GET /price-variance` — Fiyat sapması (son alımlar vs ortalama)
- `GET /products` — Ürün listesi (anlık stok)
- `GET /movements` — Stok hareketleri (filtreli)
- `GET /depots` — Depolar
- `GET /product-purchases/{product_id}` — Ürün alım geçmişi (tedarikçi/fiyat)
- `GET /product-purchases/{product_id}/pdf` — Ürün alım geçmişi PDF
- Salt-okuma GET'ler + tek Sedna-import mutasyonu → onay akışı kapsam dışı. Detay: `docs/modules/stok.md`

