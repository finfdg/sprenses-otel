# Sprenses ERP — v3 Kurumsal Kod Denetimi

## §0 — Denetim Kimliği ve Kapsam

| Alan | Değer |
|---|---|
| **Denetim tarihi** | 2026-07-05 |
| **Denetçi** | Claude Opus 4.8 — çok-ajanlı orkestrasyon (16 denetçi + boyut-başına bağımsız 2. göz doğrulaması) |
| **Denetlenen sürüm** | git `126b92f` · branch `master` |
| **Şablon** | Kurumsal Kod Denetim Şablonu **v3** (23 boyut, 18 çıktı) |
| **Kapsam** | `backend/` (FastAPI, 235 py / 40.7k LOC / 96 router / 20 service / 45 model / 88 migration) + `frontend/` (SvelteKit, 105 svelte / 37.9k LOC) + altyapı (EC2/systemd/nginx/yedek) + docs. Test: 1232 backend fn / 305 frontend it. |
| **Bilinçli hariç** | Paralel bir oturumda **`quality`(kalite) + `flights`(uçak) modülleri siliniyor** → bu ikisinin yarım-silme artıkları kapsam dışı. |
| **Örnekleme** | Kritik yollar (finans, auth, DR, sunucu) **%100** derin okuma; kalan boyutlar hedefli örneklem + kanıt (`dosya:satır`). |
| **Önceki denetim referansı** | 2026-06-21 v2 teknik denetim (**72/100**, 15 boyut, tek Kritik = "otomatik DB yedeği yok"). 2026-06-19 kod denetimi (~7.8/10). 2026-07-01 tam modül denetimi (156 bulgu). |
| **Kalite süreci** | Her Kritik/Yüksek bulgu bağımsız 2. gözle çekişmeli teyit edildi → **~10 şişirilmiş bulgu doğrulamada düşürüldü/çürütüldü** (aşağıda işaretli), böylece bu rapordaki her Kritik/Yüksek koddan/canlı-sistemden doğrulanmıştır. |

---

## Yönetici Özeti

**Genel Not: ≈ 62 / 100** (bağımlılık azaltıldığında hedef **≈ 80**).

Sprenses, **ürün/uygulama katmanında gerçekten üst-çeyrek** bir ERP'dir: mimari katmanlama (router→service→model tek yön), onay/dual-write ortak-service deseni, güvenlik temelleri (HttpOnly cookie, tek-oturum, RBAC), finansal mutabakat çekirdeği (idempotent `finance_events`, para-birimi-ayrık FIFO) ve frontend tasarım sistemi olgun ve **koddan doğrulandı** (CLAUDE.md iddiaları körü körüne kabul edilmedi). Bu boyutlar 7–8/10.

Notu sınırlayan, **operasyon/uyum/platform katmanıdır** — 2026-06-21'de saptanan desenin devamı, ama artık daha derin mercekle:

- **Bimodal profil:** Çekirdek ürün katmanı (güvenlik, finans, mimari, DB, frontend, performans) **≈ 7.4/10**; operasyon/uyum katmanı (CI-gating, observability/alerting, DR-derinliği, KVKK, 3rd-party dayanıklılık) **≈ 4.5/10**.
- **06-21 ile karşılaştırma:** O denetimin **tek Kritik'i (DB yedeği yok) ÇÖZÜLMÜŞ** — günlük `pg_dump -Fc` fiilen çalışıyor (son 15 gün kesintisiz). Ancak daha derin DR incelemesi **iki yeni Kritik** ortaya çıkardı (yedek yalnız DB'yi ve yalnız aynı diski kapsıyor). Headline'ın 72→62'ye inmesi **regresyon değil**, ilk kez puanlanan KVKK (3.5), observability/alerting (3.5) ve DR/finans derinliğinin etkisidir.

**En büyük tek risk:** İşletme sürekliliği — birbirini pekiştiren **3 Kritik** (TLS ~12 günde bitiyor; yüklenen dosyalar hiçbir yedekte değil; off-site yok + tek EBS). Bir disk/instance kaybı veya sertifika bitişi bugün kurtarılamaz veri/erişim kaybı yaratır.

