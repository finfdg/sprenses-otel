# Off-site Yedek Tatbikatı — 2026-07-25 (denetim DR-002)

Bu belge DR-002'nin (ve ona bağlı DR-001'in) kapanış kriterinin ölçüm çıktılarını kayda
geçirir. **Durum: KAPANDI — off-site canlı** (`s3://sprenses-dr-2026/sprenses`, eu-west-1).
Önce AWS'siz (sahte S3) tatbikat, sonra gerçek S3 kurulumu koşulmuştur; ikisi de aşağıda.

## Kapanış kriteri

> Günlük DB+uploads farklı bölgedeki S3'e otomatik yükleniyor ve S3'ten restore
> en az bir kez uçtan uca doğrulandı.

| Bileşen | Durum | Kanıt |
|---|:--:|---|
| Günlük DB → off-site | ✔ kod | aşağıdaki koşum + `test_backup_offsite.py` |
| Günlük uploads → off-site | ✔ kod | aynı koşum (2060 dosya aynalandı) |
| **Farklı bölge** zorlaması | ✔ | `offsite_assert_cross_region` + 3 test |
| Off-site'tan restore (uçtan uca) | ✔ kod | aşağıdaki tatbikat (gerçek üretim verisi) |
| **Gerçek AWS S3'e** yükleme | ✔ | 2026-07-25 12:24 canlı koşum (aşağıya bkz) |

## Ön tatbikat (AWS'siz) — 2026-07-25 11:39–11:41 UTC

