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
- **Off-site (OPSİYONEL, henüz pasif):** `SPRENSES_BACKUP_S3=s3://bucket/prefix` set edilirse `aws s3 cp --sse AES256` ile yüklenir. **Şu an kapalı** — EC2'de IAM role / aws credential YOK. Tam felaket-kurtarma (instance/disk kaybı) için S3 bucket + IAM role kurulup bu değişken servise (`/etc/systemd/system/sprenses-db-backup.service` `Environment=`) eklenmeli. Yerel yedek; yanlış DROP/DELETE, app bug ve veri bozulmasına karşı korur ama tek-disk kaybına karşı KORUMAZ → off-site tamamlanmalı.
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
- **Off-site:** `SPRENSES_BACKUP_S3` set ise snapshot `uploads-<ts>.tgz` olarak S3'e gider
  (dizin senkronu dosya başına istek = pahalı), yükleme sonrası yerel tar silinir.
- **İzin modeli:** koruma **dizin seviyesinde** — `/var/backups/sprenses-uploads` `0700`.
  Snapshot içindeki dosyalar kaynak izinlerini korur (`rsync -a`), bazıları dünya-okunur;
  **bilinçli tercih**: `--chmod` ile izin değiştirmek hardlink'i bozar (izni farklı dosya
  önceki snapshot'a link'lenemez → dedup çöker, 30 snapshot yeniden 7,5 GB olur). Ayrıcalıksız
  süreç `0700` dizinden içeri giremediği için koruma seviyesi dump'larla aynıdır.

> **DR-001 durumu:** yerel günlük yedek + restore tatbikatı ✔ · **off-site ✗** (DR-002'ye bağlı).
> Tek disk kaybında hâlâ her şey gider — off-site tamamlanmadan bu bulgu TAM kapanmaz.

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

### Off-site (S3) Etkinleştirme Runbook (eu-north-1)

EC2'de **IAM role/credential yok** → off-site pasif. Etkinleştirmek için (AWS hesabında, BİR kez):

```bash
# 1) S3 bucket (versioning + şifreleme + public-erişim kapalı + 90 gün lifecycle)
BUCKET=sprenses-db-backups-<benzersiz-ek>   # küresel benzersiz olmalı
aws s3api create-bucket --bucket "$BUCKET" --region eu-north-1 \
  --create-bucket-configuration LocationConstraint=eu-north-1
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# 2) IAM policy (MİNİMAL — yalnız bu bucket/prefix; put + restore için get/list)
#    Resource'taki BUCKET'i değiştir:
{
  "Version":"2012-10-17",
  "Statement":[
    {"Sid":"Put","Effect":"Allow","Action":["s3:PutObject"],
     "Resource":"arn:aws:s3:::BUCKET/sprenses-db/*"},
    {"Sid":"GetList","Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],
     "Resource":["arn:aws:s3:::BUCKET","arn:aws:s3:::BUCKET/sprenses-db/*"]}
  ]
}
# Bu policy ile bir IAM role oluştur → EC2 instance'ına ekle (Actions → Security → Modify IAM role).

# 3) Etkinleştir (instance'ta, role ekli olunca):
scripts/enable-offsite-backup.sh s3://$BUCKET/sprenses-db
```

`enable-offsite-backup.sh`: AWS erişimini + S3 yazmayı test eder, systemd **drop-in** ile
(`/etc/systemd/system/sprenses-db-backup.service.d/offsite.conf` → `Environment=SPRENSES_BACKUP_S3=...`)
günlük yedeğe S3 yüklemesi ekler, bir test koşumu yapar. Ana `.service` dosyası değişmez.
Geri yükleme S3'ten: `aws s3 cp s3://$BUCKET/sprenses-db/<dosya>.dump /tmp/ && scripts/db-restore.sh /tmp/<dosya>.dump`.

**Coğrafi DR notu:** Daha güçlü koruma için bucket'ı farklı bir bölgede aç veya S3 Cross-Region
Replication ekle (bölge-geneli arıza her iki kopyayı kaybetmesin). Tek-bölge bile mevcut "yerel-only"den
çok daha iyi (instance/disk kaybını kapatır).


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
| GET | `/api/system/backup/status` | view | Son commit, bekleyen değişiklik, ahead/behind, senkron, uzak URL, son 30 commit |
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