**İyi haber:** Kritiklerin hepsi **düşük eforlu, altyapı-seviyesi** düzeltmelerdir (kod değil). İlk hafta ~1 günde kapatılabilir (bkz. Quick Wins).

---

## Çıktı 16 — Skor Panosu (23 boyut · önceki → şimdi → 90g hedef)

| # | Boyut | 06-21 | **v3 (şimdi)** | 90g hedef | Not |
|---|---|:--:|:--:|:--:|---|
| 1 | Mimari & Modülerlik | 7.5 | **7** | 8 | Katmanlama olgun; dev frontend dosyaları |
| 2 | Kod Kalitesi | 7.5 | **7** | 8 | Lint/type CI-gate yok |
| 3 | Güvenlik | 8.5 | **7.5** | 8.5 | Auth sağlam; dosya-IDOR |
| 4 | Performans | 7.8 | **7** | 8 | async-blocking noktaları |
| 5 | Stabilite | 7.5 | **7** | 7.5 | Global handler var; dönem-kilidi yok |
| 6 | Veritabanı | 7.5 | **7** | 8 | tx_hash UNIQUE eksik (satış) |
| 7 | API | 7.0 | **6** | 7.5 | response_model %12; kontrat zayıf |
| 8 | Frontend & Mobil | 8.0 | **7** | 8 | E2E yok; fieldErrors tutarsız |
| 9 | Test Kapsamı | 7.0 | **7** | 8 | parser'lar testsiz |
| 10 | Test Süreçleri | 7.5 | **7** | 8 | freezegun yok; PII fixture |
| 11 | CI/CD | 5.5 | **4** | 7 | merge-gate DEĞİL |
| 12 | Loglama | 6.5 | **5** | 7 | structured/correlation yok |
| 13 | Dokümantasyon | — | **7** | 8 | zengin; drift otomasyonu yok |
| 14 | Ölçeklenebilirlik | 5.5 | **5** | 6 | in-memory state, tek-worker |
| 15 | Teknik Borç / Bus factor | 5.5 | **5** | 7 | bus factor=1, runbook yok |
| 16 | Yedekleme & DR | Kritik | **5** | 8 | DB yedeği ✔; uploads/off-site ✗ |
| 17 | Gözlemlenebilirlik | — | **3.5** | 7 | APM/alerting yok |
| 18 | KVKK / Gizlilik | — | **3.5** | 6 | envanter/retention/rıza yok |
| 19 | 3rd-Party Dayanıklılık | — | **4** | 6.5 | retry/circuit-breaker yok |
| 20 | Finansal Doğruluk | — | **7** | 8.5 | çekirdek sağlam; dönem-kilidi/FX |
| 21 | Arka Plan İşleri | — | **6** | 7.5 | başarısızlık görünürlüğü yok |
| 22 | Sunucu & Ortam | — | **6** | 8 | TLS renewal KAPALI (Kritik) |
| 23 | Zaman & Türkçe | — | **5** | 7 | process TZ ayarsız; C.UTF-8 |

> **Katmanlı okuma:** Çekirdek (1-10,20) ort. **≈7.1** — 06-21 ile aynı seviye (kod katmanı korundu). Operasyon/uyum (11,14-19,22-23) ort. **≈4.7** — notu çeken bu. Aynı ekip aynı diskte iki farklı olgunluk seviyesi işletiyor.

---

## Çıktı 6+8 — Kritik ve Yüksek Bulgular (çekişmeli doğrulanmış)

### 🔴 KRİTİK (3)

