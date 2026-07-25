# Sprenses ERP — v4 Kurumsal Kod Denetimi

## §0 — Denetim Kimliği ve Kapsam

| Alan | Değer |
|---|---|
| **Denetim tarihi** | 2026-07-24 / 25 |
| **Denetçi** | Claude Opus 5 — çok-ajanlı orkestrasyon: **23 bağımsız boyut denetçisi + 63 çekişmeli 2. göz doğrulayıcı** (toplam 86 ajan, 2.142 araç çağrısı, 8,56 M token) |
| **Denetlenen sürüm** | git `41e7552` · branch `master` · çalışma ağacı **temiz** |
| **Şablon** | Kurumsal Kod Denetim Şablonu **v3** (23 boyut, 18 çıktı) |
| **Kapsam** | `backend/` (FastAPI, 268 py / 54.702 LOC / 101 migration / 52 model) + `frontend/` (SvelteKit, 118 svelte + 66 ts) + altyapı (EC2/systemd/nginx/yedek/TLS) + `docs/` + canlı üretim veritabanı (salt-okuma) |
| **Bilinçli hariç** | Kod yazımı/onarım (salt-okunur denetim). Uyuyan banka entegrasyonları (QNB/Garanti/YKB) yalnız dayanıklılık boyutunda değerlendirildi. |
| **Örnekleme** | Kritik yollar (finans, auth, DR, sunucu, arka plan işleri) **%100** derin okuma + **canlı DB doğrulaması**; kalan boyutlar hedefli örneklem + kanıt (`dosya:satır`). |
| **Önceki denetim referansı** | 2026-07-05 **v3** (62/100 ağırlıklı · 59/100 aritmetik, 3 Kritik) · 2026-06-21 v2 (72/100) · 2026-07-01 tam modül denetimi (156 bulgu) |
| **Kalite süreci** | 204 bulgu üretildi. Her Kritik/Yüksek bulgu bağımsız 2. gözle çürütülmeye çalışıldı → **61 bulgunun risk seviyesi düşürüldü**, yalnız 2'si Kritik'te teyit edildi. Ana denetçi ayrıca 6 headline bulguyu canlı sistemde bizzat doğruladı (aşağıda ✔ ile işaretli). |
| **Revizyon** | **R1 · 2026-07-25 04:35** — 3 bulgu kapatıldı (FIN-001 Kritik · DB-001 · JOBS döviz cron'u).<br>**R2 · 2026-07-25 05:15** — ARCH-001 kapatıldı **ve bu raporun bir bulgusundaki yanlış canlı-sapma iddiası düzeltildi** (bkz. R2 Kapanış Kaydı).<br>**R3 · 2026-07-25 05:35** — DR ailesi: DR-001 büyük ölçüde kapandı (uploads yedekte + tatbikat), DR-003 kapatıldı (alarm kanalı canlı), DR-002 AWS provizyonuna bağlı açık.<br>**R5 · 2026-07-25 10:30** — İLK GERÇEK RESTORE TATBİKATI koşuldu (`docs/denetim/2026-07-25-restore-tatbikati.md`): başarılı, ama **R3'teki izin sertleştirmesinin felaket kurtarmayı sessizce kırdığını yakaladı**. RPO/RTO ilk kez tanımlandı.<br>**R4 · 2026-07-25 10:05** — CICD-010'un **ön koşulları** açıldı: sıfırdan bootstrap'ı engelleyen 3 kusur (migration FK sırası · seed'in 14 modül geride olması · 7 bayat modül yaması) düzeltildi. Taze DB'de 1927 test yeşil. Bulgu kapanmadı — Actions'ı açmak hâlâ depo sahibinde. Bulgu metinleri **silinmedi**; durumlar güncellendi, hatalı iddia üstü çizilerek gerekçesiyle bırakıldı — denetim anının fotoğrafı ve hatanın izi birlikte korunur. |

---

## Kapanış Kaydı — R5 (2026-07-25) · İlk gerçek restore tatbikatı

Tam kayıt: **[`docs/denetim/2026-07-25-restore-tatbikati.md`](2026-07-25-restore-tatbikati.md)**

**Sonuç ✔ başarılı:** DB satır sayıları üretimle birebir (users/roles/modules/finance_events/
vendor_transactions/checks/credit_products/reservations tam eşleşme; `audit_logs` 25.048→25.047
= dump anından beri +1, beklenen). uploads snapshot'ından rastgele 5 mali belge **5/5 md5-özdeş**.
Süre: DB 4,3 sn + uploads 2,4 sn.

### Tatbikatın yakaladığı kusur — kendi sertleştirmemiz kurtarmayı kırmıştı

İlk koşu `pg_restore: could not open input file … Permission denied` ile **öldü**. Sebep:
R3'te yedekler sertleştirildi (dosya `0600`, dizin `0700`, sahip `ec2-user` — DR-002 gereği
doğru bir adım), ama tatbikat `sudo -u postgres` ile koşuyor ve **`postgres` o dosyayı
okuyamıyor**. Yani felaket kurtarma sessizce kırılmıştı; gerçek bir felakette anlaşılacaktı.

Düzeltme: dump geçici bir kopyaya sahnelenip oradan yükleniyor (`mktemp -d` + `trap`);
**kaynak yedeğin izinleri değişmiyor**. Üretime geri yükleme yolu `ec2-user` olarak koştuğu
için etkilenmiyordu.

Ayrıca: `could not change directory` gürültüsü giderildi ve **uploads doğrulaması tatbikata
eklendi** (önceden yalnız DB test ediliyordu — oysa dosyasız DB işe yaramaz).

### RPO / RTO — ilk kez tanımlandı (denetimde "TANIMSIZ" idi)

| Ölçüt | Değer |
|---|---|
| **RPO** | **≤ 24 saat** — günlük tek yedek, PITR/WAL yok |
| **RTO** (aynı makine) | **≤ 30 dk** — ölçülen teknik süre 7 sn; kalanı insan müdahalesi |
| **RTO** (makine kaybı) | **BELİRSİZ, ≥ 1 gün** — off-site yok (DR-002), rebuild runbook'u yok |

> **Ders:** Sertleştirme ve kurtarılabilirlik birbirini sessizce bozabilir. Bu tatbikat
> olmasaydı, yedeklerin okunamadığını ancak gerçek bir felakette öğrenirdik. **Yedek
> izinlerine/script'ine her dokunuşta tatbikat tekrar koşulmalı.**

---

## Kapanış Kaydı — R4 (2026-07-25) · CI'ın önündeki gizli engeller

Bu tur bir bulgu kapatmadı; **CICD-010'un ön koşullarını** açtı. Rapor "Actions'ı aç, 15 dk"
diyordu — **yanlıştı**. CI açılsaydı ilk adımda ölürdü. Üç ayrı engel vardı ve üçü de tam olarak
*CI hiç çalışmadığı için* birikmişti.

| # | Engel | Belirti | Düzeltme |
|:--:|---|---|---|
| 1 | **Migration FK sırası** | `alembic upgrade head` sıfırdan çöküyordu: `b7d2f4a8c1e6` modül 925'i (`sales.kontratlar`) `parent_id=896`'ya bağlıyor, ama 896 (`Satış`) `02_seed.sql`'de ve migration'dan SONRA yükleniyor | Modül + izin insert'leri `WHERE EXISTS (parent)` ile koşullu yapıldı; üretimde (896 varken) aynen çalışır, taze kurulumda atlanır |
| 2 | **Seed sürüklenmesi** | `02_seed.sql` üretimden **14 modül geride**: `finance.sales_invoices` · tüm `stok.*` · `ai.*` · `accounting.mutabakat` · `finance.hakedis` · `system.docs`. `reset_data.sql` TÜM tabloları TRUNCATE ettiğinden seed tek kaynak → eksik modül test DB'sinde HİÇ oluşmuyor → admin izin alamıyor → **17 test kırmızı** | modules + role_module_permissions blokları üretimden yeniden üretildi (50 modül / 356 izin) |
| 3 | **Bayat modül yamaları** | COPY bloğundan sonra elle eklenmiş 7 "idempotent" INSERT vardı ve id'leri üretimden kaymıştı (`system.docs` seed=914/üretim=915 · `stok.*` seed=904-908/üretim=905-909). `ON CONFLICT (id)` farklı id'yi yakalamıyor, `ix_modules_code` UNIQUE patlıyordu | 7 yama kaldırıldı; yerine "yama ekleme, bloğu üretimden yeniden üret" kuralı yazıldı |

### Sonuç — CI artık açılabilir

```
Sıfırdan bootstrap : 5/5 adım temiz (alembic → reset_data → 02_seed → seed_admin)
Test DB            : 50 modül (üretimle birebir), izinsiz Sedna adımı yok
Tam takım          : 1927 geçti · 5 atlandı · 0 HATA (13:59)
```

**Öncesi:** aynı takım aynı taze DB'de **17 hata** veriyordu (8 `test_sales_invoices` + 3
`test_sedna_sync` + 6 diğer). Artımlı büyütülmüş DB'de yeşil görünüyordu — sürüklenmeyi
gizleyen tam da buydu.

CI **birebir aynı dört adımı ve aynı dosyaları** çalıştırıyor
(`.github/workflows/ci.yml` → `reset_data.sql` · `02_seed.sql` · `seed_admin.py`) → yerel
doğrulama CI'a transfer eder.

### Yol üstünde bulunan iki ek kusur