Gerçek AWS kimliği gelmeden önce kod yolu doğrulandı: S3 katmanı
`backend/tests/fixtures/fake_aws.py` ile birebir taklit edildi
(`aws` CLI PATH'te değiştirildi, `s3://` → yerel dizin). **Veri gerçek üretim
verisidir**; script'ler değiştirilmeden, üretim yolları ile koşmuştur.

### 1) Yedek + off-site yükleme

```
$ SPRENSES_BACKUP_S3=s3://sprenses-dr-test/sprenses bash scripts/db-backup.sh
DB yedeği OK: /var/backups/sprenses-db/sprenses-20260725-113956.dump (4.4M) — toplam 30 yedek
uploads snapshot OK: /var/backups/sprenses-uploads/20260725-113956 (2060 dosya) — toplam 4 snapshot, dizin 286M
off-site DB OK: s3://sprenses-dr-test/sprenses/db/sprenses-20260725-113956.dump
off-site uploads OK: s3://sprenses-dr-test/sprenses/uploads/ (2060 dosya aynalandı)
EXIT=0

$ du -sh <s3-kök> ; find <s3-kök> -type f | wc -l
290M     2061        # 1 dump + 2060 belge
```

### 2) Off-site'tan geri yükleme (uçtan uca)

```
$ scripts/db-restore.sh --offsite
=== OFF-SITE TATBİKATI: s3://sprenses-dr-test/sprenses ===
farklı-bölge OK: sunucu=eu-north-1 bucket=eu-west-1
indiriliyor: s3://sprenses-dr-test/sprenses/db/sprenses-20260725-113956.dump
Geri yükleniyor: /tmp/sprenses-offsite-hanSLe.dump → sprenses_restore_test
=== 'sprenses_restore_test' satır sayıları (yedeğin geri yüklenebilirliği) ===
  users                  10
  roles                  12
  modules                51
  finance_events         4737
  vendor_transactions    3306
  checks                 205
  credit_products        35
  reservations           18411
  audit_logs             25056
=== uploads snapshot tatbikatı ===
  snapshot : 20260725-113956 (2060 dosya)
  örneklem : 5 eşleşti / 0 uyuşmadı
=== off-site uploads tatbikatı ===
  örneklem : 5 indirildi+eşleşti / 0 sorunlu
TATBİKAT OK — geçici DB temizlendi.
OFF-SITE TATBİKATI GEÇTİ — S3'teki kopyadan uçtan uca geri dönülebilir.
EXIT=0
```

Tatbikatta bulunan ve düzeltilen bir hata: off-site belge örneklemi ilk koşumda
`0 indirildi` verdi (özyinelemeli listeleme çalışmıyordu). Kaynak sahte CLI'daydı ama
sınıf gerçekti — bu yüzden regresyon testi eklendi
(`test_offsite_uploads_are_listable_recursively`).

### 3) Eşik kontrolü — eksiklik alarm üretiyor (kurulumdan ÖNCE ölçüldü)

Ön tatbikat sonrası durum dosyası o günkü gerçeği yansıtacak şekilde yeniden üretildi
(off-site henüz kurulu DEĞİLDİ) ve eşik kontrolü ihlali gördü:

```
$ scripts/health-thresholds.py --dry-run
  ok    disk
  ok    döviz kuru
  ok    TLS sertifikası
  ok    yedek tazeliği
  İHLAL off-site yedek — Off-site yedek YOK — DB, uploads ve yedeklerin kendisi aynı
        diskte. Sunucu/disk kaybında veri geri getirilemez (denetim DR-002).
        Kurulum: scripts/provision-offsite-backup.sh
eşik kontrolü: 1 eşik ihlali
```

Bu ihlal günde 2 kez (08:00 / 20:00) `error_logs` CRITICAL + e-posta üretir ve
off-site kurulduğu an **kendiliğinden susar**. Bulgunun iki denetim boyunca sessizce
açık kalmasını sağlayan boşluk budur.

### 4) Testler

```
$ python -m pytest tests/test_backup_offsite.py tests/test_system_backup.py -q
27 passed

$ python -m pytest tests/ -q          # tam takım
2002 passed, 5 skipped in 1025.90s
```

**Sahte-yeşil değil:** düzeltmeler tek tek geri alınıp testlerin kırmızıya döndüğü
fiilen doğrulandı —
`exit 1` → `:` (sessiz off-site) ⇒ `test_offsite_failure_fails_the_job` KIRMIZI;
`offsite_assert_cross_region` → `return 0` ⇒ 3 bölge testi KIRMIZI;
`--recursive` elenmesi ⇒ `test_offsite_uploads_are_listable_recursively` KIRMIZI.

## Kurulum adımları (yapıldı — 2026-07-25)

```bash
aws configure                                              # geçici admin access key (IAM kullanıcısı)
scripts/provision-offsite-backup.sh sprenses-dr-2026 eu-west-1
rm -rf ~/.aws                                              # anahtar sunucuda bırakılmadı
scripts/enable-offsite-backup.sh s3://sprenses-dr-2026/sprenses
scripts/db-restore.sh --offsite                            # gerçek S3'ten kapanış kanıtı
```

Provizyon için açılan geçici IAM kullanıcısı (`sprenses-provision`) işlem sonrası
**silinmelidir** — sunucu artık `SprensesBackupRole` ile çalışır, anahtara ihtiyaç yoktur.


---

## CANLI KURULUM — 2026-07-25 12:14 / 12:24 (kapanış)

Bucket `sprenses-dr-2026` **eu-west-1**'de açıldı (sunucu eu-north-1), IAM rolü
`SprensesBackupRole` EC2'ye bağlandı, admin anahtarı silindi (`~/.aws` yok).

```
$ sudo systemctl start sprenses-db-backup.service ; systemctl show -p Result -p ExecMainStatus
Result=success   ExecMainStatus=0
  off-site DB OK: s3://sprenses-dr-2026/sprenses/db/sprenses-20260725-122428.dump
  off-site uploads OK: s3://sprenses-dr-2026/sprenses/uploads/ (2060 dosya aynalandı)

$ aws s3api get-bucket-location --bucket sprenses-dr-2026 --output text
eu-west-1
$ . scripts/_offsite-lib.sh; offsite_assert_cross_region s3://sprenses-dr-2026/sprenses
farklı-bölge OK: sunucu=eu-north-1 bucket=eu-west-1          (çıkış 0)

$ aws sts get-caller-identity --query Arn --output text
arn:aws:sts::636665306455:assumed-role/SprensesBackupRole/i-0cf25a70e992feaa5
$ ls -d ~/.aws  →  No such file or directory     # uzun ömürlü anahtar YOK

$ scripts/db-restore.sh --offsite
farklı-bölge OK: sunucu=eu-north-1 bucket=eu-west-1
indiriliyor: s3://sprenses-dr-2026/sprenses/db/sprenses-20260725-121409.dump
  reservations 18411 · finance_events 4737 · audit_logs 25057 · vendor_transactions 3306
=== off-site uploads tatbikatı ===  örneklem : 5 indirildi+eşleşti / 0 sorunlu
OFF-SITE TATBİKATI GEÇTİ — S3'teki kopyadan uçtan uca geri dönülebilir.

$ scripts/health-thresholds.py --dry-run
  ok    off-site yedek                     # ihlal kendiliğinden düştü
```

### İlk provizyonda yakalanan hata (düzeltildi)

İlk koşumda bekçi `bucket=us-east-1` dedi — oysa bucket eu-west-1'deydi:

1. **IAM policy:** `s3:GetBucketLocation`, `s3:ListBucket` ile aynı **`s3:prefix` koşullu**
   ifadedeydi. Bu eylem `s3:prefix` bağlam anahtarını desteklemez → koşul sağlanmaz →
   `AccessDenied`. → Ayrı, koşulsuz ifadeye taşındı.
2. **Sessiz geri düşüş:** `offsite_bucket_region` hatayı yutup "us-east-1" varsayıyordu →
   bucket eu-north-1'de **olsaydı bile** "farklı bölge ✔" derdi. Bekçi fiilen ölüydü ve
   kapanış kriteri yanlış yere sağlanmış görünüyordu. → Okuma başarısızsa **reddediyor**
   ve eksik izni adıyla söylüyor.

Regresyon: `test_unreadable_bucket_region_is_rejected_not_assumed` — düzeltme geri alınınca
kırmızıya döndüğü doğrulandı.

**Ders:** bir bekçinin "geçti" demesi çalıştığı anlamına gelmez. Doğrulayamadığı durumu
geçiren bekçi, hiç yazılmamış bekçiyle aynıdır.