```
[SRV-001] TLS sertifikası otomatik yenilemesi devre dışı — sertifika ~12 günde bitiyor
Dosya   : sistem — certbot-renew.timer (etc/letsencrypt/renewal/sprenses.com.conf)
Kanıt   : certbot-renew.timer inactive/yok; renewal cron/timer yok → sprenses.com sertifikası
          yenilenmiyor. Bitince TÜM site (HTTPS+API+WS) TARAYICIDA ERİŞİLEMEZ olur.
Risk    : Kritik — belirli tarihte tam kesinti (kullanıcı hatası değil, zamanlı bomba)
Çözüm   : systemctl enable --now certbot-renew.timer (veya cron 'certbot renew --deploy-hook
          "nginx -s reload"'); bitişe X gün kala alarm (efor: S)
Kapanış : certbot-renew.timer aktif + bir kuru-çalıştırma (renew --dry-run) başarılı + bitiş izleme
Durum   : Açık | 2. göz: ✔ CONFIRMED
```
```
[DR-001] uploads/ (yüklenen dosyalar) HİÇBİR yedekte yok — DB geri yüklense bile dosyalar kalıcı kaybolur
Dosya   : .gitignore:44 (backend/uploads/* git-dışı) · scripts/db-backup.sh:36 (yalnız pg_dump)
Kanıt   : uploads/ = 91 MB / 1448 dosya (banka ekstreleri, cari Excel, çek/rezervasyon PDF).
          db-backup.sh yalnız pg_dump çalıştırır; DB'de 546+ satır (bank_statements 340 /
          check_uploads 97 / vendor_uploads 109) diskteki gerçek dosyalara işaret eder →
          disk kaybında her file_url dangling, mali belge kaybı. (= DOCS-006)
Risk    : Kritik — geri-getirilemez mali belge kaybı
Çözüm   : db-backup.sh'e 'tar czf uploads-<ts>.tgz backend/uploads' (aynı rotasyon+bütünlük+
          off-site) VEYA EBS snapshot; restore tatbikatına dosya-varlık kontrolü (efor: M)
Kapanış : uploads/ günlük yedeğe girer, off-site kopyalanır, tatbikat örnek dosyayı doğrular
Durum   : Açık | 2. göz: ✔ CONFIRMED
```
```
[DR-002] Off-site (S3) yedek PASİF + tek EBS = tek nokta arıza (DB+uploads+yedekler aynı diskte)
Dosya   : docs/modules/yedekleme.md:19 · scripts/db-backup.sh:51-57 (S3 yalnız env set ise)
Kanıt   : EC2'de IAM role yok (aws sts → "Unable to locate credentials"), Environment= boş →
          S3 bloğu hiç çalışmıyor. lsblk: tek nvme0n1 30G '/' altında DB (/var/lib/pgsql) +
          uploads + yedeklerin kendisi (/var/backups/sprenses-db) → birim/instance/ransomware
          kaybı üç kopyayı BİRDEN götürür. (SRV-003 aynı kök)
Risk    : Kritik — tek olayda tüm veri + tüm yedek kaybı
Çözüm   : yedekleme.md runbook'unu uygula — S3 (versioning+SSE+public-block, farklı bölge) +
          minimal IAM role + enable-offsite-backup.sh; en az DB dump + uploads off-site (efor: M)
Kapanış : Günlük DB+uploads farklı bölgedeki S3'e otomatik yükleniyor, S3'ten restore 1 kez doğrulandı
Durum   : Açık | 2. göz: ✔ CONFIRMED
```

### 🟠 YÜKSEK (11 — birleştirilmiş)