- **`setup-test-db.sh` DB şifresini düz metin basıyordu** (son satırdaki "testleri şöyle
  çalıştır" ipucunda; satır 36'daki maskeleme orada unutulmuş). Depo public olduğundan CI
  logları bunu kalıcı yayımlardı. Kapatıldı.
- **Yedek rotasyonunda sıralama hatası (R3'te eklediğim kodda):** rotasyon `ls -1dt` ile
  **mtime**'a göre sıralıyordu, ama `rsync -a` dizin zaman damgalarını kaynaktan kopyalıyor →
  canlıda dört snapshot da aynı mtime'a sahipti (`2026-07-17 10:30:22`). Sıralama anlamsız,
  yani 31. günde **en yeni snapshot silinebilirdi**. Ad sıralamasına çevrildi
  (`YYYYMMDD-HHMMSS` sözlüksel = kronolojik) ve `KEEP=2` ile gerçek rotasyon testiyle
  doğrulandı (en yeni 2 kaldı, hardlink'ler sağ çıktı). `KEEP=30` olduğu için zarar vermemişti.

> **Ders — bu turun asıl bulgusu:** Üç engelin hiçbiri kod hatası değildi; üçü de
> *doğrulanmamış varsayım*du. "Testler geçiyor" ifadesi, **hangi DB'de** geçtiği sorulmadığı
> sürece anlamsız: artımlı büyütülmüş bir test DB'si, seed'in üretimden 14 modül geride
> olduğunu 14 modül boyunca gizledi. CICD-010'un maliyeti "15 dakika" değil, "bir günün
> yarısı + üç gizli kusur"du — ve bu maliyeti üreten şey bulgunun kendisiydi.

---

## Kapanış Kaydı — R3 (2026-07-25) · DR ailesi

| ID | Risk | Durum | Ölçülen sonuç |
|---|:--:|:--:|---|
| **DR-001** uploads yedeksiz | 🔴 Kritik | ◐ **Büyük ölçüde kapandı** | Günlük hardlink snapshot ✔ · restore tatbikatı ✔ · **off-site ✗** (DR-002'ye bağlı) |
| **DR-003** yedek başarısızlık alarmı yok | 🟠 → Orta | ✔ **KAPATILDI** | 5 işe `OnFailure=` bağlandı; bilerek başarısız birimle uçtan uca doğrulandı |
| **DR-002** off-site yok + tek EBS | 🔴 Kritik | ⬜ **AÇIK — bende değil** | AWS tarafında tıkalı: IMDS boş, IAM role yok, `aws sts` kimliksiz |

### DR-001 — uploads artık yedekte

`scripts/db-backup.sh` genişletildi: `backend/uploads/` (285 MB · 1969 dosya) →
`/var/backups/sprenses-uploads/<ts>/` **hardlink snapshot** (`rsync --link-dest`).

- **Neden tar.gz değil:** içerik zaten sıkıştırılmış (1259 xls · 411 pdf · 113 jpg) → 30 günlük
  tam kopya ≈ **7,5 GB** olurdu (30 GB diskte kabul edilemez). Hardlink'te değişmeyen dosya yer
  kaplamaz. **Ölçüldü:** iki snapshot toplam **285 MB** (570 değil), `links=2`.
- **Restore tatbikatı:** 5 rastgele mali belge kaynak↔snapshot checksum-özdeş; PDF `%PDF-`
  imzasıyla açılıyor.
- **Yan kazanç (DR-002'nin bir parçası):** `umask 077` + dump'lar `0600`, dizinler `0700`.
  Öncesi `0644`/`0755` idi — tüm finans+KVKK verisi ayrıcalıksız her sürece okunabilirdi.
- **Disk bekçisi:** boş alan < 2000 MB ise yedek alınmaz ve hata verir (dolu disk PostgreSQL'i
  durdurur — yedek işi koruduğu sistemi öldürmemeli).

### DR-003 — alarm kanalı kuruldu ve gerçekten çalıştı

`scripts/systemd-failure-alert.py` + `sprenses-alert@.service` şablonu; 5 işe drop-in ile
bağlandı (db-backup · exchange-rates · sedna-sync · sales-sync · ai-digest). `/etc` git'te
olmadığından (DEBT-003) drop-in'ler `scripts/systemd/dropins/` altında kurulum README'siyle
saklanıyor.

**Uçtan uca kanıt:** `/bin/false` çalıştıran geçici bir birim tetiklendi → systemd alarmı
otomatik başlattı → `error_logs`'a CRITICAL kayıt düştü → e-posta gönderildi.

> **Bu turda ikinci bir sessiz-hata yakalandı — alarmın kendisinde.** İlk sürüm alıcıları
> `u.role.name == "Admin"` ile seçiyordu; ilişkinin gerçek adı **`role_rel`** olduğundan
> `getattr(u, "role", None)` sessizce `None` dönüyor ve alarm **hiç e-posta göndermiyordu**.
> Tam da kapatmaya çalıştığı hata sınıfı. Alıcı seçimi izne bağlandı (`system.server` /
> `system.error_logs`), rol adına değil.

> **⚠️ Yeni açık bulgu:** iki alıcıdan **`admin@sprenses.com` teslim edilemiyor** —
> `550 5.1.1 Recipient address rejected: User unknown in virtual mailbox table`. Alarm fiilen
> **tek kişiye** ulaşıyor (`finans@…`). Bu, alarm kanalının yarısının ölü olması demektir;
> adres düzeltilmeli. *(Kullanıcı kararı — dokunulmadı.)*

### DR-002 neden kapanamadı

Off-site altyapısı **kod tarafında hazır**: `db-backup.sh` DB'yi ve uploads'ı
`SPRENSES_BACKUP_S3` set edilir edilmez S3'e gönderiyor; `scripts/enable-offsite-backup.sh`
ve `docs/modules/yedekleme.md`'deki runbook duruyor (değişiklik gerekmedi). Eksik olan tek şey
**AWS hesabında bir kerelik provizyon**: S3 bucket + minimal IAM policy + role'ün EC2'ye
eklenmesi. Bu, sunucudan yapılamaz (kimlik yok) — hesap sahibinin işidir.

---

## Kapanış Kaydı — R2 (2026-07-25) · ARCH-001 + bir denetim hatasının düzeltilmesi

**ARCH-001 KAPATILDI.** `match_credit_payment` artık ortak uygulayıcıyı çağırıyor —
kredi eşleştirmesinin üç giriş noktası (otomatik matcher · öneri-Onayla · manuel uç) tek
davranışta birleşti. Yeni: `tests/test_credit_match_principal.py` (5 test). Düzeltme geri
alınarak kanıtlandı: tek tur **+₺8.000** (tam anapara), üç tur **+₺24.000** (birikim),
çift eşleştirme 409 yerine 200.

### ⚠️ Bu turda kendi denetim bulgumuzda bir hata bulundu

| | |
|---|---|
| **Yanlış iddia** | "Canlıda Halk Leasing #446'da **₺22.963,23 sapma**, doğrudan atfedilebilen manuel taksit ₺14.835,60" |
| **Gerçek** | #446 **tutarlı**: `remaining_amount` 67.748,34 = `total_amount` 86.041,56 − ödenen anapara 18.293,22 (kuruşu kuruşuna) — ve ödenen anaparaya manuel eşleşen taksitin 14.835,60'ı **dahil** |
| **Hatanın kökü** | Denetim ajanı sapmayı `remaining_amount − Σ(ödenmemiş anapara)` ile hesapladı. Bu değişmez bu veri modelinde geçerli değil: `total_amount` (86.041,56) ≠ Σ(tüm anapara) (63.078,33) ve fark **tam olarak 22.963,23** — yani "sapma" ürünün kurulum özelliğiydi, bug'ın izi değil |
| **Neden yakalanmadı** | 2. göz **kod asimetrisini** doğruladı (gerçek) ama ana denetçi bunu **canlı sapma** iddiasına genişletirken değişmezi doğrulamadı |

**Canlı etki — yeniden ölçüldü:** Bu uçtan 33 eşleşme geçmiş (hepsi 2026-07-19).
Ayırt edici: `method='manual' AND score IS NULL` → hatalı uç; öneri-Onayla yolu `score`
yazar. Bu 33'ün yalnız **6'sında `principal` doluydu** (gerisi BCH, `principal` NULL →
düşüm zaten yapılmaz) ve etkilenen üç ürünün (#10 · #13 · #446) `remaining_amount`'ı
**bugün tutarlı** (#13: 320.000−320.000 = 0 ✔). O günkü elle banka-eşitleme çalışmasında
rakamlar düzeltilmiş görünüyor.

> **Sonuç:** Kusur **gerçek ve kanıtlı** (testler tur başına tam +anapara birikimi
> gösteriyor), ama **kalıcı canlı para sapması üretmedi**. Düzeltme geleceğe dönüktür.
> Veri onarımı **yapılMADI** — onarılacak sapma yok. Ayrıca ürün tiplerinde
> `remaining_amount` farklı anlam taşıdığından (kredi kartında **limit**, taksitli/leasingde
> **anapara bakiyesi**) global bir "sapma taraması" anlamlı değildir; bu, ileride benzer
> bir iddia kurulurken hatırlanmalı.

---

## Kapanış Kaydı — R1 (2026-07-25)

Denetimden sonraki ilk düzeltme turu. Her kapanış, raporun kendi **Kapanış Kriteri**yle
(Çıktı 18) ölçüldü; kriter sağlanmadan hiçbir madde kapalı sayılmadı.

| ID | Risk | Kapanış kriteri | Ölçülen sonuç |
|---|:--:|---|---|
| **FIN-001** | 🔴 Kritik | `SELECT count(*) … currency='TRY' AND abs(amount_try-amount)>0.01` = 0 + regresyon testi | **0** ✔ · açık kalemlerde hayalet tutar **₺696.190,94 → ₺0** ✔ · `tests/test_amount_try_integrity.py` 7 test yeşil ✔ |
| **DB-001** | 🟠 Yüksek | autogenerate boş diff (hiçbir `DROP TABLE` yok) + metadata bütünlük testi | `compare_metadata` → `DROP TABLE` önerisi **5 → 0** ✔ · `tests/test_model_registry.py` 2 test yeşil ✔ |
| **JOBS (döviz)** | 🟠 Yüksek | `journalctl -u sprenses-exchange-rates` son koşularda `[amount_try]` uyarısı yok | Cron elle koşturuldu → uyarı **yok** ✔ · sorgu yan-yana kanıtlandı: `limit(1)` ile geçiyor, `limit(1)` olmadan hâlâ `MultipleResultsFound` ✔ |

### Yapılan değişiklikler

| Dosya | Değişiklik |
|---|---|
| `app/utils/finance_event_service.py` | `_upsert` TRY kalemlerde `amount_try = amount` türetir (**merkezî yazıcı** — 9 `upsert_*` yolunun tamamını kapsar) |
| `app/routers/finance/cash_flow/t_account.py` | `_event_eur` TRY dalı `amount_try` kontrolünden **öne alındı** (savunma katmanı) |
| `app/routers/finance/cash_flow/runway.py` | aynı düzeltme |
| `app/models/__init__.py` | `Check`/`CheckUpload`/`AiConversation`/`AiMessage`/`AiUsage` kayda eklendi → 5 tablo metadata'ya girdi |
| `cron_fetch_exchange_rates.py` | `.scalar()` çağrısına `.limit(1)` — sorgu canlıda **1301 satır** dönüyordu |
| `tests/test_amount_try_integrity.py` | **YENİ** — 7 test (yazıcı · okuyucu · GBP yolu korunumu · kapanış kriteri) |
| `tests/test_model_registry.py` | **YENİ** — 2 test, alembic'in dar import yüzeyini **alt süreçte** taklit eder |
| `fix_stale_amount_try.py` | **YENİ** — canlı veri onarım script'i (varsayılan kuru çalışma, `--apply` ile yazar, kendi doğrulamasını yapar) |

### Doğrulama disiplini — iki sahte-yeşil test yakalandı

Yazılan testlerin gerçekten regresyon yakaladığı, düzeltme **geri alınarak** kanıtlandı.
İlk yazımda iki test hiçbir şey kanıtlamıyordu; ikisi de yeniden yazıldı:

1. **`test_model_registry`** — pytest süreci `conftest.py` üzerinden FastAPI uygulamasını
   yüklüyor, router'lar model modüllerini dolaylı import ettiğinden metadata "yanlışlıkla tam"
   görünüyordu → import kaldırılsa bile test yeşil kalıyordu. Çözüm: kontrol **ayrı bir alt
   süreçte**, alembic'in gördüğü daraltılmış import yüzeyinde koşar.
2. **`TestAmountTryReaders`** — test DB'sinde EUR kuru olmadığından `_event_eur` `None`
   dönüyor, test erken çıkıyordu. Çözüm: fixture gerçek bir kur tohumlar; düzeltme geri
   alınınca beklenen €4,46 yerine **€1440** üretiliyor (bug'ın tam 322 katlık büyüklüğü).

### Canlı doğrulama (üretim DB'si)

```
Bayat TRY kaydı           : 11 → 0
Açık kalemlerde hayalet   : ₺696.190,94 → ₺0
Örnek fe#1205             : amount=178,58 / amount_try=57.600,00 → 178,58 / 178,58
Onarılan satır yedeği     : scratchpad/fin001-onceki-degerler.csv (11 satır, öncesi)
```

**Test takımı:** 1921 geçti · 5 atlandı · **0 hata** (12 dk 37 sn).
**Deploy:** `sprenses-api` restart → **active** · `/api/health` **HTTP 200** · açılış logları temiz.

> **Not — 5 atlanan test bulgu TSTC-005'i doğruluyor:** "ay sonuna çok yakın", 3× "test verisi
> yok", "gerçek XLS bulunamadı". Bunlar veri/takvim koşuluna bağlı sessiz atlamalardır ve CI
> açıldığında da koşmayacaklardır — ayrı bir kalem olarak açık kalır.

---

## Yönetici Özeti

**Genel Not: 55 / 100** (aritmetik ortalama 5,52 × 10). Karşılaştırılabilir v3 değeri **59/100** idi.

> **Notun düşmesi ürün regresyonu değil, üç şeyin toplamıdır:** (a) bu denetim v3'ün göremediği **iki yapısal gerçeği** ortaya çıkardı — CI'ın hiç çalışmamış olması ve deponun herkese açık olması; (b) canlı veritabanı sorgulanarak **yönetim raporlarında görünen gerçek bir para sapması** bulundu; (c) v3'ün Kritik'lerinden ikisi (uploads yedeği, off-site) 20 gündür kapatılmadı ve risk büyüdü (uploads 91 MB → **284 MB**).

**Bimodal profil devam ediyor, ama ayrışma derinleşti:**

- **Çekirdek ürün katmanı** (boyut 1-10, 20) ort. **≈ 6,1** — v3'te 7,1'di. Düşüşün nedeni ürünün bozulması değil, ilk kez yapılan **canlı-veri doğrulamasının** kod okumasıyla görünmeyen sapmaları açığa çıkarması (FIN-001, ARCH-001, DB-001).
- **Operasyon/uyum katmanı** (boyut 11-19, 21-23) ort. **≈ 4,9** — v3'te 4,7'ydi; TLS ve TZ düzeltmeleriyle bir miktar iyileşti, CI gerçeğiyle geri düştü.

**Kapatılan v3 Kritik'i (1/3):** `SRV-001` TLS otomatik yenileme — `certbot-renew.timer` artık **enabled + active**, sertifika 16 Eki 2026'ya kadar geçerli. ✔ *canlıda doğrulandı*

**En büyük tek risk:** Sistemin **doğruluk güvencesi katmanı yok**. 1.917 test yazılmış ama bir kez bile otomatik koşmamış; 453 commit'in tamamı denetimsiz `master`'a gitmiş; para hesaplarındaki sapmalar (FIN-001'de ₺696.190,94) hiçbir alarm üretmeden aylarca yaşayabiliyor ve fiilen yaşadı. Bu bir kod kalitesi sorunu değil, **süreç sorunudur** — ve düzeltmesi bir günden kısadır.

> **R1 güncellemesi (2026-07-25):** FIN-001'in kendisi kapatıldı (₺696.190,94 → ₺0) ama
> **teşhis eden mekanizma hâlâ yok**: bu sapmayı bulan şey bir alarm değil, elle yapılan bir
> denetimdi. Aynı sınıftan bir sonraki hata yine aylarca sessiz kalır. CICD-010 (CI kapalı)
> ve OBS-001 (alarm kanalı yok) açık kaldığı sürece "en büyük tek risk" değerlendirmesi
> **aynen geçerlidir**.

**İyi haber:** Nihai 2 Kritik + 8 Yüksek bulgunun **7'si "S" eforlu**. İlk haftada kapatılabilecek işin etkisi orantısız derecede yüksek (bkz. Çıktı 15 — Hızlı Kazanımlar).

---

## Çıktı 16 — Skor Panosu (23 boyut · v3 → v4 → 90 gün hedef)

| # | Boyut | v3 (07-05) | **v4 (şimdi)** | 90g hedef | Değişimin nedeni |
|---|---|:--:|:--:|:--:|---|
| 1 | Mimari & Modülerlik | 7 | **6,5** | 8 | Katmanlama olgunlaştı (router→router kapandı) ama ortak-uygulayıcı kuralı para yolunda delik (ARCH-001) |
| 2 | Kod Kalitesi | 7 | **6,5** | 7,5 | Lint/tip hiçbir kapıda yok; FIFO mantığı üç kopya |
| 3 | Güvenlik (OWASP) | 7,5 | **5,5** | 8 | **Depo PUBLIC** (yeni tespit) + IDOR devam + CVE taraması yok |
| 4 | Performans | 7 | **6,5** | 7,5 | Temel sağlam; ölçüm/görünürlük sıfır |
| 5 | Stabilite | 7 | **6** | 7,5 | Optimistik kilit yok; senkron kilidi yok; event-loop blokajı |
| 6 | Veritabanı | 7 | **5,5** | 7,5 | **5 tablo alembic metadata dışında** (DROP riski) + 23 indeks sürüklenmesi |
| 7 | API | 6 | **5,5** | 7 | 443 uçtan 401'i tipsiz; onay 202'si frontend'de işlenmiyor |
| 8 | Frontend & Mobil | 7 | **6,5** | 7,5 | UI sapmalarının çoğu kapandı; rota testi hâlâ sıfır |
| 9 | Test Kapsamı | 7 | **6,5** | 8 | Kapsam ölçümü geldi (%77) ama para yollarında %14-20 delik |
| 10 | Test Süreçleri | 7 | **5,5** | 7,5 | **CI hiç koşmadı**; suite zamana bağlı, gece kırmızı |
| 11 | CI/CD | 4 | **3** | 7 | **Actions repo düzeyinde KAPALI** — v3'ün varsaydığı gate hiç var olmamış |
| 12 | Loglama | 5 | **5,5** | 7 | Audit geniş; error_logs'a hiçbir logger.error düşmüyor |
| 13 | Dokümantasyon | 7 | **6** | 7,5 | İçerik zengin ama drift ölçülmüyor + PUBLIC ifşa kanalı |
| 14 | Ölçeklenebilirlik | 5 | **4,5** | 6 | 15 kalemlik süreç-içi durum → çok-worker yapısal olarak imkânsız |
| 15 | Teknik Borç / Bus factor | 5 | **4,5** | 6,5 | Bus factor hâlâ 1; runbook yok; 1.493 satır ölü entegrasyon |
| 16 | Yedekleme & DR | 5 | **4,5** | 8 | DB yedeği sağlam; **uploads + off-site + konfig hâlâ yok**, hacim 3× arttı |
| 17 | Gözlemlenebilirlik | 3,5 | **4** | 7 | health ucu sahte; alarm kanalı yok; ama ai-digest bir kanal örneği kurdu |
| 18 | KVKK / Gizlilik | 3,5 | **4** | 6 | Envanter bu raporla çıkarıldı; retention/rıza/yurt-dışı dayanağı hâlâ yok |
| 19 | 3rd-Party Dayanıklılık | 4 | **5,5** | 7 | Sedna arka plana alındı + dedup/idempotency olgun; retry/CB hâlâ yok |
| 20 | Finansal Doğruluk | 7 | **6** | 8,5 | Çekirdek sağlam ama **canlıda ₺696K hayalet** + dönem kilidi bloklamıyor |
| 21 | Arka Plan İşleri | 6 | **5,5** | 7,5 | Envanter/Persistent iyi; **döviz cron'u 2 aydır sessizce yarım** |
| 22 | Sunucu & Ortam | 6 | **6,5** | 8 | TLS ✔, swap/earlyoom ✔, TZ drop-in ✔; alarm ve IaC yok |
| 23 | Zaman & Türkçe | 5 | **7** | 8 | TZ drop-in kuruldu, en büyük sınıf kapandı; collation ve 3 unit açık |

> **Katmanlı okuma:** Çekirdek (1-10, 20) ort. **6,1** · Operasyon/uyum (11-19, 21-23) ort. **4,9**. v3'teki 2,4 puanlık uçurum 1,2'ye indi — ama yakınsama yukarı değil, **aşağı doğru** oldu.

> **R1 sonrası skorlar (2026-07-25):** Yukarıdaki tablo **denetim anının** fotoğrafıdır ve
> öyle bırakılmıştır. R1 düzeltmeleri üç boyutu etkiler: **6 Veritabanı 5,5 → 6** (DROP riski
> kalktı, indeks sürüklenmesi duruyor) · **20 Finansal Doğruluk 6 → 6,5** (hayalet para
> kapandı, dönem kilidi/FX/tx_hash açık) · **21 Arka Plan İşleri 5,5 → 6** (döviz çökmesi
> bitti, alarm boşluğu duruyor). Genel not **55 → 55,5**. Nottaki hareketin küçük olması
> tesadüf değil: kapatılan üç madde de *sonuç*tu; notu asıl çeken *nedenler* — CI'ın hiç
> koşmaması, alarm kanalının olmaması, off-site yedeğin bulunmaması — aynen duruyor.

---

## Çıktı 6+8 — Kritik ve Yüksek Bulgular (çekişmeli doğrulanmış)

> **Doğrulama disiplini:** İlk taramada 10 Kritik + 53 Yüksek işaretlendi. Bağımsız 2. göz **61 bulgunun riskini düşürdü**. Aşağıdakiler doğrulamadan geçenlerdir.

### 🔴 KRİTİK (3)

```
[FIN-001] finance_events.amount_try hiç tazelenmiyor — yönetim raporlarında ₺696.190,94 hayalet yükümlülük
Dosya   : backend/app/utils/finance_event_service.py:118-170 (_upsert)
          backend/app/routers/finance/cash_flow/t_account.py:187 · runway.py:173 · aging.py:59-61
Kanıt   : Hiçbir upsert_* metodu alan sözlüğüne `amount_try` KOYMAZ → `ON CONFLICT DO UPDATE SET`
          bu kolona hiç dokunmaz. Kolonun tek yazıcısı `update_amount_try` (:697-725) yalnız
          currency='EUR' VE event_date=bugün satırlarını günceller. Okuyucular ise amount_try'ı
          amount'a TERCİH eder (TRY kontrolünden ÖNCE). Cari FIFO kırpması / KK kısmi ödemesi
          `amount`'ı küçültünce `amount_try` eski tam tutarda donar.
          ✔ ANA DENETÇİ CANLI DOĞRULAMASI (2026-07-24, üretim DB):
            · TRY kaleminde bayat amount_try: 11 kayıt, toplam sapma ₺2.426.887,85
            · Bunlardan hâlâ AÇIK (is_matched=false AND is_realized=false): 6 kayıt → ₺696.190,94
            · Örnek: fe#1205 amount=178,58 ama amount_try=57.600,00 (322×);
                     fe#1401 amount=0,02 / amount_try=21.169,60
            · EUR kalemlerin %74'ünde (634/855) amount_try NULL → aging'de € yüz değeri TRY sanılıyor
Risk    : Kritik — şablon ölçütü "para hatası". Panel T-Hesap Cetveli, Nakit Koruma (runway) ve
          Yaşlananlar raporu bugün var olmayan ₺696.190,94'ü gösteriyor; yönetici bu sayıyla
          nakit planlıyor. Sapma sessiz (log/hata üretmez) ve her kısmi ödemede büyüyor.
Çözüm   : (1) `_upsert` alan sözlüğüne amount_try'ı dahil et (TRY → amount, döviz → ledger_rate
          ile hesapla veya açıkça None); (2) okuyucularda öncelik sırasını düzelt — TRY dalı önce;
          (3) tek seferlik onarım: UPDATE finance_events SET amount_try=amount WHERE currency='TRY'
          (efor: S)
Kapanış : SELECT count(*) FROM finance_events WHERE currency='TRY' AND amount_try IS NOT NULL
          AND abs(amount_try-amount)>0.01  →  0 ; ve "büyük tutarla upsert → küçük tutarla yeniden
          upsert → amount_try==amount" regresyon testi yeşil.
Durum   : ✔ KAPATILDI (R1 · 2026-07-25) — bayat TRY kaydı 11→0, hayalet ₺696.190,94→₺0.
          Yazıcı (_upsert) + okuyucu (t_account/runway) düzeltmesi canlıda; 7 regresyon
          testi, düzeltme geri alınarak kırmızıya döndürülüp kanıtlandı. Bkz. Kapanış Kaydı.
          2. göz Yüksek önermişti (gerekçe: defter bozulmuyor, hata okuma yolunda)
          → ANA DENETÇİ KRİTİK'TE TUTTU: canlı DB'de yönetim raporuna yansıyan gerçek para
            sapması ölçüldü ve şablon "para hatası"nı açıkça Kritik sayıyor.
```

```
[DR-001] uploads/ (284 MB · 1904 iş belgesi) hiçbir yedekte değil — v3'ten beri AÇIK, hacim 3× arttı
Dosya   : scripts/db-backup.sh (yalnız pg_dump) · .gitignore (uploads git-dışı)
Kanıt   : ✔ ANA DENETÇİ DOĞRULAMASI: `ls /var/backups/` → yalnız `sprenses-db`.
          `du -sh backend/uploads` → 284 MB / 1904 dosya (v3'te 91 MB / 1448 dosya).
          İçerik: banka ekstreleri, cari Excel'leri, çek/rezervasyon PDF'leri — DB'deki
          file_url kayıtları bu dosyalara işaret ediyor.
Risk    : Kritik — geri getirilemez mali belge kaybı. DB restore edilse bile her file_url dangling.
Çözüm   : db-backup.sh'e `tar czf uploads-<ts>.tgz backend/uploads` ekle (aynı rotasyon + bütünlük
          + off-site) VEYA EBS snapshot; restore tatbikatına dosya-varlık kontrolü ekle (efor: M)
Kapanış : uploads/ günlük yedeğe giriyor, off-site kopyalanıyor ve tatbikat örnek bir dosyayı
          açarak doğruluyor.
Durum   : ◐ BÜYÜK ÖLÇÜDE KAPANDI (R3 · 2026-07-25) — uploads artık günlük hardlink
          snapshot'ta (/var/backups/sprenses-uploads), restore tatbikatı yapıldı
          (5 belge checksum-özdeş, PDF açılıyor). OFF-SITE HÂLÂ YOK → tek disk
          kaybında kayıp sürüyor; tam kapanış DR-002'ye bağlı. | 2. göz: ✔ ONAYLANDI
```

```
[DR-002] Off-site yedek yok + tek EBS — DB, uploads ve yedeklerin kendisi aynı diskte
Dosya   : scripts/db-backup.sh:51-57 (S3 bloğu yalnız SPRENSES_BACKUP_S3 set ise çalışır)
Kanıt   : ✔ ANA DENETÇİ DOĞRULAMASI: `aws sts get-caller-identity` → "Unable to locate credentials"
          (IAM role yok, S3 bloğu hiç çalışmıyor). `df -h /` → tek nvme0n1p1 30G; altında
          /var/lib/pgsql (DB) + backend/uploads + /var/backups/sprenses-db (yedeklerin kendisi).
          Ek olarak dump'lar 0644 ve dizin 0755 → ayrıcalıksız her süreç tüm finans+PII DB'sini
          okuyabiliyor; şifreleme yok.
Risk    : Kritik — tek birim/instance kaybı, yanlış DROP veya ransomware üç kopyayı BİRDEN götürür.
Çözüm   : docs/modules/yedekleme.md runbook'unu uygula — farklı bölgede S3 (versioning + SSE +
          public-block) + minimal IAM role; en az DB dump + uploads off-site; dump izinlerini
          0600'e çek (efor: M)
Kapanış : Günlük DB+uploads farklı bölgedeki S3'e otomatik yükleniyor ve S3'ten restore en az
          bir kez uçtan uca doğrulandı.
Durum   : Açık — v3'ten devam | 2. göz: ✔ ONAYLANDI (Kritik)
          R3 notu: kod tarafı HAZIR (db-backup.sh DB+uploads'ı S3'e gönderiyor,
          enable-offsite-backup.sh + runbook duruyor). Eksik olan yalnız AWS'de bir
          kerelik provizyon (bucket + IAM role → EC2). Sunucudan yapılamaz.
```

### 🟠 YÜKSEK (8 — kök nedene göre birleştirilmiş)

| ID | Başlık | Kanıt | Efor | Doğrulama |
|---|---|---|:--:|:--:|
| **CICD-010**<br>(=TSTP-001<br>=DEBT-001) | **CI 2026-06-02'den beri hiç çalışmadı** — GitHub Actions depo düzeyinde KAPALI; 451 commit test edilmeden master'a gitti. 1.917 testlik takım ve `--cov-fail-under=60` eşiği fiilen dekoratif. | ✔ *ana denetçi:* `actions/permissions` → `{"enabled":false}`; `ci.yml/runs` → `total_count: 0` | **S** | RISK_DUSUR → Yüksek |
| **SEC-001**<br>(=CICD-011<br>=DOC-001) | **Depo PUBLIC + Stop hook her tur otomatik push ediyor** — CLAUDE.md:444'te varsayılan yönetici şifresi, test fixture'larında checksum-geçerli gerçek IBAN'lar, `docs/denetim/` altında kapanmamış zafiyetleri `dosya:satır` ile listeleyen 6 rapor. GitHub secret-scanning/push-protection da kapalı. | ✔ *ana denetçi:* `gh repo view` → `"visibility":"PUBLIC"`; `.claude/settings.json` Stop hook `git push origin master` | **S**\* | RISK_DUSUR → Yüksek |
| ~~**FIN-001**~~ ✔ | *(bkz. Kritik — 2. göz bu seviyede değerlendirdi)* — **KAPATILDI R1** | canlı DB | S | RISK_DUSUR → Yüksek |
| ~~**DB-001**~~ ✔ | **5 tablo alembic metadata'sının dışında** — `check.py` (checks, check_uploads), `ai_usage.py`, `ai_conversation.py` (ai_conversations, ai_messages) ne `models/__init__.py`'de ne `alembic/env.py`'de import ediliyor. Bir sonraki `alembic revision --autogenerate` bu beş tablo için **DROP TABLE** üretir — `checks` çekirdek finans tablosu. **→ KAPATILDI R1:** modeller kayda eklendi, autogenerate DROP önerisi 5→0, bekçi testi eklendi. | ✔ *ana denetçi:* `__init__` taraması → eksik: `check`, `ai_usage`, `ai_conversation`; `alembic/env.py`'de bu modüllerin import'u yok | **S** | RISK_DUSUR → Yüksek |
| ~~**ARCH-001**~~ ✔ | **Manuel kredi eşleştirme ortak `apply_credit_bank_match` uygulayıcısını atlıyor** — taksiti `is_paid` yapar ama anaparayı düşmez; geri alma ise koşulsuz iade eder → `remaining_amount` her eşleştir/geri-al turunda şişer. Kilit ve `is_paid` guard'ı da yok (çift eşleştirme mümkün). **→ KAPATILDI R2** | ✔ *ana denetçi:* matching.py:222-225 (anapara satırı yok) vs matching_service.py:950-951 (düşüyor); matching.py:675-676 (koşulsuz iade). <br>⚠️ **DÜZELTME (R2):** bu satırdaki "*canlıda Halk Leasing #446'da ₺22.963,23 sapma*" iddiası **YANLIŞTI** — aşağıya bkz. | **S** | RISK_DUSUR → Yüksek |

\* SEC-001'in "S" eforu deponun private yapılmasıdır (2 dakika). Sızmış sırların rotasyonu ayrıca M efordur.

> **Tek kök neden, tek bulgu:** `CICD-010 = TSTP-001 = DEBT-001` (Actions kapalı) ve `SEC-001 = CICD-011 = DOC-001` (PUBLIC depo) üç ayrı boyutta bağımsız olarak bulundu; burada birer kez sayıldı. Bağımsız üç ajanın aynı kökü bulması bulgunun gücünü artırır, sayısını değil.

### ⤵️ Doğrulamada düşürülen/çürütülen bulgular (rigor kanıtı)

2. göz **61 bulgunun** riskini düşürdü. Öne çıkanlar:

- **SEC-002** "API süreci NOPASSWD sudo ile keyfi komut çalıştırıyor" Yüksek→**Orta**. ✔ *Ana denetçi de doğruladı:* `backend/app/routers/system_server.py:167` endpoint'i `require_permission("system.server","use")` + `ALLOWED_SERVICES` whitelist'i ile korunuyor. Gerçek bulgu daha dar: `ec2-user` sudoers'ta `(ALL) NOPASSWD: ALL` taşıyor — endpoint değil, **host sertleştirmesi** sorunu.
- **CICD-012** "CI merge gate değil" Yüksek→**Düşük** (tek geliştiricili depoda branch protection'ın marjinal faydası; asıl sorun CICD-010).
- **FIN-002** (aging para birimi karıştırması) Yüksek→**Orta**: mekanizma kesin ama bugün pencerede döviz kalem yok — zamanlama belirsiz, etki henüz gerçekleşmemiş.
- **FIN-003/FIN-004**, **STAB-001..004**, **DB-002/003**, **API-001**, **FE-001/002**, **TSTC-001..003**, **OBS-001..004**, **JOBS-001..003**, **DR-003..005**, **SRV-001..003**, **PRIV-001/002**, **INT-001** → tamamı Yüksek→**Orta**.
- **OBS-003** (error_logs geçmişinin audit'siz silinmesi) Yüksek→**Düşük**; **DOC-004** Yüksek→**Düşük**.

---

## Çıktı 14 — Delta Raporu (v3 → v4)

| v3 Bulgu | v3 Risk | Durum | Kanıt |
|---|:--:|:--:|---|
| **SRV-001** TLS otomatik yenileme kapalı | 🔴 Kritik | ✔ **KAPATILDI** | `certbot-renew.timer` enabled+active; sertifika 16 Eki 2026 |
| **DR-001** uploads yedeksiz | 🔴 Kritik | ▼ **KÖTÜLEŞTİ** | Hâlâ yedeksiz; 91 MB → **284 MB** (+212%) |
| **DR-002** off-site yok + tek EBS | 🔴 Kritik | ● Devam | `aws sts` → kimlik yok; S3 bloğu hiç çalışmıyor |
| **CICD-002** CI merge-gate değil | 🟠 Yüksek | ▼ **KÖTÜLEŞTİ** | Gerçek daha kötü: CI **hiç çalışmamış** (0 koşu) |
| **CICD-001** APM/alerting yok | 🟠 Yüksek | ● Devam | requirements.txt'te Sentry/OTel yok; alarm kanalı yok |
| **DR-003** yedek OnFailure alarmı yok | 🟠 Yüksek | ● Devam | systemd unit'lerinde `OnFailure=` yok |
| **JOBS-001** arka plan iş görünürlüğü yok | 🟠 Yüksek | ▼ **KÖTÜLEŞTİ** | Somutlaştı: döviz cron'unun `amount_try` adımı **2 aydır her koşuda** sessizce çöküyor |
| **SECA-001** files.py IDOR | 🟠 Yüksek | ● Devam | `serve_file` hâlâ yalnız auth doğruluyor, modül izni/kaynak sahipliği değil |
| **FIN-002** dönem kilidi yok | 🟠 Yüksek | ◐ Kısmen | Altyapı geldi (`finance_period_locks` + `period_lock_service` + onay dalı) ama servis **UYARI modunda**, hiçbir mutasyonu bloklamıyor |
| **FIN-003** rezervasyon döviz yeniden değerleme | 🟠 Yüksek | ● Devam | `reservation_service.py` her senkronda güncel kurla yeniden değerliyor |
| **DB-002** sales tx_hash UNIQUE yok | 🟠 Yüksek | ◐ Kısmen | UNIQUE hâlâ yok; dedup uygulama belleğinde |
| **TEST-001** parser'lar testsiz | 🟠 Yüksek | ◐ Kısmen | `bank_parser` test edildi ✔; `cc_statement_parser` **%10 kapsamda** (4 banka, 643 satır) |
| **DOCS-001** bus factor = 1 | 🟠 Yüksek | ● Devam | 436/453 commit tek yazar; README/CODEOWNERS/onboarding yok |
| **DOCS-002** runbook yok | 🟠 Yüksek | ◐ Kısmen | `docs/modules/sunucu.md` + `yedekleme.md` kısmi kapsıyor; olay/gece-arıza runbook'u yok |
| **PERF-001** async-blocking | Orta | ◐ Kısmen | Sedna arka plana alındı ✔; yükleme/onay uçları hâlâ event-loop'ta |
| **I18N-001** naive datetime / process TZ | Orta | ◐ Kısmen | **TZ drop-in kuruldu ✔** (api+frontend); ama 5 cron unit'inin **3'ünde TZ ayarsız** (UTC) |
| **DB-001/I18N-002** C.UTF-8 collation | Orta | ● Devam | `datcollate=C.UTF-8`; Ç/Ö/Ş/İ ile başlayan kayıtlar Z'den sonra sıralanıyor |
| **API-004** Idempotency-Key yok | Düşük | ● Devam | Kritik mutasyon POST'larında yok |
| **FIN-001** para katmanı float | Düşük | ● Devam — **indirim geçerli** | Her op sonrası `round(...,2)` + DB kolonları NUMERIC(15,2) (`models/`'de 0 adet `Float`) → birikimli drift yok |
| UI: native `confirm()` · focus-ring sapması · `type="number"` para · paylaşılan bileşende teal-600 | Orta | ✔ **KAPATILDI** | 2026-06/07 UI çalışmaları; koddan doğrulandı |
| v3-sonrası altyapı iddiaları (4GB swap, earlyoom, deploy bellek bekçisi, TZ drop-in, ssh-key-audit, sedna-sync timer) | — | ✔ **DOĞRULANDI** | CLAUDE.md iddiaları gerçekle örtüşüyor — hepsi kurulu ve çalışıyor |

**▲ Yeni (v3'te hiç görülmemiş):** CICD-010 (Actions kapalı) · SEC-001 (PUBLIC depo) · FIN-001 (amount_try hayalet) · DB-001 (5 tablo metadata dışında) · ARCH-001 (manuel kredi eşleştirme) · JOBS döviz cron'u sessiz çökme.

---

## Çıktı 1 — Risk Matrisi (olasılık × etki)

| | **Etki: Yüksek** | **Etki: Orta** | **Etki: Düşük** |
|---|---|---|---|
| **Olasılık: Yüksek** | 🔴 **FIN-001** (zaten gerçekleşti) · 🟠 CICD-010 · SEC-001 · JOBS-001 (2 aydır çöküyor) | 🟠 ARCH-001 · FIN-006 (dönem kilidi) · LOG-001 | FIN-009 · I18N-005 |
| **Olasılık: Orta** | 🔴 **DR-001** · **DR-002** · 🟠 DB-001 | 🟠 SECA-001/PRIV-003 (IDOR) · FIN-002/003/004 · STAB-003/004 · DB-002/003 · OBS-001/002 | API-006/007 · FE-007/008 |
| **Olasılık: Düşük** | 🟠 INT-003 (VakıfBank sandbox→prod) | SCALE-002 · DEBT-002 (bus factor) · PRIV-001 (yurt-dışı aktarım) · INT-006 (yıl devri) | SEC-007/008 · INT-010 |

---

## Çıktı 15 — Hızlı Kazanımlar (efor ≤ 1 gün × etki Yüksek/Kritik)

| Sıra | ID | İş | Süre | Kazanç | Durum |
|:--:|---|---|:--:|---|:--:|
| 1 | **SEC-001** | Depoyu **private** yap (GitHub → Settings → Danger Zone) | **2 dk** | Canlı finansal sistemin saldırı haritası ve gerçek IBAN'lar kamuya kapanır | ⬜ Açık — *depo sahibinin yapması gerekir* |
| 2 | **CICD-010** | GitHub Actions'ı **etkinleştir** + boş commit ile ilk koşuyu yeşile al | ~~15 dk~~ **15 dk** (ön koşullar R4'te açıldı — öncesinde CI ilk adımda ölüyordu) | 1.927 test ilk kez koruyucu hâle gelir | ⬜ Açık — *depo sahibinin yapması gerekir* |
| 3 | **FIN-001** | `UPDATE finance_events SET amount_try=amount WHERE currency='TRY'` + `_upsert`'e alan ekle | **1-2 sa** | Panel/runway/aging'den **₺696.190,94 hayalet** silinir | ✔ **R1** |
| 4 | **DB-001** | `check`, `ai_usage`, `ai_conversation`'ı `models/__init__.py` + `alembic/env.py`'ye ekle | **10 dk** | Bir sonraki autogenerate'in `DROP TABLE checks` üretmesi engellenir | ✔ **R1** |
| 5 | **JOBS (döviz)** | `amount_try` adımındaki `Multiple rows were found` hatasını düzelt | **1 sa** | 2 aydır yarım çalışan kur güncellemesi tamamlanır | ✔ **R1** |
| 6 | **ARCH-001** | `match_credit_payment`'ı `apply_credit_bank_match`'e bağla ~~+ canlı `remaining_amount` onarımı~~ | **2-3 sa** | Kredi kalan borcu sapması durur (canlı onarım GEREKMEDİ — bkz. R2) | ✔ **R2** |
| 7 | **DR-003** | 6 systemd unit'ine `OnFailure=` + basit e-posta/push alarm servisi | **1 sa** | Sessiz yedek/cron çökmesi biter | ✔ **R3** (5 iş) |
| 8 | **DR-001** | `db-backup.sh`'e uploads ~~tar'ı~~ **hardlink snapshot'ı** ekle | **30 dk** | 285 MB mali belge yedeğe girer | ✔ **R3** |
| 9 | **SEC-007/008** | `UserUpdate` parola min-uzunluk + zayıf `SECRET_KEY`'de başlatmayı durdur | **20 dk** | Parola politikası tutarlı hâle gelir | ⬜ Açık |

**Toplam ≈ 1 iş günü** → 2 Kritik'in biri tamamen, diğeri kısmen kapanır; 8 Yüksek'in 5'i kapanır.

> **R1+R2+R3 ilerleme (2026-07-25):** 6/9 kapandı (madde 3-4-5-6-7-8) → 1 Kritik tam + 1 Kritik kısmi + 4 Yüksek. Kalan 6'nın
> **ikisi kod işi değil**: SEC-001 ve CICD-010 GitHub depo ayarıdır, yalnız depo sahibi
> yapabilir — ve ikisi de listenin en yüksek etkili maddeleridir (toplam süre 17 dakika).

---

## Çıktı 9 — 30 / 60 / 90 Günlük Plan

### İlk 30 gün — "Güvenceyi kur"
1. **Hızlı Kazanımlar 1-9'un tamamı** (yukarıda, ~1 gün).
2. **DR-002 off-site**: IAM role + farklı bölgede S3 (versioning + SSE + public-block); DB + uploads günlük yükleme; dump izinleri 0600.
3. **Restore tatbikatı**: `db-restore.sh`'i koş, satır sayısı + uploads dosya varlığı doğrula, sonucu `docs/` altına tarihli yaz. **RPO/RTO'yu yazılı tanımla.**
4. **Sızmış sırların rotasyonu** (SEC-001 devamı): depo public kaldığı sürece görünmüş olan her şey — admin şifresi, varsa API anahtarları — döndürülür.
5. **CI'yı gate'e çevir**: Actions açıldıktan sonra `svelte-check`'i CI'ya ekle (yerelde 0 hata → bedava kazanç).

### 31-60 gün — "Görünürlüğü kur"
6. **Alerting katmanı**: mevcut SMTP + push altyapısını operasyonel alarma bağla — `OnFailure=`, disk %80 eşiği, kur bayatlığı (>24 sa), TLS bitişine 21 gün.
7. **`/api/health`'i gerçek yap** (DB + Sedna tüneli kontrolü) ve nginx/deploy doğrulamasına bağla.
8. **Frontend hata yakalama**: `hooks.client.ts` + `+error.svelte` → backend `error_logs`; `logger.error` çağrılarını da `error_logs`'a köprüle (LOG-001).
9. **Dönem kilidini bloklayıcı yap** (FIN-006) — en azından kapalı aya yazan mutasyonlarda uyarı + audit.
10. **`cc_statement_parser` testleri** (4 banka × gerçek örnek PDF) — TEST-001'in kalan yarısı.

### 61-90 gün — "Sürdürülebilir kıl"
11. **Bus factor**: README + CODEOWNERS + sıfırdan-kurulum runbook'u; `/etc`'deki 17 elle-yapılmış konfigi repoya al (IaC'nin ilk adımı).
12. **KVKK paketi**: bu rapordaki envanteri temel alarak retention politikası + otomatik imha; Anthropic yurt-dışı aktarımı için aydınlatma/dayanak.
13. **Optimistik kilit** (STAB-004) — en azından finans kayıtlarında `version` kolonu.
14. **Collation** (I18N-003/DB-006): ICU ile Türkçe sıralama; ~10 endpoint etkilenir.
15. **Ölü kod temizliği**: Amadeus (kapanmış sağlayıcı) + 1.493 satır uyuyan entegrasyon yüzeyi.

---

## Çıktı 17 — Arka Plan İşleri Envanteri

| İş | Ne yapar | Zamanlama (Istanbul) | Process TZ | Son başarılı | Overlap | Persistent | Alarm |
|---|---|---|:--:|---|:--:|:--:|:--:|
| `sprenses-db-backup` | pg_dump -Fc + bütünlük + 30 rotasyon | Günlük 03:00 | ⚠ UTC | 24 Tem ✔ | yok (risk düşük) | ✔ | ❌ |
| `sprenses-sedna-sync` | 6 adım: cari/IBAN/çek/düzenli/maaş/banka mutabakat | 09-21 arası 2 saatte bir :15 | ✔ Istanbul | 24 Tem 21:15, 6/6 ✔ | ❌ (UI `sync-all` ile çakışır) | ✔ | ❌ + **hata olsa da exit 0** |
| `sprenses-sales-sync` | Satış faturası + tahsilat + avans + acente köprüsü | 08-22 arası 2 saatte bir :15 | ⚠ UTC | 24 Tem 22:15 ✔ | ❌ | ✔ | ❌ + exit 0 |
| `sprenses-exchange-rates` | TCMB günlük+saatlik kur → `exchange_rates` → `amount_try` | Hafta içi 10:00-16:15, 28 koşu/gün | ⚠ UTC | ~~`amount_try` adımı 2 aydır HER koşuda çöküyor~~ → ✔ **R1'de düzeltildi** | yok | ✔ | ❌ (WARNING'e düşürülmüş, exit 0) |
| `sprenses-ai-digest` | 7 günlük yaklaşan ödeme özeti (in-app + push) | Günlük 08:00 | ✔ Istanbul | 24 Tem, 8 kullanıcı ✔ | gerekmiyor | ✔ | ❌ (dolaylı) |
| `ssh-key-audit` (.timer+.path) | Tünel anahtarlarını `command=`+`permitopen=` ile sertleştirir | Günlük + dosya değişiminde | — | 24 Tem ✔ | idempotent | ✔ | ❌ |
| `cron_weekly_push.py` | Haftalık push bildirimi | **ZAMANLANMAMIŞ** — unit yok, cron paketi kurulu değil | — | Hiç | — | — | ❌ + doküman çalıştığını iddia ediyor |
| YKB/QNB/Garanti ekstre cron'ları | Banka API'lerinden hareket çekme | Zamanlanmamış — **bilinçli** (kimlikler .env'de yok) | — | — | — | — | *bulgu değil* |

**Öne çıkan:** Kur cron'u her koşuda `WARNING [amount_try] Güncelleme hatası: Multiple rows were found when exactly one was required` yazıyor, çıkış kodu 0 dönüyor, systemd "başarılı" sayıyor. ✔ *ana denetçi journalctl ile doğruladı.* Bu, FIN-001'in ikinci bacağıdır.

> **R1 (2026-07-25):** Kök neden `.scalar()`'ın çok satır dönen bir sorguda çağrılmasıydı —
> filtre `date <= target_date` olduğundan canlıda **1301 EUR satırı** dönüyordu. `.limit(1)`
> eklendi, uyarı bitti. **Ama alarm boşluğu KAPANMADI:** iş hâlâ hata durumunda `exit 0`
> dönüyor ve `OnFailure=` yok — yani bir sonraki sessiz çökme yine aylarca fark edilmez.
> Bu satırın "Alarm ❌" sütunu bilerek kırmızı bırakıldı (DR-003 / JOBS-002 açık).

---

## Çıktı 13 — Üçüncü-Parti Entegrasyon Dayanıklılık Matrisi

| Servis | Durum | Timeout | Retry | Circuit-breaker | Degradation | Idempotency | Test |
|---|---|:--:|:--:|:--:|---|:--:|:--:|
| **Sedna SQL Server** | AKTİF | 10 sn login / 60-180 sn sorgu | ❌ | ❌ | ✔ Graceful (503, diğer adımlar sürer) | ✔ (rec_id + tx_hash) | kısmi |
| **TCMB kur** | AKTİF | 15 sn | ❌ (3 kademeli kaynak fallback var) | ❌ | ✔ carry-forward | ✔ (tarih+ccy upsert) | ❌ **hiç** |
| **Anthropic Claude** | AKTİF | ❌ açık tanım yok (SDK: 600 sn read) | SDK varsayılanı 2 | ❌ | ✔ 503/502 | onay akışına giriyor | kısmi |
| **SMTP** | AKTİF | 20 sn | ❌ | ❌ | ⚠ **sessiz** — False döner, kullanıcı bilmez | ❌ | — |
| **Web Push (VAPID)** | AKTİF | 10 sn | ❌ | ◐ (abonelik pasifleştirme) | ✔ arka plan | ✔ | — |
| **VakıfBank** | ⚠ **SANDBOX kimliğiyle üretime yazma yolu açık** | 20 sn | ❌ | ❌ | ✔ 503 | ✔ tx_hash | ✔ 19 test |
| QNB / Garanti / YKB | Uykuda (kimlik yok) | 60/60/30 sn | ❌ | ❌ | ✔ | ✔ | ✔ 8/8/4 test |
| **Amadeus** | ☠ **ÖLÜ** — sağlayıcı 17.07.2026'da kapandı, kod duruyor | 15 sn | ❌ | ❌ | ⚠ mock veriye düşüyor | — | ❌ |

**Genel desen:** Timeout disiplini iyi, **retry ve circuit-breaker hiçbir entegrasyonda yok**, idempotency olgun. Kritik boşluk: TCMB ayrıştırıcısının hiç testi olmaması (kur = tüm EUR/TRY dönüşümlerinin tek kaynağı) ve bayatlık alarmının bulunmaması.

---

## Çıktı 11 — KVKK / Kişisel Veri Envanteri

| Tablo | PII alanları | Tür | Kayıt | Saklama süresi |
|---|---|---|---:|---|
| `reservations` | guests, nation, voucher | Misafir ad-soyad, uyruk | 18.411 | **TANIMSIZ** |
| `audit_logs` | user_id, ip_address, details | IP + davranış izi | 25.038 | **TANIMSIZ** (hiç silinmemiş, en eski 24 Şub) |
| `personnel` | full_name, employee_code, title, access_token | Çalışan kimlik + cihaz token'ı | 230 | **TANIMSIZ** |
| `attendance_logs` | personnel_id, punched_at | Çalışma davranışı izleme | 16 | **TANIMSIZ** (İş mevzuatı 5 yıl önerir) |
| `messages` | content, file_url | **Haberleşme gizliliği (Anayasa m.22)** | 157 | **TANIMSIZ** — soft-delete, içerik kalıcı |
| `dividend_shareholders/payments` | name, gross/stopaj/net | Gerçek kişi geliri — yüksek hassasiyet | 12 ortak | **TANIMSIZ** (vergi mevzuatı 5-10 yıl) |
| `vendor_bank_accounts` + `finance_events.iban` | iban, hesap_adi | Kişisel finansal veri | 268 | **TANIMSIZ** |
| `push_subscriptions` | endpoint, p256dh, user_agent | Cihaz parmak izi | 259 | **TANIMSIZ** (pasifler temizlenmiyor) |
| `notifications` | title, body | Finansal tutar/cari adı içerir | 1.962 | **TANIMSIZ** |
| `ai_conversations/messages/usage` | content, cost_usd | **YURT DIŞI AKTARIM (Anthropic)** | 1 konuşma | **TANIMSIZ** |
| `users` | email, hashed_password (bcrypt ✔) | Kimlik + auth sırrı | 10 | Hesap ömrü (CASCADE ✔) |
| `error_logs` | ip_address, path, traceback | IP + istek yolu | 0 (boş) | **TANIMSIZ** |

**Boşluklar:** ① Hiçbir tabloda **retention/otomatik imha yok**. ② Aydınlatma metni ve **açık rıza kaydı sistemde hiç yok** (özellikle `personnel` için kritik). ③ **Anthropic'e yurt dışı aktarımın KVKK Md.9 dayanağı yok** — `ai_service.py` cari adı/finansal veri gönderiyor. ④ Veri ihlali müdahale süreci (72 saat) yazılı değil. ⑤ Hassas veri **okuma/dışa aktarma** audit'e girmiyor (yalnız yazma). ⑥ Yedekler şifresiz ve 0644. ⑦ Misafir (ilgili kişi) silme talebi karşılanamıyor — veri serbest metin.

**Güçlü yön:** Veri minimizasyonu fiilen uygulanmış — `personnel.phone` %0 dolu, `vendors.contact_person/phone/email` %0 dolu; biyometrik veri yerine cihaz token'ı kullanılmış.

---

## Çıktı 12 — Felaket Kurtarma (DR) Raporu

| Soru | Cevap |
|---|---|
| Otomatik DB yedeği var mı? | ✔ Günlük 03:00, `pg_dump -Fc`, bütünlük doğrulamalı, 30 rotasyon, kesintisiz |
| Yedek izleniyor mu? | ❌ `OnFailure=` yok — sessiz kesinti haftalarca fark edilmez |
| Kapsam tam mı? | ❌ DB ✔ · **uploads ❌** (284 MB) · **.env ❌** · **TLS anahtarları ❌** · **17 systemd/nginx konfigi ❌** |
| Off-site? | ❌ Yok — IAM role yok, S3 bloğu hiç çalışmadı |
| Şifreli mi? | ❌ Düz `pg_dump`, dosya izni 0644 |
| RPO / RTO | ✔ **R5'te tanımlandı** — RPO ≤ 24 sa · RTO ≤ 30 dk (aynı makine) · makine kaybında **BELİRSİZ** (off-site yok) |
| Restore tatbikatı | ✔ **R5** — koşuldu ve KAYIT ALTINA ALINDI; DB satır sayıları üretimle birebir, uploads örneklemi 5/5 md5-özdeş. Sonraki vade 2026-10-25 |
| PITR / WAL arşivleme | ❌ Yok — gün-içi kayıp kaçınılmaz (en fazla 24 sa) |
| SPOF | 🔴 Tek EC2 · tek EBS · tek DB — DB + uploads + yedekler **aynı diskte** |

**Ransomware / yanlış DROP / disk kaybı senaryosu bugün:** Yedekler de gittiği için **kurtarma yok**. Yalnız git deposundaki kod kalır (DB verisi ve 1904 mali belge kalıcı kayıp).

---

## Çıktı 5 — Dokümantasyon Drift Raporu

| İddia (CLAUDE.md / docs) | Gerçek | Durum |
|---|---|:--:|
| "CI her push/PR'da pytest + vitest çalıştırır" | **0 koşu**, Actions kapalı | ▼ Yanlış |
| "1220+ test (pytest), ~%66 satır kapsamı" | 1.917 test, %77 kapsam | ◐ Bayat (iyi yönde) |
| "Tablolar (85)" | 52 model dosyası, 5'i registry dışında — sayım doğrulanamıyor | ◐ Şüpheli |
| `docs/api-haritasi.md` | Canlı API yüzeyinin **%24'ü katalogda yok** (AI + VakıfBank modülleri hiç yok, 1 path yanlış) | ▼ Drift |
| `docs/modules/finans-mimarisi.md` izin kodları | `finance.advances` / `finance.exchange_rates` — **gerçek kodlar farklı** (`finance.avanslar` / `finance.doviz`) | ▼ Yanlış |
| `finans-mimarisi.md:302,315` "haftalık push çalışıyor" | `cron_weekly_push.py` **hiç zamanlanmamış** | ▼ Yanlış |
| `.env.example` | 58 config ayarından **9'u belgeli**; fiilen kullanılan 2 anahtar eksik | ▼ Eksik |
| v3-sonrası altyapı iddiaları (swap/earlyoom/TZ/ssh-audit/sedna-timer) | Hepsi kurulu ve çalışıyor | ✔ **Doğru** |
| systemd TZ drop-in "process TZ'si zorlanır" | api + frontend ✔; **5 cron unit'inin 3'ünde TZ ayarsız** | ◐ Kısmen |

**Drift otomatik ölçülmüyor** — CI'da kod↔doküman tutarlılık testi yok (DOC-003).

---

## Çıktı 2 — Eksik Test Senaryoları

1. `cc_statement_parser` — 4 banka × gerçek örnek PDF (şu an **%10 kapsam**, 643 satır)
2. TCMB ayrıştırıcısı — XML şeması değişimi, boş yanıt, carry-forward davranışı (**hiç test yok**)
3. `finance_events.amount_try` tazeleme — büyük→küçük upsert regresyonu (FIN-001 kapanış testi)
4. Manuel kredi eşleştir→geri al turu — `remaining_amount` değişmemeli (ARCH-001)
5. Kısmi eşleşme kabulü — planlı yükümlülüğün tamamı silinmemeli (FIN-003)
6. Alembic metadata bütünlüğü — "her `__tablename__` `Base.metadata`'da mı" AST/runtime testi (DB-001)
7. Finansal uç durumlar: kuruş yuvarlama (ROUND_HALF_UP vs banker's), ay sonu 28/29/30/31, yıl geçişi, çok-para-birimli FIFO
8. WebSocket uçtan uca — polling yasağının dayandığı tek mekanizma, **hiç test edilmiyor**
9. Türkçe normalizasyon — `İSTANBUL` ↔ `istanbul` eşleşmesi (cari eşleştirme = para yolu)
10. Gün sınırı / TZ — "bugünkü tahsilatlar" İstanbul gece yarısında doğru mu
11. Rota/sayfa testleri + E2E (Playwright) — 38.570 satırlık frontend sayfa katmanı **sıfır testli**
12. `ai.asistan` 8 HTTP endpoint'i — izin geçidi doğrulanmayan tek modül

## Çıktı 3 — Eksik Test Kullanıcıları / Roller

Non-admin izin-matrisi fixture'ları var ✔ ancak: `system.error_logs`'a **yalnız Admin** sahip (tek kullanıcı) → çok-rollü hata görünürlüğü test edilemiyor; `ai.asistan` için rol fixture'ı yok.

## Çıktı 4 — Eksik Mock Veri Setleri

Gerçek banka PDF örnekleri (4 banka KK ekstresi), TCMB XML varyantları (tatil/eksik kur/şema değişimi), Sedna şema-değişimi senaryosu. **Açık ağ engeli (network guard) yok** — dış API izolasyonu "her test patch'lemeyi hatırladığı için" çalışıyor (kırılgan).

## Çıktı 7 — Performans İyileştirme Listesi

1. `GET /finance/cariler/payment-schedule` her okumada tüm cari FIFO'sunu yeniden hesaplıyor **ve `finance_events`'e yazıyor** (salt-görme izniyle mutasyon — API-003)
2. Yükleme/onay `async def` uçları ağır senkron işi event-loop'ta koşuyor → tek worker'da tüm API donuyor
3. PG slow-query kapalı, `pg_stat_statements` kurulu değil → **sıfır gecikme görünürlüğü**
4. Onay bekleyenler listesinde N+1 + Python'da sayfalama
5. Satış FIFO motoru her cache-miss'te tüm fatura+tahsilat tablolarını belleğe alıyor
6. Threadpool (40) > DB havuzu (35) → yoğunlukta `pool_timeout` 500'leri
7. Çekler sayfası 500 kayıt tek istekte çekiyor, grup toplamları kırpılmış veriden hesaplanıyor
8. Krediler sayfası kart ekstrelerini sıralı (waterfall) çekiyor

---

## Çıktı 10 — Genel Proje Notu

| | Değer |
|---|---|
| **v4 genel not** | **55 / 100** (aritmetik ortalama 5,52) |
| Karşılaştırılabilir v3 | 59 / 100 |
| Çekirdek ürün katmanı (1-10, 20) | **6,1** / 10 |
| Operasyon/uyum katmanı (11-19, 21-23) | **4,9** / 10 |
| **90 gün hedefi** | **72 / 100** (plandaki hedef skorların ortalaması) |
| Hızlı Kazanımlar uygulanırsa (1 gün) | ≈ **61 / 100** |

**Neden 55:** Ürün katmanı gerçekten iyi — katmanlı mimari zorlanıyor (AST bekçileri), onay/dual-write ortak-service deseni olgun, RBAC + HttpOnly cookie disiplini sağlam, tasarım sistemi tutarlı, finansal çekirdek (idempotent `finance_events`, para-birimi-ayrık FIFO, NUMERIC(15,2)) doğru kurulmuş. Notu çeken şey **bu iyi ürünün etrafında güvence katmanının olmaması**: test var ama koşmuyor, yedek var ama eksik, log var ama alarm yok, doküman var ama doğrulanmıyor. Sonuç bu denetimde somutlaştı — 2 ay boyunca sessizce çöken bir cron ve yönetim raporlarında duran 696 bin TL.

---

## Çıktı 18 — Kapanış Kriterleri

| ID | Kapanmış sayılır ki… | Durum |
|---|---|:--:|
| **FIN-001** | `SELECT count(*) ... WHERE currency='TRY' AND abs(amount_try-amount)>0.01` = **0** + upsert regresyon testi yeşil | ✔ **R1** — ölçüm 0, 7 test yeşil |
| **DB-001** | `alembic revision --autogenerate` boş diff üretiyor (hiçbir `DROP TABLE` yok) + metadata bütünlük testi yeşil | ✔ **R1** — DROP 5→0, 2 test yeşil |
| **JOBS (döviz)** | `journalctl -u sprenses-exchange-rates` son 10 koşuda `[amount_try]` uyarısı yok | ✔ **R1** — uyarı yok, sorgu yan-yana kanıtlandı |
| **DR-001** | uploads/ günlük yedekte, off-site kopyada ve tatbikatta bir dosya açılarak doğrulanmış | ◐ **R3** — günlük yedek ✔ · tatbikat ✔ · off-site ✗ |
| **DR-002** | DB+uploads farklı bölgedeki S3'e otomatik yükleniyor ve **S3'ten restore bir kez uçtan uca** yapılmış | ⬜ Açık |
| **CICD-010** | `actions/permissions` → `enabled:true` **ve** en son `ci.yml` koşusunun conclusion'ı `success` | ⬜ Açık — **ön koşullar R4'te kapatıldı** (bootstrap 5/5, taze DB'de 1927 test yeşil); kalan adım depo ayarı |
| **SEC-001** | `gh repo view` → `"visibility":"PRIVATE"` **ve** public dönemde görünmüş kimlik bilgileri döndürülmüş | ⬜ Açık |
| **ARCH-001** | Router `apply_credit_bank_match` çağırıyor + eşleştir/geri-al turu sonrası `remaining_amount` değişmiyor (test) + canlı sapma 0 | ✔ **R2** — router çağırıyor ✔ · 5 test yeşil (geri alınca kırmızı) ✔ · canlı sapma zaten yoktu (iddia düzeltildi) |
| **DR-003** | Bir test hatası kasten tetiklendiğinde alarm kanalından bildirim geliyor | ✔ **R3** — tetiklendi, error_logs + e-posta geldi |

---

## Ek — Boyut Bazlı Güçlü Yönler (kanıtlı)

Denetim yalnız sorun listelemez; şunlar **koddan doğrulandı** ve korunmalıdır:

- **Paketler-arası `router→router` import'u tamamen kapalı** ve `services/` hiç router import etmiyor — tek yön korunuyor (`grep -rn "from app.routers" backend/app/services/` → 0 sonuç).
- **Onay/dual-write ortak-service deseni**: 16 executor handler'ının neredeyse tamamı router ile aynı `services/*_service.py` fonksiyonunu çağırıyor; `tests/test_approval_system.py:1647` AST testi handler kapsamını statik zorluyor.
- **Fabrika deseni**: 7 planlı gelir/gider modülü tek router fabrikası + tek executor closure'ı + tek frontend bileşeniyle üretiliyor.
- **Para tipi disiplini**: `models/`'de **0 adet `Float`** — tüm para kolonları `NUMERIC(15,2)`; her operasyon sonrası `round(...,2)` → v3'ün float endişesi geçerli olarak Düşük'te kaldı.
- **Dedup/idempotency**: Sedna içe aktarmalarında `rec_id` partial unique + `tx_hash` + upsert deseni olgun.
- **Deploy scripti olaydan öğrenmiş**: `flock` tekilleştirme + build öncesi RAM/swap headroom bekçisi (2026-07-06 ve 07-18 olaylarının doğrudan ürünü).
- **Gizli bilgi hijyeni**: depoda izlenen tek ortam/anahtar dosyası yok; `PreToolUse` bekçisi zorla-ekleme (force-add) yolunu kapatıyor — *bu denetim sırasında bekçi fiilen tetiklendi ve çalıştığı doğrulandı.*
- **CLAUDE.md'nin altyapı iddiaları doğru çıktı** — swap/earlyoom/TZ drop-in/ssh-key-audit/sedna-timer hepsi kurulu (iddia ≠ gerçek kontrolü geçildi).
- **UI tasarım sistemi**: v3'te açık olan native `confirm()`, focus-ring sapması, para girişinde `type="number"`, paylaşılan bileşende `teal-600` sapmalarının tamamı kapatılmış.

---

*Denetim yöntemi: 23 bağımsız boyut denetçisi paralel çalıştı; her Kritik/Yüksek bulgu, bulguyu çürütmekle görevlendirilmiş bağımsız bir 2. göz tarafından koddan/sistemden yeniden incelendi (61 düşürme). Ana denetçi 6 headline bulguyu canlı üretim sisteminde ayrıca bizzat doğruladı (✔ işaretli). Ham ajan çıktıları: `wf_95109cbd-55f` ve `wf_75846a1f-8b4` transcript dizinleri.*
