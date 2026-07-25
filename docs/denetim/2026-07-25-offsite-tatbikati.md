# Off-site Yedek Tatbikatı — 2026-07-25 (denetim DR-002)

Bu belge, DR-002 kapanış kriterinin **hangi kısmının kanıtlandığını** ve hangisinin
kullanıcı aksiyonu beklediğini ölçüm çıktılarıyla kayda geçirir.

## Kapanış kriteri

> Günlük DB+uploads farklı bölgedeki S3'e otomatik yükleniyor ve S3'ten restore
> en az bir kez uçtan uca doğrulandı.

| Bileşen | Durum | Kanıt |
|---|:--:|---|
| Günlük DB → off-site | ✔ kod | aşağıdaki koşum + `test_backup_offsite.py` |
| Günlük uploads → off-site | ✔ kod | aynı koşum (2060 dosya aynalandı) |
| **Farklı bölge** zorlaması | ✔ | `offsite_assert_cross_region` + 3 test |
| Off-site'tan restore (uçtan uca) | ✔ kod | aşağıdaki tatbikat (gerçek üretim verisi) |
| **Gerçek AWS S3'e** yükleme | ✗ | **AWS kimliği yok** — kullanıcı aksiyonu |

**Neden gerçek S3 değil:** sunucuda AWS kimliği bulunmuyor —
`aws sts get-caller-identity` → *Unable to locate credentials*; IMDS
`meta-data/iam/security-credentials/` → **404** (instance'a bağlı IAM role yok).
Kimlik olmadan bucket ve IAM rolü oluşturulamaz. Bu adım AWS hesabı sahibinin
bir kerelik işlemidir; komutlar aşağıda.

## Tatbikat — 2026-07-25 11:39–11:41 UTC

S3 katmanı, `backend/tests/fixtures/fake_aws.py` ile birebir taklit edildi
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

### 3) Eşik kontrolü — eksiklik artık alarm üretiyor

Tatbikat sonrası durum dosyası **gerçeği** yansıtacak şekilde yeniden üretildi
(off-site üretimde kurulu DEĞİL) ve eşik kontrolü ihlali gördü:

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

## Kalan adım (kullanıcı — AWS hesabında)

```bash
aws configure                                              # geçici admin access key
scripts/provision-offsite-backup.sh sprenses-dr-2026 eu-west-1
rm -rf ~/.aws                                              # anahtarı sunucuda BIRAKMAYIN
scripts/enable-offsite-backup.sh s3://sprenses-dr-2026/sprenses
scripts/db-restore.sh --offsite                            # gerçek S3'ten kapanış kanıtı
```

Bu dört komut geçtiğinde DR-002 **tam** kapanır; `health-thresholds.py` ihlali kendiliğinden
düşer ve Sistem ▸ Yedekleme'deki kırmızı kart yeşile döner.