| ID | Başlık | Dosya:satır | Efor | Doğrulama |
|---|---|---|:--:|:--:|
| **SECA-001** | Dosya sunumu kaynak-scope kontrolü yapmaz — yatay yetki (IDOR): `serve_file` yalnız auth doğrular, dosyanın modül-iznini değil → `file_url` sızarsa izinsiz kullanıcı çek/ekstre/mesaj-eki çeker | `routers/files.py:73-145` | M | ✔ CONFIRMED |
| **FIN-002** | Dönem kilidi yok — kapanmış aya geriye kayıt raporu sessizce değiştirir (nakit akım `SUM` anlık türetilir, iz yok) | tüm finans mutasyon servisleri | M | ✔ CONFIRMED |
| **FIN-003** | Döviz rezervasyon cirosu her senkronda **güncel kurla yeniden değerleniyor** → geçmiş ay "gerçekleşen" cirosu kayar (acente mahsup/kickback yanlış tabana oturur) | `services/reservation_service.py:132-134` | M | ✔ CONFIRMED |
| **DB-002** | `sales_invoices`/`sales_collections` `tx_hash` DB UNIQUE yok (yalnız plain index + Python-set dedup) — banka/cari'de UNIQUE varken sapma; eşzamanlı/yarım import'ta çift-sayım | `models/sales_invoice.py:30-33` | M | ✔ CONFIRMED |
| **CICD-001** | Merkezi hata-izleme + APM + **ALERTING yok** — arıza yalnızca kullanıcı şikayetiyle fark edilir | `requirements.txt` (Sentry/OTel yok) | M | ✔ CONFIRMED |
| **CICD-002** | CI **merge-gate değil** — asıl akış Stop hook ile doğrudan master'a push; testler yeşil olmasa da kod canlıya gider | `.claude/settings.json:6` | M | ✔ CONFIRMED |
| **TEST-001** | `cc_statement_parser.py` (4 bankaya özel PDF parser, 643 satır) + `bank_parser.py` pratikte testsiz — en riskli finans girdi-ayrıştırıcıları | `utils/cc_statement_parser.py` | M | ✔ CONFIRMED |
| **JOBS-001** | Arka plan işlerinde başarısızlık görünürlüğü yok — kur/senkron 3 gündür güncellenmese kimse fark etmez ("son başarılı koşu" yok) | `scripts/systemd/sprenses-sales-sync.service` | M | ✔ CONFIRMED |
| **DR-003** | Yedek başarısızlık alarmı yok (`OnFailure=` yok) — sessizce aylarca bozuk kalabilir | kurulu `sprenses-db-backup.service` | S | ✔ CONFIRMED |
| **DOCS-001** | Bus factor = 1 (256/258 commit tek geliştirici); README/CODEOWNERS/onboarding yok | repo kökü | M | ✔ CONFIRMED |
| **DOCS-002** | Üretim RUNBOOK'u yok — gece-arıza/restore/sertifika/disk-dolu prosedürü belgesiz | `docs/` | M | ✔ CONFIRMED |

