# Yedekleme Modülü

> ## ⚠️ İki ayrı yedek vardır — karıştırma
> - **KOD yedeği** (bu modül + Stop hook): kaynak kodu git/GitHub'a yedekler. **Veriyi (DB) YEDEKLEMEZ.**
> - **VERİTABANI yedeği** (aşağıdaki "Veritabanı Yedeği" bölümü): `pg_dump` ile finansal/cari/rezervasyon/PDKS verisini yedekler.
>
> Bu ayrım kritik: 2026-06-21 denetimi (D15-1, **tek Kritik bulgu**) bu modülün yalnız kodu yedeklediğini, DB için
> hiçbir otomatik yedek olmadığını saptadı → 2026-06-22'de DB yedeği eklendi (aşağıda).

## Veritabanı Yedeği (pg_dump) — 2026-06-22 (D15-1)

Otomatik günlük PostgreSQL yedeği. **Bu modülden (UI) bağımsız**, altyapı seviyesinde çalışır.

- **Script:** `scripts/db-backup.sh` — `pg_dump -Fc` (sıkıştırılmış custom format) → `/var/backups/sprenses-db/sprenses-<ts>.dump`. Atomik yazım (`.tmp`→`mv`), **bütünlük doğrulaması** (`pg_restore --list`), **rotasyon** (son `SPRENSES_BACKUP_KEEP`=30 yedek). DB şifresi `.env`'deki `DATABASE_URL`'den (argümanda parola yok, `PGPASSWORD`).
- **Zamanlama:** `sprenses-db-backup.timer` (systemd) — her gün **03:00 Europe/Istanbul**, `Persistent=true` (kaçan koşum açılışta çalışır). Servis: `sprenses-db-backup.service` (`User=ec2-user`, oneshot).
- **Geri yükleme / tatbikat:** `scripts/db-restore.sh`
  - `scripts/db-restore.sh` → en son yedeği **geçici DB'ye** yükler + kritik tablo satır sayılarını basar + geçici DB'yi siler (**restore tatbikatı** — "yedek var ≠ çalışıyor"). Çeyrekte bir çalıştırılmalı.
  - `scripts/db-restore.sh <dump> sprenses` → **ÜRETİME** geri yükler (elle `EVET` onayı; `--clean --if-exists`, owner=sprenses md5 ile).
- **Off-site (S3):** aşağıdaki **"Off-site (S3) — DR-002"** bölümüne bakın. Yerel yedek; yanlış DROP/DELETE, app bug ve veri bozulmasına karşı korur ama **tek-disk kaybına karşı KORUMAZ**.
- **Not:** `archive_mode=off` (PITR yok); küçük DB (~44 MB) için günlük tam-dump yeterli. PITR/RDS orta-vade.
- **İzinler (2026-07-25, denetim DR-002):** script `umask 077` ile çalışır, dump'lar `0600`, dizin `0700`. Öncesinde `0644`/`0755` idi → tüm finans+KVKK verisi ayrıcalıksız her sürece okunabilirdi.

## Yüklenen Dosya Yedeği (uploads/) — 2026-07-25 (denetim DR-001)

DB geri yüklense bile bu dosyalar olmadan her `file_url` **dangling** kalır: banka ekstreleri,
cari Excel'leri, çek/rezervasyon/kontrat PDF'leri = geri getirilemez mali belge. Denetim
2026-07-05'te bunu Kritik işaretledi; hacim 91 MB → **285 MB**'a çıktı ve hâlâ hiçbir yedekte
değildi.

- **Kaynak:** `backend/uploads/` (285 MB · 1969 dosya) → **`/var/backups/sprenses-uploads/<ts>/`**
- **Yöntem — hardlink snapshot** (`rsync -a --delete --link-dest=<önceki>`): değişmeyen dosya
  ek yer kaplamaz. **Ölçüldü:** iki snapshot toplam **285 MB** (570 değil), örnek dosyada
  `links=2`. 30 snapshot ≈ tek kopya + günlük değişimler.
  - **Neden tar.gz DEĞİL:** içeriğin çoğu zaten sıkıştırılmış (1259 xls · 411 pdf · 113 jpg) →
    tar.gz ~250 MB ve 30 günlük tam kopya ≈ **7,5 GB** olurdu (30 GB diskte kabul edilemez).
  - **Ek fayda:** her snapshot TAM bir dizin gibi görünür → restore = doğrudan kopyala,
    çıkarma adımı yok.
