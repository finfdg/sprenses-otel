# Restore Tatbikatı — 2026-07-25

> Denetim kapanış kriteri: *"yedek var ≠ yedek çalışıyor"*. Bu belge tatbikatın **fiilen
> koşulduğunun** kaydıdır. Sonraki tatbikat bu dosyanın altına eklenir.

## Sonuç: ✔ BAŞARILI (ilk gerçek tatbikat)

| Alan | Değer |
|---|---|
| Tarih | 2026-07-25 10:2x (Europe/Istanbul) |
| Yedek | `sprenses-20260725-092356.dump` (4,4 MB, `pg_dump -Fc`) |
| Yöntem | `scripts/db-restore.sh` (argümansız = geçici DB'ye yükle → say → DROP) |
| Süre | **4,3 sn** (DB) + **2,4 sn** (285 MB uploads kopyası) |

### Satır sayıları — üretim ↔ geri yüklenen

| Tablo | Üretim | Geri yüklenen | |
|---|---:|---:|:--:|
| users | 10 | 10 | ✔ |
| roles | 12 | 12 | ✔ |
| modules | 50 | 50 | ✔ |
| finance_events | 4.737 | 4.737 | ✔ |
| vendor_transactions | 3.306 | 3.306 | ✔ |
| checks | 205 | 205 | ✔ |
| credit_products | 35 | 35 | ✔ |
| reservations | 18.411 | 18.411 | ✔ |
| audit_logs | 25.048 | 25.047 | ✔ *beklenen* — dump 09:23'te alındı, o andan beri +1 satır |

### uploads snapshot

| Alan | Değer |
|---|---|
| Snapshot | `20260725-092356` — **1.995 dosya** |
| Örneklem | rastgele 5 mali belge (pdf/xls) → **5 eşleşti / 0 uyuşmadı** (md5) |

---

## ⚠️ Tatbikatın yakaladığı gerçek kusur

**İlk koşu BAŞARISIZ oldu** — ve sebebi aynı gün yapılan güvenlik sertleştirmesiydi:

```
pg_restore: error: could not open input file
  "/var/backups/sprenses-db/sprenses-20260725-092356.dump": Permission denied
```

R3'te yedekler sertleştirilmişti (dosya `0600`, dizin `0700`, sahip `ec2-user` — denetim
DR-002: finans+KVKK verisi dünyaya açık olmamalı). Ama tatbikat `sudo -u postgres` ile
koşuyor ve **`postgres` kullanıcısı `ec2-user`'ın dosyasını okuyamıyor**. Yani sertleştirme
felaket kurtarmayı **sessizce kırmıştı**; gerçek bir felakette fark edilecekti.

**Düzeltme:** tatbikat dump'ı `postgres`'in okuyabileceği geçici bir kopyaya alır
(`mktemp -d` + `trap` ile temizlenir); **kaynak yedeğin izinleri değişmez**. Üretime geri
yükleme yolu zaten `ec2-user` olarak koştuğu için etkilenmiyordu.

> **Ders:** Sertleştirme ve kurtarılabilirlik birbirini sessizce bozabilir. Yedek izinlerine
> her dokunuşta tatbikat tekrar koşulmalı.

Ayrıca tatbikat çıktısındaki `could not change directory` gürültüsü giderildi (postgres
çalışma dizinini miras alıyordu) ve **uploads doğrulaması tatbikata eklendi** — önceden
yalnız DB test ediliyordu, oysa dosyalar olmadan DB tek başına işe yaramaz.

---

## RPO / RTO — ilk kez tanımlandı

Denetim bunları "TANIMSIZ" olarak işaretlemişti.

| Ölçüt | Değer | Gerekçe |
|---|---|---|
| **RPO** (kabul edilebilir veri kaybı) | **≤ 24 saat** | Yedek günde bir kez 03:00'te alınır; PITR/WAL arşivleme yok → son yedekten sonraki değişiklikler kayıptır. Gün içi yoğun mutasyon varsa (Sedna senkronu 2 saatte bir) gerçek kayıp 24 saate kadar çıkabilir. |
| **RTO** (kurtarma süresi) | **≤ 30 dakika** *(aynı makinede)* | Ölçülen: DB restore 4,3 sn + uploads kopyası 2,4 sn. Kalan süre insan müdahalesi: kararı verme, servisleri durdurma, doğrulama, servisleri açma. |
| **RTO** *(makine tamamen kaybedilirse)* | **BELİRSİZ — muhtemelen ≥ 1 gün** | Off-site yedek YOK (DR-002). Yeni EC2 kurulumu belgelenmemiş; `/etc`'deki 17 elle-yapılmış konfig git'te değil. **Bu senaryoda veri de kurtarılamaz.** |

### RPO'yu iyileştirmek isterseniz
- PITR/WAL arşivleme → RPO dakikalara iner (orta vade, `archive_mode=off` şu an)
- Yedek sıklığını artırmak (ör. 6 saatte bir) → RPO ≤ 6 saat, maliyeti düşük

### RTO'yu iyileştirmek için ÖNCE kapatılması gereken
- **DR-002 off-site** — bu kapanmadan "makine kaybı" senaryosunda RTO tanımlanamaz
- Sunucu yeniden kurulum runbook'u (DOCS-002 / SRV-003)

---

## Kurtarma prosedürü (ölçülmüş)

```bash
# 1) Tatbikat — üretime dokunmaz, güvenli, her çeyrekte koşulmalı
scripts/db-restore.sh

# 2) GERÇEK kurtarma — üretim verisi SİLİNİR, elle 'EVET' onayı ister
scripts/db-restore.sh /var/backups/sprenses-db/sprenses-<ts>.dump sprenses

# 3) uploads geri yükleme (DB tek başına yetmez!)
sudo systemctl stop sprenses-api
cp -a /var/backups/sprenses-uploads/<ts>/. /home/ec2-user/otel/backend/uploads/
sudo systemctl start sprenses-api
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/api/health   # 200 bekle
```

## Sonraki tatbikat

**Vade:** 2026-10-25 (çeyreklik). Yedek izinlerine/script'ine dokunulursa **hemen** tekrarla.