> **SRV-003** (off-site pasif/IAM yok) DR-002 ile aynı kök → DR-002 altında sayıldı. **DOCS-006** (uploads yedeksiz) = DR-001. **CICD-006/SECA-002** (başarısız giriş audit'e yazılmıyor) tek bulgu (Orta).

### ⤵️ Doğrulamada DÜŞÜRÜLEN/çürütülen bulgular (rigor kanıtı)

2. göz, ilk taramada Yüksek işaretlenen şu bulguları koddan **düşürdü** — false-positive ayıklama çalıştı:

- **SECB-001** CSWSH (WS Origin kontrolü) Yüksek→**Düşük** (cookie+samesite+tek-oturum zaten büyük ölçüde koruyor)
- **FIN-001** para-katmanı float Orta→**Düşük** (her op sonrası `round(...,2)` → drift <0.01, gerçek para hatası yok; yalnız standart tutarsızlığı)
- **FIN-005** satış dedup / **FIN-006** cari-FIFO para-birimi Orta→**Düşük** (tek-kullanıcı import / TL-ağırlıklı cari → pratik risk düşük)
- **PERF-001** async-blocking Yüksek→**Orta**; **DB-001/I18N-002** C.UTF-8 collation Yüksek→**Orta**
- **PRIV-001/002** KVKK retention/veri-sahibi-hakları Yüksek→**Orta**; **SRV-004** rebuild Yüksek→**Orta**; **I18N-001** naive-datetime Yüksek→**Orta**
- **API-004** Idempotency-Key Orta→**Düşük** (frontend `Button loading` + görünür kayıt)

---

## Çıktı 1 — Risk Matrisi (olasılık × etki)

| | **Etki: Yüksek** | **Etki: Orta** | **Etki: Düşük** |
|---|---|---|---|
| **Olasılık: Yüksek** | 🔴 SRV-001 (TLS bitişi kesin) · JOBS-001 · DR-003 | 🟠 CICD-002 · API-001 · I18N-001 | FIN-001 · DOCS-007 |
| **Olasılık: Orta** | 🔴 DR-001 · DR-002 · CICD-001 · FIN-002 · FIN-003 | 🟠 SECA-001 · DB-002 · FIN-004 · PRIV-003 · DOCS-004 | API-002/003 · FE-003 |
| **Olasılık: Düşük** | 🟠 TEST-001 · DOCS-001/002 | SECA-003/004 · PERF-002 · DB-004 | FIN-005/006/007 · SECB-002 |

---

## Çıktı 15 — Hızlı Kazanımlar (efor ≤1g × etki Yüksek/Kritik)

Bu 6 madde **ilk hafta** kapatılabilir ve en büyük risk kümesini eritir:

1. **SRV-001 (S):** `systemctl enable --now certbot-renew.timer` + `certbot renew --dry-run` → **~12 günlük zamanlı bombayı defuse et.** (En acil.)
2. **DR-001 (S/M):** `db-backup.sh`'e `tar czf uploads-*.tgz backend/uploads` satırı ekle → yüklenen dosyalar günlük yedeğe girer.
3. **DR-003 (S):** `sprenses-db-backup.service`'e `OnFailure=` bildirim unit'i (mevcut `utils/push.py`) → sessiz-bozuk-yedek riski kalkar.
4. **JOBS-001 (S):** Sedna/kur senkron unit'lerine `OnFailure=` + "son başarılı koşu" göstergesi (sunucu izleme ekranına).
5. **FIN-004 (S):** `credit_service.py:58,150` `if product.bsmv_rate` → `is not None` — BSMV=0 gerçekten uygulanır (banka ekstresiyle uyum).
6. **DOCS-003 (S):** CLAUDE.md tablo sayısı 63→**65** + `agency_code_map`/`receivable_terms` ekle; test sayısı 293→**305**.

---

## Çıktı 9 — 30 / 60 / 90 Günlük İyileştirme Planı

**30 gün — "Kesintiyi ve veri kaybını durdur":**
- 🔴 Tüm Quick Wins (SRV-001, DR-001, DR-003, JOBS-001, FIN-004, DOCS-003).
- 🔴 **DR-002:** S3 off-site (farklı bölge, versioning+SSE) + IAM role → DB+uploads off-site.
- 🟠 **CICD-002:** CI'yı merge-gate yap (branch protection / required checks) + ruff+svelte-check adımları (ARCH-001).
- 🟠 **SECA-001:** `serve_file`'a kaynak-scope yetki kontrolü (dosya sınıfı → modül izni).

**60 gün — "Görünürlük ve finansal bütünlük":**
- 🟠 **CICD-001:** Sentry (backend + `hooks.client.ts` frontend) → hata/alerting; readiness probe'a DB kontrolü (CICD-005).
- 🟠 **FIN-002:** `closed_periods` tablosu + mutasyon guard (dönem kilidi).
- 🟠 **FIN-003:** `eur_total`'ı checkout kuruyla **dondur** (geçmiş ciro değişmez).
- 🟠 **DB-002:** satış fatura/tahsilat `tx_hash` UNIQUE + `ON CONFLICT` upsert.
- 🟠 **TEST-001:** `cc_statement_parser`/`bank_parser` için gerçek-örnek fixture testleri (freezegun ile — TEST-002).
- 🟠 **DOCS-001/002:** README + onboarding + `docs/modules/runbook.md`.

**90 gün — "Uyum ve olgunluk":**
- **KVKK (PRIV):** kişisel veri envanteri + retention politikası (DB-005/DOCS-005 retention job) + aydınlatma/rıza + veri-sahibi-hakları akışı.
- **3rd-party (PRIV-003):** Sedna/TCMB/push çağrılarına timeout+retry+circuit-breaker.
- **Ölçek (DOCS-004):** `--workers 1` kısıtını + in-memory state envanterini CLAUDE.md'ye bilinçli-borç olarak yaz; Redis dışsallaştırma tasarımı.
- **Kod kalitesi:** en büyük 3 frontend sayfasını böl (ARCH-002); finans servislerini ortak `money.py` (Decimal+ROUND_HALF_UP) ile hizala (FIN-001).
- **DR tatbikatı (DR-004):** aylık otomatik restore-drill timer + RPO/RTO tanımı (DR-005).

---

## Boyut Özetleri (skor · güçlü yönler · ana bulgular)

**1-2 Mimari & Kod Kalitesi — 7/10.** ✅ Katman yönü mimari olarak zorlanmış (`services/`+`utils/` hiç router import etmiyor); onay/dual-write 16/16 handler ortak domain-service çağırıyor; fabrika desenleri (`create_scheduled_router`, `_make_crud_handler`). ⚠️ CI lint/type-gate yok (ARCH-001); dev frontend dosyaları >1400 satır (ARCH-002); `formatCurrency` sayfalarda tekrar tanımlı (ARCH-003); 439 `any` (ARCH-004, düşük — svelte-check 0 hata).

**3 Güvenlik — 7.5/10.** ✅ JWT yalnız HttpOnly+secure+samesite cookie (frontend token'ı hiç görmez); tek-oturum HTTP/WS/dosya'da tutarlı; `?token=` fallback güvenlik için kaldırılmış; `require_permission` tüm mutasyonlarda; bcrypt-passlib; UUID dosya adları; rate-limit güvenilir `X-Real-IP` ile. ⚠️ **Dosya-IDOR (SECA-001, Yüksek)**; başarısız giriş audit'e yazılmıyor (SECA-002); IP-only rate-limit + hesap kilidi yok (SECA-003); 24s sabit oturum, 2FA yok (SECA-004); zayıf SECRET_KEY fail-open (SECA-005). SQL injection/path-traversal/CSP/HSTS/CORS-whitelist doğrulandı — temiz.

**4-5 Performans & Stabilite — 7/10.** ✅ Global exception handler + ErrorLog; TTL cache'ler; para-birimi-ayrık FIFO. ⚠️ async endpoint'lerde senkron DB/parse bloklaması (PERF-001, Orta); `payment-schedule` GET'i her okumada FIFO+commit (PERF-002); threadpool(40)>DB pool(35) (PERF-004).

**6 Veritabanı — 7/10.** ✅ `finance_events` UNIQUE+idempotent upsert; banka/cari `tx_hash` UNIQUE; elle-yazılan güvenli migration'lar. ⚠️ **satış `tx_hash` UNIQUE eksik (DB-002, Yüksek)**; C.UTF-8 collation (DB-001→Orta); finans CHECK constraint yok (DB-004); retention yok (DB-005).

**7 API — 6/10.** ✅ REST/çoğul/kebab-case/ASCII path kusursuz; PATCH-only; merkezi pagination helper; `/docs` publicte 404 (ifşa yok). ⚠️ `response_model` yalnız 40/327 endpoint (API-001) → OpenAPI zayıf; `pages` 3 konvansiyon (API-002); başarı-gövdesi 5 anahtar (API-003); 422 İngilizce sızıyor (API-005).

**8 Frontend — 7/10.** ✅ Tasarım sistemi (Button/StatCard/MoneyInput/ListPage), lacivert/altın tema token'ları, mobil tablo→kart. ⚠️ E2E yok (FE-001); `fieldErrors` tutarsız (FE-002); `text-gray-400` AA-fail (FE-003).

**9-10 Test — 7/10.** ✅ 1232 backend + 305 frontend test; SAVEPOINT izolasyonu; izin-matrisi fixture'ları; test-DB izolasyon sigortası. ⚠️ **parser'lar testsiz (TEST-001, Yüksek)**; freezegun yok (TEST-002); takvim-bağlı sessiz skip (TEST-003); gerçek PII fixture (TEST-004).

**11-12-17 CI/CD, Loglama, Observability — 4/10 (en zayıf küme).** ⚠️ **CI merge-gate değil (CICD-002, Yüksek)**; **APM/alerting yok (CICD-001, Yüksek)**; lint/SAST/dependency-scan yok (CICD-003); frontend client-hata yakalama yok (CICD-004); health probe sığ (CICD-005); structured/correlation log yok (CICD-008). ✅ audit_logs + ErrorLog + generic-mesaj-handler var.

**13-14-15 Doküman, Ölçek, Teknik Borç — 6/10.** ✅ 42 modül dokümanı + 744-satır CLAUDE.md + arşivli denetim geçmişi. ⚠️ **bus factor=1 + README/runbook yok (DOCS-001/002, Yüksek)**; doküman-drift otomasyonu yok + 63→65 tablo drift'i (DOCS-003); in-memory state tek-worker'a bağlı (DOCS-004); retention yok (DOCS-005); auto-yedek commit gürültüsü (DOCS-007).

**16 DR — 5/10.** ✅ Günlük `pg_dump -Fc` fiilen çalışıyor (15 gün kesintisiz) + bütünlük doğrulama + rotasyon + restore aracı. ⚠️ **uploads yedeksiz (DR-001) + off-site pasif/tek-EBS (DR-002) = 2 Kritik**; alarm yok (DR-003); tatbikat periyodik değil (DR-004); RPO/RTO+runbook yok (DR-005); "Yedekleme" modülü yalnız kod yedekler (DR-006).

**18-19 KVKK & 3rd-Party — 3.5/10 (en düşük).** ⚠️ Kişisel veri envanteri/retention/maskeleme/aydınlatma-rıza/ihlal-bildirim/veri-sahibi-hakları **hiç yok** (PRIV-001/002/004/005); 3rd-party çağrılarında retry/circuit-breaker yok (PRIV-003); Sedna sync-all istek yolunda uzun senkron (PRIV-006). Not: bunların çoğu 2. gözde Orta'ya çekildi (aktif ihlal değil, süreç boşluğu).

**20 Finansal Doğruluk — 7/10.** ✅ Çift-sayım yapısal engelli (`finance_events` UNIQUE+upsert, `tx_hash`); dual-write sapması kapalı; temettü servisi örnek-nitelikli (Decimal+HALF_UP); FIFO para-birimi-ayrık; ekran↔PDF tek kaynak. ⚠️ **dönem kilidi yok (FIN-002, Yüksek)**; **FX ciro yeniden-değerleme (FIN-003, Yüksek)**; BSMV=0 uygulanamıyor (FIN-004); para-katmanı float ama drift<0.01 (FIN-001→Düşük).

**21 Arka Plan İşleri — 6/10.** ✅ systemd timer'lar (yedek, sales-sync, ssh-audit, exchange-rate). ⚠️ **başarısızlık görünürlüğü yok (JOBS-001, Yüksek)**; `cron_weekly_push` zamanlayıcısı yok (JOBS-002); tek envanter yok (JOBS-004).

**22 Sunucu & Ortam — 6/10.** ⚠️ **TLS renewal kapalı (SRV-001, Kritik)**; OS auto-patch yok (SRV-002); off-site+IAM yok (SRV-003=DR-002); fail2ban yok (SRV-005); swap yok/OOM koruması (SRV-006); `PermitRootLogin without-password`+X11Forwarding (SRV-007). ✅ systemd auto-restart; SSH tünel anahtarı sertleştirme (`ssh-key-audit`).

**23 Zaman & Türkçe — 5/10.** ⚠️ Process TZ ayarsız → naive `date.today()`/`datetime.now()` UTC döner (I18N-001→Orta); C.UTF-8 collation Türkçe sıralamayı bozar (I18N-002); para formatı sayfa-sayfa elle (I18N-003). ✅ DB bağlantıda `SET timezone`; `config.py` pytz.

---

## Çıktı 11 — KVKK / Kişisel Veri Envanteri ve Boşluklar

| Tablo | PII | Saklama | Maskeleme | Boşluk |
|---|---|---|---|---|
| `users` | ad, e-posta, hash | süresiz | — | rıza/aydınlatma kaydı yok |
| `personnel`, `attendance_logs` | ad, TC?, PDKS | süresiz | yok | retention yok |
| `vendors`, `reservations` | cari/misafir ad, iletişim | süresiz | yok | 3rd-party (Sedna/PMS) aktarım sözleşmesi belgesiz |
| `audit_logs` (23.301), `error_logs`, `messages` | IP, kullanıcı eylemi, mesaj | süresiz | — | retention/anonimleştirme yok |

**Genel boşluk (PRIV):** envanter yok · retention yok · maskeleme yok (log/yedek/test) · aydınlatma+açık rıza yok · ihlal-bildirim (72s) süreci yok · veri-sahibi erişim/silme/düzeltme mekanizması yok. → 90-gün planında.

## Çıktı 12 — DR / Restore Tatbikat Raporu

| Kontrol | Durum |
|---|---|
| Otomatik DB yedeği | ✅ günlük `pg_dump -Fc` 03:00, 15 gün kesintisiz, bütünlük-doğrulamalı, 30-rotasyon |
| Off-site kopya | ❌ **PASİF** (IAM yok) — DR-002 Kritik |
| Yedek kapsamı | ⚠️ yalnız DB; **uploads (91MB) + .env + nginx/systemd config + TLS yedek DIŞI** |
| RPO / RTO | ❌ tanımsız |
| Restore tatbikatı | ⚠️ araç var; yalnız 2026-06-22'de 1 kez elle (periyodik değil) |
| PITR / WAL | ❌ yok |
| SPOF | ❌ tek EC2 / tek 30GB EBS / tek DB |

## Çıktı 13 — 3rd-Party Dayanıklılık Matrisi

| Servis | Timeout | Retry | Circuit-breaker | Fallback | Idempotent |
|---|:--:|:--:|:--:|:--:|:--:|
| Sedna SQL Server | kısmi | ❌ | ❌ | 503 (graceful) | ✅ (RecId/tx_hash) |
| TCMB kur | kısmi | ❌ | ❌ | son kur | ✅ |
| Travelpayouts | var | ❌ | ❌ | mock/widget | n/a |
| Push (VAPID) | var | ❌ | ❌ | sessiz | ✅ |

→ Genel: **retry/circuit-breaker yok** (PRIV-003). Timeout tek başına dayanıklılık değil.

## Çıktı 14 — Delta Raporu (06-21 → 07-05)

- ✔ **KAPATILAN:** `[DB-2026-06-21]` "otomatik DB yedeği yok" (tek Kritik) → günlük pg_dump fiilen çalışıyor. **Ana kazanım.**
- ▲ **YENİ Kritik:** SRV-001 (TLS renewal), DR-001 (uploads yedeksiz), DR-002 (off-site/tek-EBS) — daha derin DR/sunucu merceğiyle.
- ● **DEVAM:** CI merge-gate değil (5.5→4), APM/alerting yok (6.5→3.5 gözlemlenebilirlik ayrıştı), in-memory ölçek (5.5→5), bus factor.
- ▲ **İLK KEZ PUANLANAN:** Finansal Doğruluk 7, KVKK 3.5, 3rd-party 4, Arka plan 6, Sunucu 6, i18n 5.
- 🟰 **KORUNAN çekirdek:** Güvenlik ~8, Frontend ~7-8, Mimari/DB/Performans ~7 (kod katmanı 06-21 seviyesinde).

## Çıktı 17 — Arka Plan İşleri Envanteri

| İş | Zamanlama | TZ | Son-başarılı görünür? | Overlap | Alarm |
|---|---|---|:--:|:--:|:--:|
| DB yedek | 03:00 günlük | Istanbul | journalctl (elle) | — | ❌ |
| Sedna sales-sync | timer | ? | ❌ | ? | ❌ |
| Exchange-rate | timer | ? | ❌ | ? | ❌ |
| ssh-key-audit | path/timer | — | — | — | — |
| `cron_weekly_push` | **zamanlayıcı YOK** | — | ❌ | — | ❌ |

## Çıktı 18 — Kapanış Kriterleri (Kritik/Yüksek)

Her bulgunun "kapandı" tanımı ilgili kutuda (`Kapanış:` satırı) ve tabloda verildi. Bir sonraki denetimin kabul testi bu kriterlerdir; bulgu ID'leri (SRV-/DR-/FIN-/SECA-/DB-/CICD-/TEST-/JOBS-/DOCS-) delta takibi için kalıcıdır.

---

*Çıktı 2 (Eksik Test Senaryoları): parser'lar (cc_statement/bank), finansal uç durum (kuruş/negatif/ay-sonu/yıl-geçişi — freezegun), E2E (Playwright). · Çıktı 3-4 (Test kullanıcı/mock): izin-matrisi fixture'ları mevcut ✔; harici HTTP network-guard eksik. · Çıktı 5 (Doküman drift): DOCS-003. · Çıktı 6-7 (Güvenlik/Performans listeleri): yukarıdaki boyut bölümleri. · Çıktı 10 (Genel not): 62/100 → hedef 80.*