- **Bütünlük:** kaynak ↔ snapshot dosya sayısı karşılaştırılır; uyuşmazlıkta uyarı.
- **Atomiklik:** `.tmp`'ye yazılır, başarılıysa `mv` → yarım snapshot tarih adını almaz.
- **Rotasyon:** `SPRENSES_UPLOADS_KEEP` (varsayılan 30).
- **Kapatma:** `SPRENSES_SKIP_UPLOADS=1` (yalnız DB yedeği).
- **Restore tatbikatı (2026-07-25 yapıldı):** 5 rastgele mali belge kaynak↔snapshot
  **checksum-özdeş**; PDF `%PDF-` imzasıyla açılıyor.
- **Disk bekçisi:** boş alan `SPRENSES_MIN_FREE_MB` (varsayılan 2000) altındaysa yedek
  **alınmaz ve hata verir** — disk dolması PostgreSQL'i durdurur; yedek işi koruduğu sistemi
  öldürmemeli.
- **Off-site:** `SPRENSES_BACKUP_S3` set ise snapshot `aws s3 sync` ile `<prefix>/uploads/`
  altına **tam ayna** olarak gider (günlük tar.gz DEĞİL — gerekçe DR-002 bölümünde).
- **İzin modeli:** koruma **dizin seviyesinde** — `/var/backups/sprenses-uploads` `0700`.
  Snapshot içindeki dosyalar kaynak izinlerini korur (`rsync -a`), bazıları dünya-okunur;
  **bilinçli tercih**: `--chmod` ile izin değiştirmek hardlink'i bozar (izni farklı dosya
  önceki snapshot'a link'lenemez → dedup çöker, 30 snapshot yeniden 7,5 GB olur). Ayrıcalıksız
  süreç `0700` dizinden içeri giremediği için koruma seviyesi dump'larla aynıdır.

> **DR-001 durumu:** yerel günlük yedek + restore tatbikatı ✔ · off-site **kod tarafı hazır ve
> testli**, AWS provizyonu bekliyor (aşağıdaki DR-002 bölümü). Off-site kurulduğu anda uploads
> da otomatik aynalanır — `db-backup.sh` aynı koşumda `aws s3 sync` ile gönderir.

## Zamanlanmış İş Başarısızlık Alarmı — 2026-07-25 (denetim DR-003 / JOBS-002)

Hiçbir işte `OnFailure=` yoktu; bir iş çökerse yalnız journald'a düşüyor, kimse haber almıyordu.
Denetim bunu canlıda somut buldu: döviz cron'unun `amount_try` adımı **2 ay boyunca her koşuda**
sessizce çöktü ve fark edilmedi.

- **Script:** `scripts/systemd-failure-alert.py` — başarısız birimin son 40 log satırını toplar →
  (1) `error_logs`'a **CRITICAL** kayıt (Sistem ▸ Hata Logları ekranında görünür),
  (2) sistem izinli aktif kullanıcılara e-posta.
- **Alıcı seçimi İZNE dayanır** (`system.server` veya `system.error_logs` view), rol ADINA değil.
  *İlk sürüm `u.role.name == "Admin"` bakıyordu; ilişkinin gerçek adı `role_rel` olduğundan
  `getattr` sessizce `None` dönüyor ve alarm HİÇ e-posta göndermiyordu — kapatmaya çalıştığı
  sessiz-hata sınıfının aynısı. Test sırasında yakalandı.*
- **Şablon birim:** `scripts/systemd/sprenses-alert@.service` → `/etc/systemd/system/`
- **Bağlantı:** `scripts/systemd/dropins/*-onfailure.conf` (5 iş: db-backup · exchange-rates ·
  sedna-sync · sales-sync · ai-digest). Kurulum: `scripts/systemd/dropins/README.md`.
- **Kuru çalışma:** `scripts/systemd-failure-alert.py <birim> --dry-run` — yazmaz/göndermez,
  alıcı çözümlemesini gösterir.
- **Uçtan uca doğrulandı (2026-07-25):** bilerek başarısız bir birim (`/bin/false`) tetiklendi →
  systemd alarmı otomatik çalıştırdı → `error_logs` kaydı düştü → e-posta gönderildi.

