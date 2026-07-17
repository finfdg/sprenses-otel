# Kontratlar (sales.kontratlar)

## Genel Bilgi

- **Modül kodu:** `sales.kontratlar` (modül id 925, üst modül: Satış/896)
- **Frontend rota:** `/dashboard/satis/acente-mahsup?tab=kontrat` (Acente Mahsup birleşik sayfasının sekmesi — sekme görünürlüğü bu modülün `view` iznine bağlı, sayfanın kendisi `sales.acente_mahsup`)
- **Backend prefix:** `/api/sales/kontratlar`
- **İzin:** `can_view` (görüntüleme + belge indirme) / `can_use` (CRUD + belge yükleme)
- **Tasarım kaynağı:** 2026-07-17 kontrat klasörü analizi (16 tur operatörü, 96 belge — rapor artifact'i) + kullanıcı kararları: kapsam 16 operatörün tamamı, veri girişi hem elle CRUD hem belge yükleme, #26 nakit akım varyantı (iii) tam ciro projeksiyonu (Faz 2)

## Amaç ve Kapsam (Faz 1)

Tur operatörü kontratlarının **arşiv + metadata** katmanı: sezon dönemleri, ödeme planları ve
taksitleri (nakit akımın kalbi), EB/SPO aksiyonları, kontenjan (allotment) ve kesinti
(kickback) kalemleri + belge arşivi. **Fiyat matrisi (contract_rates) ve çocuk politikası
tabloları BİLİNÇLİ ertelendi** — Faz 4 fiyat doğrulama motoru ile gelecek.

## Dosya Haritası

- Backend: `models/contract.py` (10 model + merkezi sabitler), `schemas/contract.py`,
  `services/contract_service.py` (D1-2 ORTAK service), `routers/sales/contracts.py`,
  `utils/approval_executor.py::_handle_sales_kontratlar`
- Frontend: `lib/components/sales/KontratlarPanel.svelte` (sekme paneli)
- Migration: `b7d2f4a8c1e6` (10 tablo + modül kaydı), `a1c4e7f9b2d5` (reservations.sedna_contrack_id + agency_code_overrides — Faz 0)
- Test: `tests/test_contracts.py` (CRUD + kind + RBAC + 2 uçtan-uca onay regresyonu)

## Veritabanı Şeması (10 tablo)

- **agency_contracts** — çapa: `agency_group_id` FK (tüzel kişi ayrımı GRUP değil KONTRAT
  düzeyinde: Odeon ≠ Coral aynı ODEON grubunda ayrı `legal_counterparty` ile). `code` unique
  (`ALLTOURS-S26`). `invoice_due_basis` + `invoice_due_days` 16 kontratın 10 farklı vade
  kuralını taşır (checkout/invoice_date/invoice_receipt/self_billing/before_checkin/
  first_friday_after_checkin). `fx_rule` kur maddesi (checkin_tcmb_buying çoğunlukta;
  Akdem checkout; Webres fixed_rate=60). `supersedes_contract_id` revizyon zinciri.
  `sedna_contrack_ids` JSON — Sedna Contrack.RecId eşlemesi (rezervasyon bağı).
  **`data_confidence`**: verified / scanned_approx / needs_confirmation — taranmış
  belgeden okunan değerler operatör teyidine dek yaklaşık kabul edilir.
- **contract_periods** — sezon fiyat dönemleri; aynı `code` ile birden çok satır olabilir
  (AllTours çift takvim bandı: P1 = 26.03–30.04 + 22.10–31.10).
- **contract_payment_plans** + **contract_installments** — 4 plan arketipi: `advance`
  (sabit tarihli büyük avans), `eb_prepayment` (EB booking-list ön ödemesi %25/%50/%90 —
  taksitte `percent` + `percent_basis`, amount null), `guarantee_check` (Odeon 8 çek,
  Webres), `invoice_terms` (yalnız ek şart varsa — gecikme faizi `late_interest`).
  Taksit: sabit `due_date`+`amount` VEYA olay bazlı; `is_conditional` (W2M %70 ciro şartı),
  `supersedes_installment_id` (addendum ile öne çekme), `bank_transaction_id` (Faz 2
  banka eşleşmesi). **Politika:** 2026+ vadeli taksitler `pending` girilir — vadesi
  geçmiş tahsil edilmemişleri görmek İSTENEN davranış (Faz 2'de runway overdue_income'a düşecek).
- **contract_actions** + **contract_action_tiers** — EB kademeleri ve SPO'lar; `basis`
  booking/stay (DerTour/Pegas Şubat 2026'da geçiş yaşadı), `combinable` operatör bazlı
  aritmetik (cumulative=Pegas toplanır / best_price=Coral-Odeon / non_combinable /
  kb_only), `supersedes_action_id` revize zinciri, tier = konaklama bandı + `%` veya
  sabit net fiyat.
- **contract_allotments** — kontenjan; `allotment_type` allot/guaranteed/free_sale +
  `guaranteed_share_percent` (AllTours %80 stop-sale'siz, Pegas %70 blokaj, Roket %70).
- **contract_deductions** — kesinti kalemleri; `applies` per_invoice/season_end/monthly,
  baremli kesintiler `tier_from/tier_to` ile ayrı satır (Odeon %5+%1+%1+3.000€+uçak %1–4,
  Fun&Sun %5/6/6,5). `agency_groups.kickback_percent`'in genellemesi — Faz 3 mutabakat
  hesaplayıcısının veri kaynağı.
- **contract_documents** — belge arşivi; `contract_id` NULLABLE (önce yükle sonra bağla),
  `agency_group_id` zorunlu. Dosyalar `backend/uploads/contract_files/` altında UUID adla.

## API

| Method | Path | İzin | Not |
|---|---|---|---|
| GET | `/sales/kontratlar/` | view | sayfalı; `group_id`/`season`/`status` filtreleri |
| GET | `/sales/kontratlar/summary` | view | stat kartları (aktif, bekleyen/30g/geciken taksit) |
| GET | `/sales/kontratlar/{id}` | view | iç içe tam detay |
| POST/PATCH/DELETE | `/sales/kontratlar[/{id}]` | use | onay akışlı; silme banka-eşleşmeli taksit varsa engellenir |
| POST | `/sales/kontratlar/{id}/children/{kind}` | use | kind: periods/room-types/plans/installments/actions/tiers/allotments/deductions; onay payload'ı `_kind`+`_contract_id` taşır |
| PATCH/DELETE | `/sales/kontratlar/children/{kind}/{child_id}` | use | onay payload'ı `_kind` taşır |
| POST | `/sales/kontratlar/documents` | use | multipart; `validate_upload_file` (pdf+excel); onay DIŞI (dosya istisnası) ama audit+broadcast'li |
| GET | `/sales/kontratlar/documents/{id}/download` | view | attachment |
| PATCH/DELETE | `/sales/kontratlar/documents/{id}` | use | metadata / silme (dosya diskten de silinir) |

## Onay Akışı

Kontrat ve TÜM alt varlık mutasyonları `check_approval("sales.kontratlar", ...)` ile
onaya düşebilir. Executor `_handle_sales_kontratlar`: payload'da `_kind` yoksa kontrat,
varsa alt varlık — `contract_service` fonksiyonları router ile ORTAK (D1-2). Onay
payload'ında tarihler string'e serileşir → `contract_service._coerce_date` normalize eder.
Regresyon testleri: `test_create_contract_via_approval_regression`,
`test_create_installment_via_approval_regression`.

## İş Kuralları / Kararlar

- **Neden `sales.acente_mahsup` değil ayrı modül kodu:** executor `_HANDLERS` modül koduna
  tek handler bağlar; `sales.acente_mahsup` RoomType CRUD'una bağlıydı — kontratlar aynı
  kodu kullansa onaylar oda tipi handler'ında patlar/yanlış uygulanırdı. Ayrı kod ayrıca
  kontratlara özel onay workflow'u tanımlamayı mümkün kılar.
- **Broadcast:** tüm mutasyonlar `BroadcastModule.KONTRATLAR` yayınlar (AST bekçisi
  `test_broadcast_guard` uyumlu); panel `useLiveRefetch(salesModules=['kontratlar'])` dinler.
- **kickback_percent ↔ contract_deductions:** `agency_groups.kickback_percent` kaba
  yaklaşım (Faz 0'da kontrat değerlerine çekildi); tam temsil deductions'ta. Faz 3
  hesaplayıcısı deductions'ı okuyacak; o zamana dek compute_settlement eski alanla çalışır.
- **Taranmış belge çelişkileri** (needs_confirmation işaretli): Pegas vade 28→elle 21,
  Akdem EB ödeme %50→elle %30 + sayfa içi tarih çelişkisi, Odeon allotman 75/77 (kontrat)
  vs 91 (protokol), W2M 88 vs 90 oda. Operatör teyidi alınana dek bu değerlerle hesap
  yapan her tüketici (Faz 2-4) confidence bayrağını dikkate almalı.
- **Yarı-otomatik PDF→metadata çıkarımı** (kullanıcı isteği "her ikisi de"): Faz 1'de
  belge YÜKLEME var, otomatik metadata çıkarımı YOK — ai.asistan tabanlı "öner→onayla"
  akışı ileriki faz adayı olarak not edildi.

## Faz Yol Haritası (2026-07-17 kullanıcı kararları)

1. ✅ Faz 0: veri düzeltmeleri + sedna_contrack_id + agency_code_overrides
2. ✅ Faz 1: bu modül (arşiv + metadata + CRUD + onay + sekme UI)
3. Faz 1b: 16 operatörün verisi seed (workflow ile çıkarımdan; belgeler arşive)
4. Faz 2: taksitler + **TAM CİRO projeksiyonu** (#26 karar: varyant iii) → finance_events
   + runway/eur_balances/t_account + banka eşleştirici + 4 vektörlü çift-sayım kural seti;
   Sedna 340 bakiyeleri İZLEME görünümü. SPO bantları doluluk/ciro grafiklerine overlay.
5. Faz 3: sezon sonu kickback/mutabakat hesaplayıcısı + allotment × doluluk.
6. Faz 4: fiyat doğrulama motoru (contract_rates + kombinasyon aritmetiği + oda eşleme).

## Denetim ve Düzeltmeler (2026-07-17, modul-denetci 7.5/10 → bulgular kapatıldı)

- **RBAC erişim kırığı (Yüksek):** tek-kod route guard, yalnız `sales.kontratlar` izni olan
  kullanıcıyı sayfadan atıyordu → `NavItem.altCodes` eklendi (`lib/config/navigation.ts`):
  acente-mahsup rotası `sales.acente_mahsup` VEYA `sales.kontratlar` ile geçer;
  sidebar görünürlüğü (`Sidebar.itemVisible`) ve `+layout` guard'ı
  (`requiredModulesForPath` — çoklu kod, OR) aynı konfigden beslenir. Sekme-gömülü
  yeni modüller için desen budur.
- **Üst-bağ değişmezliği (Orta):** `apply_child_update` artık `contract_id/plan_id/action_id`
  değişikliğini reddeder — kayıt başka kontrata/plana taşınamaz (sil + yeniden ekle).
  Test: `test_child_update_cannot_move_parent`.
- **Onay update/delete regresyonu (Orta):** `test_update_and_delete_via_approval_regression`
  — executor'ın kind=None/update ve kind=installments/delete dalları uçtan uca.
- **Belge çapraz tutarlılık (Orta):** yükleme + metadata PATCH'inde kontrat.grup ↔ belge.grup
  eşleşmesi zorunlu. Test: `test_document_group_contract_cross_check`.
- **Şema whitelist (Düşük):** `fx_rule`/`pricing_model`/`invoice_due_basis` pattern'li.
- **FileDropzone (Düşük):** `.xlsm` kaldırıldı, limit ipucu gerçek değerlerle (PDF 20 MB / Excel 10 MB).
- **BİLİNÇLİ uygulanmayan öneri:** `/summary` endpoint'ini dosya sonuna taşıma — FastAPI
  rota sırası gereği `/summary`, `/{contract_id}`'den ÖNCE tanımlı olmak zorunda
  (int path param "summary" string'ini 422'ye düşürür); taşınırsa endpoint kırılır.

## Faz 1b — Veri Yükleme (2026-07-17, TAMAMLANDI)

- **27 kontrat** seed edildi (16 operatör; workflow: 16 yazar + 16 doğrulayıcı ajan;
  kaynak: kontrat klasörü çıkarımları). Dönemler, ödeme planları/taksitler, EB/SPO
  aksiyonları + bantları, kontenjanlar, kesintiler dahil. Loader idempotent (kod bazlı
  skip): scratchpad `load_seeds.py`.
- **79 belge** arşivlendi (`uploads/contract_files/`, 175 MB) — klasör→grup eşlemeli,
  doc_type path'ten çıkarımlı, sezon path'inden kontrata bağlı. macOS kaynaklı NFD
  Unicode klasör adları (İrelsTravel, Roket Türkiye) NFC normalize edilerek çözüldü.
- **`sedna_contrack_ids` otomatik dolduruldu:** grup üyesi acentelerin rezervasyon
  Contrack'leri, checkin çoğunluğu + DAR-pencere tercihiyle (yıllık şemsiye kontratın
  sezon kontratlarını yutmasını önler) kontratlara atandı. YAKLAŞIKTIR — Faz 4'te
  rate-list bazında netleşir. Örn. ALLTOURS-S26→[2122,2123], ODEON-S26-CORAL→9 Contrack.
- **Taksit durumu politikası (uygulanan):** belge "ödendi" diyorsa paid; 2025 vadeli
  sabit avanslar paid varsayıldı; ardından **Sedna 340 `received` bakiyesi grup
  taksitlerine KRONOLOJİK mahsup edildi** — tam karşılanan pending → paid (notlu).
  Sonuç: AllTours 15.02/15.03/10.04/10.07 taksitleri paid (5,25M € received kanıtı),
  Odeon 8 çekin tümü paid (944k € received ≥ 800k). Webres 50k ve W2M 2. taksit
  340-bütçesini aşıyor ama belge/varsayım kanıtıyla paid bırakıldı (uyarı loglandı).
  Banka-işlem düzeyinde kesinleşme Faz 2 eşleştiricisinde.
- **Önemli konvansiyon — `guarantee_check` = GİDEN teminat:** tek guarantee_check planı
  Odeon'a verilen 2×24M TL ifa teminatı çekleridir (tahsil beklenmez, 31.10.2026 iade).
  `/summary` ve liste satırı bekleyen-taksit toplamları bu plan tipini ve kontrat para
  biriminden farklı taksitleri HARİÇ tutar (karışık PB tek sayıya indirgenmez; yalnız
  EUR toplanır). **Faz 2 gelir projeksiyonu da guarantee_check'i almayacak.**
- Canlı doğrulama (2026-07-17): aktif 27 kontrat · bekleyen 4,8M € (800k koşullu) ·
  30 gün içinde 500k · **vadesi geçmiş 800k / 3 taksit = W2M Şubat–Nisan** (muhtemel
  %70 performans şartı durdurması — ilk gerçek alacak-takip bulgusu, operatörle
  görüşülmeli).

## Faz 2 — Nakit Akım Entegrasyonu (2026-07-17, TAMAMLANDI)

`contract_projection_service` (okuma-anında, FE'siz) üç nakit tüketicisini besler;
4 vektörlü çift-sayım kural seti uygulandı; taksit↔banka otomatik eşleştirici
matching_service'e eklendi; SPO takvimi endpoint'i + panel bant görünümü canlıda.
Detay: `docs/modules/nakit-akim.md` "#26 KARARI KAPANDI" bölümü.

## Faz 3 — Kesinti Tahmini + Kontenjan Kullanımı (2026-07-17, TAMAMLANDI)

- `GET /sales/kontratlar/deductions-forecast?year=` — sezon sonu kickback/kesinti
  TAHMİNİ: kontrat cirosu (önce **Sedna Contrack eşlemeli** — aynı grubun iki kontratı
  birbirinin cirosunu saymaz; eşleme yoksa grup üyeleri + geçerlilik aralığı fallback)
  üzerine `contract_deductions` uygulanır (fatura-başı %, baremli sezon-sonu tier'lar,
  sabit tutarlar). Mutabakat masasına hazırlık — "beklenen vs operatör bildirimi".
- `GET /sales/kontratlar/allotment-usage?start&end` — günlük satılan oda vs kontenjan:
  ortalama/tepe kullanım %, aşım günleri, taahhüt eşiği (`guaranteed_share_percent`).
  Rezervasyon seçimi Contrack-öncelikli.
- UI: KontratlarPanel'de iki toggle bölüm (kesinti tablosu + kullanım çubuğu; kırmızı
  bar = kontenjan aşımı). Canlı ilk değerler (Tem-Ağu 2026): ODEON %76, ALLTOURS %74
  (200 oda, %80 taahhüt), NORDIC %50 (10 gün aşım), PEGAS %21.
- ODEON Contrack ayrımı elle netleştirildi: CORALTR contrack'leri (2147/2148) →
  ODEON-YEARLY-CORAL-IC; 7 uluslararası contrack → ODEON-S26 (kesinti/kontenjan sahibi);
  ratelist kontratı (ODEON-S26-CORAL) Faz 4'te kendi eşlemesini alacak (notlu).

## Faz 4a — Fiyat Doğrulama Altyapısı + Rate'siz Denetim Motoru (2026-07-17, TAMAMLANDI)

- **Tablolar** (migration `c9e1a3b5d7f2`): `contract_rates` (4 fiyat arketipi:
  base_price / multiplier / fixed_total; occupancy_code; market_scope) +
  `contract_child_policies`. CRUD kind'ları: `rates`, `child-policies` (onay akışlı).
- **`GET /sales/kontratlar/price-audit?start&end&tolerance=3`** — rate matrisi OLMADAN
  çalışan denetimler: (1) para birimi uyumsuzluğu, (2) dönem boşluğu (**kapsama
  korumalı**: dönem verisi sezonun <%70'ini kapsıyorsa atlanır — AllTours taranmış
  kontratında yalnız P1 bantları okunabilmişti, yanlış-pozitif önlenir),
  (3) min-stay ihlali, (4) Contrack-içi fiyat tutarlılığı (aynı dönem×oda×doluluk
  grubunda gecelik HAM fiyat — sözleşme PB, EUR çevrimi değil — medyandan sapma;
  büyükten küçüğe sıralı; EB kademeleri meşru sapma üretebilir, notlu).
  `rate_rows>0` olduğunda kontrat-fiyat kıyası bu motora eklenecek.
- Canlı ilk koşum (May–Eki 2026, 5.182 rezervasyon): 95 para birimi uyumsuzluğu
  (Webres EUR rezervasyonlar TL iç-pazar kontratında — EU protokolü ayrımı bilgisi),
  14 min-stay, 3.052 dönem-kontrolü düşük-kapsama nedeniyle atlandı.
- UI: KontratlarPanel "Fiyat/kural denetimi" toggle bölümü (rozet sayaçları + bulgu tablosu).

## Faz 4b — AÇIK: Rate Matrisi Veri Girişi

Rate listeleri çoğunlukla TARANMIŞ (16 kontrat × ~8 dönem × 7-12 oda × doluluk
kombinasyonu) — seed workflow'u fiyatları BİLİNÇLİ kopyalamadı (güvenilirlik).
Giriş yolları: (a) elle CRUD (`rates` kind), (b) ayrı okuma-workflow'u ile
data_confidence=scanned_approx işaretli toplu giriş + operatör teyidi. Rate'ler
girildikçe price-audit kontrat-fiyat kıyası otomatik devreye girer; aksiyon motoru
(kümüle/best-price aritmetiği, kontrat başına birim test) bu veriyle birlikte yazılmalı.