- **Alıcı tekilleştirme:** e-posta artık benzersiz değil (aşağıya bkz) → aynı adresi taşıyan
  iki hesap tek e-posta üretir (küçük harf + trim'li karşılaştırma).

> **✔ Çözüldü (2026-07-25):** İlk kurulumda `admin@sprenses.com` teslim edilemiyordu
> (`550 5.1.1 User unknown in virtual mailbox table`) — alarmın yarısı ölüydü. Kullanıcı
> kararıyla `admin` hesabının e-postası da `finans@sideprenseshotel.com` yapıldı; bunun için
> `users.email` UNIQUE kısıtı kaldırıldı (migration `e8f2b6d4a9c3`). Artık her iki alarm
> alıcısı da çalışan tek bir ortak kutuya işaret ediyor.

### `users.email` neden UNIQUE değil (2026-07-25 kullanıcı kararı)

Ortak/rol posta kutusunun birden çok hesapta kullanılabilmesi için UNIQUE index düşürüldü
(index arama için korundu). **Kaldırmak güvenli:**

| Bağımlılık | Durum |
|---|---|
| Giriş (login) | `username` ile — e-postayla kimlik doğrulama **yok** |
| E-posta teyidi | Token `user_id`'ye bağlı; `auth.verify_email` kullanıcıyı **id ile** bulur |
| Uygulama kontrolleri | `system_users.py`'deki iki "zaten kayıtlı" kontrolü kaldırıldı |
| **Kullanıcı adı** | Benzersizliği **AYNEN korunur** |

Testler yeni davranışı sabitliyor: `test_create_user_shared_email_allowed`,
`test_update_user_shared_email_allowed`, `test_create_user_duplicate_username_still_409`.
Geri alma (`downgrade`) mükerrer e-posta varsa **bilerek başarısız olur** — sessizce veri
silmektense migration'ın patlaması doğrudur.

## Off-site (S3) — 2026-07-25 (denetim DR-002)

> **DURUM: kurulum bekliyor.** Kod yolu tamamen hazır, otomatik ve **testlidir**; eksik olan
> tek şey AWS'de bir kerelik provizyon — bunun için AWS hesabı kimliği gerekir ve sunucuda
> yoktur (`aws sts get-caller-identity` → *Unable to locate credentials*, IAM role yok).
> Aşağıdaki **iki komut** çalıştırıldığı an bulgu kapanır.

### Neden bu bulgu iki denetim boyunca (v3 → v4) açık kaldı

Teknik bir engel yoktu: `SPRENSES_BACKUP_S3` kancası v3'ten beri duruyordu. Kapanmamasının
sebepleri yapısaldı ve **hepsi bu turda giderildi**:

| Kök neden | Giderme |
|---|---|
| Kapanış "12 komutluk runbook'u elle uygula"ya bağlıydı | `scripts/provision-offsite-backup.sh` — tek komut, idempotent |
| Off-site hatası yalnız `UYARI` basıp `exit 0` dönüyordu (sessiz) | Off-site hatası artık **işi başarısız yapar** → systemd `OnFailure` alarmı |
| Eksiklik hiçbir ekranda görünmüyordu | Sistem ▸ Yedekleme'de **"Veri Yedeği"** paneli + kırmızı uyarı kartı |
| Kimse hatırlatmıyordu | `health-thresholds.py` **off-site eşiği** — günde 2 kez ihlal bildirir, kurulunca kendiliğinden susar |
| "Farklı bölge" hiçbir yerde zorlanmıyordu | `_offsite-lib.sh` → `offsite_assert_cross_region` (aynı bölge **reddedilir**) |
| Yükleme yeşilken **geri yükleme** hiç denenmemişti | `enable` betiği yazıp **geri okur**; `db-restore.sh --offsite` tam tatbikat koşar |
| Kod yolu hiç test edilmemişti | `backend/tests/test_backup_offsite.py` (17 test, sahte `aws` CLI ile) |

### Kurulum — iki komut

```bash
# 1) AWS'de provizyon (BİR kez, admin kimliğiyle). Bucket adı KÜRESEL benzersiz olmalı.
aws configure                                             # geçici admin access key
scripts/provision-offsite-backup.sh sprenses-dr-2026 eu-west-1
rm -rf ~/.aws                                             # admin anahtarını sunucuda BIRAKMAYIN

# 2) Etkinleştir + tatbikat
scripts/enable-offsite-backup.sh s3://sprenses-dr-2026/sprenses
scripts/db-restore.sh --offsite                           # DR-002 kapanış kanıtı
```

`provision-offsite-backup.sh` ne kurar (hepsi idempotent, yeniden çalıştırılabilir):

1. **S3 bucket — EC2'den FARKLI bölgede** (sunucu `eu-north-1` → varsayılan hedef `eu-west-1`).
   Aynı bölge seçilirse script **reddeder**: bölgesel arıza iki kopyayı birden götürür.
2. **Versioning** — üzerine yazma/silme geri alınabilir (ransomware ikinci katmanı).
3. **SSE-AES256** + BucketKey — durağan şifreleme (finans + KVKK verisi).
4. **Public access block** — dört bayrak da `true`.
5. **Bucket policy** — `aws:SecureTransport=false` → `Deny` (TLS zorunlu).
6. **Lifecycle** — eski sürümler 90 gün sonra silinir, yarım multipart 7 gün.
7. **IAM policy + role + instance profile** → EC2'ye eklenir. Yetki **minimal**: yalnız bu
   bucket'ın bu prefix'i, `PutObject` + `GetObject` + prefix'e kısıtlı `ListBucket`.

> **Bilerek yapılmadı — Object Lock:** bucket oluşturulurken açılmalı ve **geri alınamaz**;
> yanlış kurulmuş bir compliance-mode kilidi faturayı yıllarca kilitler → kullanıcı kararı.

### S3 düzeni ve neden böyle

```
s3://<bucket>/sprenses/
    db/sprenses-<ts>.dump      ← her gün bir dump (aws s3 cp)
    uploads/<özgün dizin yapısı> ← TAM AYNA (aws s3 sync)
```

- **uploads neden `sync`, günlük `.tgz` DEĞİL:** tar yolu her gün 285 MB'ın **tamamını**
  yüklerdi (ayda ~8,5 GB depo + transfer). `sync` yalnız **değişeni** gönderir → ilk
  koşumdan sonra günlük birkaç MB. Ayrıca restore için açma adımı gerekmez.
- **`--delete` BİLEREK YOK:** kaynakta yanlışlıkla ya da kötü niyetle silinen dosya off-site
  kopyadan da silinmemeli. Versioning üzerine-yazmaya karşı ikinci katman.
- **Nesne adları zaman sıralı** (`YYYYMMDD-HHMMSS`) → en son yedek **ada** göre bulunur.
  `LastModified`'a güvenilmez: kopyalama/replikasyon onu değiştirir.

### Geri yükleme (S3'ten)

```bash
scripts/db-restore.sh --offsite          # en son off-site dump: indir → geçici DB → satır say
scripts/db-restore.sh s3://kova/sprenses/db/sprenses-20260725-000004.dump   # belirli bir dump
```

`--offsite` modu şunları sırayla yapar: farklı-bölge kontrolü → en son nesneyi bulma →
indirme → **bütünlük** (`pg_restore --list`) → geçici DB'ye geri yükleme + kritik tablo satır
sayıları → geçici DB'yi silme → **S3'ten 5 rastgele belgeyi indirip kaynakla checksum
karşılaştırma**.

> **`--offsite` neden AYRI bir mod:** "yedek S3'e gidiyor" ile "S3'teki yedekten geri
> dönülebiliyor" aynı şey değildir. Yalnız `PutObject` veren bir IAM policy'de yükleme her gün
> yeşil görünür ama felaket anında `GetObject` reddedilir — yedek **fiilen yoktur**.
> `enable-offsite-backup.sh` de bu yüzden yazdığını **geri okur**.

### Görünürlük — sessiz kalmaz

| Katman | Nerede | Ne der |
|---|---|---|
| Durum dosyası | `/var/backups/sprenses-db/backup-state.json` | Her koşumun DB/uploads/off-site sonucu + **son başarılı** off-site zamanı |
| API | `GET /api/system/backup/data-status` (izin `system.backup` view) | `offsite.level` = `ok` / `warning` / `critical` + Türkçe açıklama |
| UI | Sistem ▸ Yedekleme → **"Veri Yedeği"** paneli | Üç StatCard (DB · Belge · Off-site) + kurulmamışsa kırmızı uyarı kartı ve kurulum komutu |
| Alarm | `health-thresholds.py` → `off-site yedek` eşiği | Günde 2 kez; **yok / başarısız / bayat** durumlarını `error_logs` CRITICAL + e-posta ile bildirir |
| İş hatası | `sprenses-db-backup.service` çıkış kodu | Off-site başarısızsa iş **failed** → `OnFailure` alarmı |

**Son başarılı off-site zamanı koşumlar arası taşınır**: üst üste başarısız koşumlarda bile
"en son ne zaman gerçekten off-site'a çıktık" bilgisi kaybolmaz — DR'da sorulacak ilk soru odur.

### Testler

`backend/tests/test_backup_offsite.py` — 17 test. Gerçek AWS gerektirmez:
`backend/tests/fixtures/fake_aws.py` sahte bir `aws` CLI olarak PATH'e girer ve `s3://`
URI'lerini yerel dizine eşler; böylece **yükleme → listeleme → indirme → içerik eşitliği**
zinciri gerçek dosya trafiğiyle koşar (`pg_restore --list` ile S3'e giden dump'ın geçerliliği
dahil). Kapsam: off-site yükleme, hata durumunda **işin başarısız olması**, yerel yedeğin
korunması, durum dosyası doğruluğu, `last_ok`'in kaybolmaması, en-son-nesne seçimi,
farklı-bölge kuralı (kabul/ret/bilinçli override) ve API'nin kritik seviyesi.


## Genel Bilgi
- **Modül kodu:** `system.backup` (üst modül: `system`)
- **Frontend rota:** `/dashboard/sistem/yedekleme`
- **Backend prefix:** `/api/system/backup`
- **İzin:** `system.backup` — view (durum izleme), use (yedek + geri yükleme). Admin-only (Sunucu modülüyle aynı rollere verilir).
- **DB tablosu yok** — veri kaynağı **git'in kendisidir** (Sunucu modülü gibi salt-operasyon).

## Amaç
Kodun GitHub'daki (`finfdg/sprenses-otel`, private) yedek durumunu uygulama içinden
izlemek, **manuel yedek** almak (commit + push) ve gerektiğinde **geri yüklemek**.
Otomatik yedek `.claude/settings.json` Stop hook'u ile zaten alınır; bu modül
**görünürlük + manuel kontrol** ekler.

## Dosya Haritası
- Backend: `backend/app/routers/system_backup.py` (main.py'de `/api/system` altına mount)
- Frontend: `frontend/src/routes/dashboard/sistem/yedekleme/+page.svelte`
- Navigasyon: `frontend/src/lib/config/navigation.ts` → system grubu → `system.backup`

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/backup/status` | view | **KOD** yedeği: son commit, bekleyen değişiklik, ahead/behind, senkron, uzak URL, son 30 commit |
| GET | `/api/system/backup/data-status` | view | **VERİ** yedeği: DB dump tazeliği/sayısı, uploads snapshot'ları, off-site durumu (`level`: ok/warning/critical + Türkçe mesaj). Kaynak: `backup-state.json` + dosya sistemi |
| POST | `/api/system/backup/run` | use | Değişiklik varsa commit (`Manuel yedek: …`) + GitHub'a push |
| POST | `/api/system/backup/restore` | use | Seçilen commit'e güvenli geri yükleme (aşağıda) |

## Geri Yükleme — Güvenli "İleri-Commit" Semantiği
**Geçmiş asla yeniden yazılmaz, force-push yapılmaz, hiçbir şey kaybolmaz:**
1. Mevcut commit'lenmemiş değişiklik varsa → önce otomatik yedeklenir.
2. Hedef commit'in dosyaları çalışma ağacına + index'e getirilir (`git checkout <commit> -- .`).
3. Fark varsa **yeni bir commit** olarak kaydedilir (`Geri yükleme: <hash> durumuna dönüldü`).
4. Push edilir.
5. **Kod değiştiği için yeniden deploy gerekir** (backend restart + frontend build) — yanıtta `redeploy_needed` ile bildirilir.

> Not: Bu yöntem hedef commit'teki dosya **içeriklerini** geri getirir; hedeften sonra
> eklenmiş yepyeni dosyalar silinmez (güvenlik için bilinçli). Tam eşitlik gerekirse
> manuel müdahale gerekir.

## Güvenlik
- **subprocess list-arg** ile (shell yok) → komut enjeksiyonu imkânsız.
- `restore` commit hash'i **yalnızca hex** kabul eder (`; rm -rf /` gibi girdiler 400 ile reddedilir).
- `git push` backend'den (`ec2-user`, gh credential-helper) çalışır; **`.env`/sırlar gitignore ile dışlanır**, yedeğe gitmez.
- Tüm yazma işlemleri **audit log**'a yazılır (`backup`, `restore` eylemleri, entity_type=`system_backup`).
- Admin-only izin (Sunucu modülüyle aynı güven sınırı).

## Frontend UI
- `ListPage` iskeleti: PageHeader + StatCard'lar (Son Yedek / Senkron Durumu / Yedek Deposu) + "Şimdi Yedekle" butonu + commit geçmişi tablosu.
- Geri yükleme: tabloda satır başına "Geri Yükle" → **danger `ConfirmDialog`** (güçlü uyarı: yeniden deploy gerekir, geri alınabilir).
- Polling yok; durum mount'ta ve her işlemden sonra tazelenir.

## Audit Log
- entity_type: `system_backup`
- Eylemler: `backup` (manuel yedek), `restore` (geri yükleme).

## Geliştirme Kuralları
- Bu modül **onay akışından muaftır** (Sunucu restart gibi salt-operasyon endpoint'i).
- Geri yükleme sonrası deploy **otomatik yapılmaz** (çalışan backend'in kendini mid-request restart etmesi riskli) — kullanıcı/operatör elle deploy eder.
