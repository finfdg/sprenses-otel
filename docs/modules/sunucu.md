# Sistem — Sunucu İzleme

## Genel Bilgi
- **Modül kodu:** `system.server`
- **Üst modül:** `system`
- **Frontend rota:** `/dashboard/sistem/sunucu`
- **Backend prefix:** `/api/system/server`
- **İzin kodu:** `system.server` — `view` (izleme), `use` (servis yeniden başlatma)

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/system_server.py` |
| Servis | `backend/app/services/disk_cleanup_service.py` (disk dökümü + temizlik) |
| Şema | `backend/app/schemas/server.py` |
| Cron | `backend/cron_disk_cleanup.py` (`sprenses-disk-cleanup.timer`) |
| Frontend | `frontend/src/routes/dashboard/sistem/sunucu/+page.svelte` |
| Test | `backend/tests/test_system_server.py` |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/server/info` | view | CPU/RAM/disk metrikleri + servis durumları |
| POST | `/api/system/server/services/{service_name}/restart` | use | Whitelist'li servisi yeniden başlat |
| GET | `/api/system/server/services/{service_name}/logs` | view | Servis journald logları (son N satır) |
| GET | `/api/system/server/disk` | view | Disk kullanımının kategori bazlı dökümü + temizlenebilir alan |
| POST | `/api/system/server/disk/cleanup` | use | Önbellek/eski log temizliği (`{keys?: [...]}`, boş → tümü) |

## Frontend UI Yapısı
- Tasarım sistemi: `PageHeader` + `StatCard` (CPU/RAM/disk) + servis durum listesi.
- **Disk kartı tıklanabilir** → disk döküm modalı (doluluk çubuğu + temizlenebilir/korunan kategori
  tabloları + "Şimdi Temizle"). Kart, `StatCard`'ın `onclick` prop'uyla `<button>` olarak render edilir
  (`href` prop'unun `<a>` karşılığı — tek kaynak korunur, sayfaya elle kart yazılmaz).
- **Polling istisnası:** Sistem metrikleri WS ile taşınmaz → 30 sn'lik `setInterval` ile `GET /server/info`
  fetch edilir. Sayfa kapanınca timer durur (`onDestroy`). Bu, CLAUDE.md "Polling yasak" kuralının
  **bilinçli sınırlı istisnasıdır** (başka sayfalarda polling yapılamaz).
- **Disk dökümü otomatik yenilemeye DAHİL DEĞİL:** `du` ile ölçüldüğünden `/server/info`'ya göre
  pahalıdır → yalnız modal açılınca ve temizlik sonrasında çağrılır.

## Audit Log Entegrasyonu
- `entity_type`: `server_service` — `action`: restart (servis yeniden başlatma kaydedilir)
- `entity_type`: `server_disk` — `action`: cleanup (elle temizlikte kullanıcı, otomatik temizlikte
  `admin` adına, `ip_address="cron"` ile yazılır → Audit Loglar sayfasında ikisi de görünür)

## Geliştirme Kuralları
- **Servis whitelist:** Yalnız izin verilen servis adları (`sprenses-api`, `sprenses-frontend`, `nginx`,
  `postgresql` vb.) restart/log alabilir — keyfi servis adı reddedilir (komut enjeksiyonu/kapsam koruması).
- **sudo NOPASSWD:** `systemctl restart/status/logs` için `ec2-user`'a dar kapsamlı NOPASSWD sudoers kuralı
  gerekir; aksi halde restart endpoint'i çalışmaz.
- **Onay akışı istisnası:** Servis restart ve disk temizliği operasyonel/anlık bakım eylemleridir;
  `check_approval`'dan geçmez (audit ile izlenir) — bilinçli muafiyet. İkisi de veri mutasyonu değil,
  sunucu bakımıdır; onay kuyruğunda beklemeleri disk dolarken zarar verir.

## Disk Dökümü ve Düzenli Temizlik (2026-07-25)

**Sorun:** Disk %45'e ulaşmıştı ve büyümenin nereden geldiği görünmüyordu; Disk kartı yalnız yüzde
gösteriyordu. Ölçümde şişkinliğin **tamamı yeniden üretilebilir veriden** geldiği çıktı: journald
1,2 GB (tavansız), npm/pip/dnf önbellekleri ~600 MB, 14 günden eski döndürülmüş uygulama logları,
eski Claude CLI sürümleri.

### Mimari — tek servis, iki tetikleyici

`disk_cleanup_service.scan_disk()` / `run_cleanup()` **hem** UI'daki "Şimdi Temizle" butonu (`POST
/server/disk/cleanup`) **hem** günlük timer (`cron_disk_cleanup.py`) tarafından çağrılır. CLAUDE.md'nin
ortak-service deseni: elle ve otomatik temizlik arasında davranış sapması **yapısal olarak** imkânsız.

### Kategoriler

| Anahtar | Kapsam | Politika |
|---|---|---|
| `journal` | `/var/log/journal` | `journalctl --vacuum-size=200M` — son 200 MB tutulur |
| `npm_cache` | `~/.npm/_cacache` + `/root/.npm` | tamamı silinir (npm şeffafça yeniden doldurur) |
| `pip_cache` | `~/.cache/pip` | tamamı silinir |
| `dnf_cache` | `/var/cache/dnf` + `/var/tmp/dnf-*` | `dnf clean all` + artık geçici dizinler |
| `app_logs` | `backend/logs/*.log.N` | **14 günden eski** arşivler; güncel log dosyası korunur |
| `claude_cli` | `~/.claude/remote/ccd-cli` | en yeni **2** sürüm tutulur, eskileri silinir (~250 MB/sürüm) |
| **Korunan** | uploads · /var/backups · venv+node_modules · worktrees · playwright · claude projects | `cleanable=False` — **hiçbir koşulda silinmez**, yalnız boyutu raporlanır |

**`~/.npm/_npx` BİLEREK hariç:** MCP sunucuları (playwright, postgres) oradan çalışır → her gün
silmek her oturumda gereksiz yeniden indirme ve ağ arızasında kırılma demektir. `_cacache` yeterli.

### Güvenlik ve güvenceler

- **Yol enjeksiyonu yok:** tüm yollar modül sabiti; dışarıdan yol gelmez. Seçim yalnız whitelist'li
  `key` ile yapılır; korunan/tanımsız anahtar → **400**.
- **Test güvencesi** (`test_system_server.py`): `uploads`/`backups`/`deps`/`claude_sessions` temizliğe
  gönderilirse 400 döner; `run_cleanup()` whitelist dışı anahtar için `_clean` çağırmaz; `_clean()`
  korunan anahtarla çağrılsa bile hiçbir silme komutu üretmez. Müşteri dosyalarının bir API çağrısıyla
  silinememesi bu modülün en önemli güvencesi — regresyonu bu testlerde yakalanır.
- **Ölçüm `du -s -x --block-size=1`** (apparent size değil gerçek blok kullanımı) → raporlanan
  "temizlenebilir" değeri gerçekten kazanılacak boş alandır. `use_sudo` yolunda `os.path.exists()`
  ön kontrolü **yapılmaz**: `/root` ec2-user'a kapalıdır, `exists()` False döner ve boyut sessizce
  0 görünürdü (ilk yazımda bu hataya düşüldü — `/root/.npm`'in 155 MB'ı görünmüyordu).

### Zamanlama — `sprenses-disk-cleanup.timer`

| Alan | Değer |
|---|---|
| Unit | `scripts/systemd/sprenses-disk-cleanup.{service,timer}` → `/etc/systemd/system/` |
| Zamanlama | `OnCalendar=*-*-* 04:30:00 Europe/Istanbul` + `Persistent=true` |
| Neden 04:30 | DB yedeği 03:00'te alınır → temizlik ondan sonra, mesai başlamadan önce |

Unit dosyaları repoda **var** (sedna-sync'in aksine) → sunucu yeniden kurulumunda:
```bash
sudo cp /home/ec2-user/otel/scripts/systemd/sprenses-disk-cleanup.* /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now sprenses-disk-cleanup.timer
```

### journald tavanı — yeniden büyümeyi engeller (git'te DEĞİL)

Temizlik journald'i **kırpar** ama tekrar 1,2 GB'a büyümesini engellemez. Kalıcı tavan:
```bash
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' | sudo tee /etc/systemd/journald.conf.d/99-sprenses-size.conf
sudo systemctl restart systemd-journald
```
**DİKKAT — `/etc/` altında, repoda yedeklenmez** (TZ drop-in'leri gibi): sunucu yeniden kurulursa
tekrar oluşturulmalı, yoksa journal sınırsız büyür. Doğrulama: `journalctl --disk-usage` ≤ 200 MB.

### İlk uygulama sonucu (2026-07-25)

journald tavanı 980 MB + temizlik 1.165 MB = **~2,1 GB** serbest; disk **%45 → %37,6**
(16,6 GB → 18,7 GB boş). En büyük kalemler: npm önbelleği 482 MB, dnf 288 MB, Claude CLI eski
sürümü 253 MB, pip 121 MB, eski uygulama logları 20 MB.

**Kalıcı temizlenmeyen büyük kalemler** (bilinçli, modalda "Korunan" olarak görünür): Playwright
tarayıcıları ~645 MB, bağımlılıklar (venv + node_modules) ~471 MB, yedekler ~407 MB, Claude oturum
geçmişi ~353 MB, worktree'ler ~147 MB. Worktree'ler biriktiğinde elle:
`git worktree remove <yol>` (bitmiş Claude oturumlarının çalışma kopyaları).

## Sunucu Seviyesi Bellek Koruması — Donma Önleme (2026-07-06)

**Olay:** 5 ve 6 Temmuz 2026'da makine iki kez tamamen kilitlendi (konsoldan zorla reboot gerekti).
Kök neden: t3.medium'da (2 vCPU / 4 GB) iki Claude oturumu aynı anda ağır iş (Vite build ×2, test)
çalıştırınca RAM tükendi; **swap olmadığı için** kernel OOM killer'ı tetikleyemeden sayfa-önbelleği
thrash'ine girdi → SSH dahil her şey dondu ve **dmesg/journal'a hiç OOM kaydı düşmedi**. Kanıt
`sar -r` geçmişinde: boş RAM 11:30'da 1,8 GB → 11:40'ta 100 MB → 11:50 örneği hiç alınamadı
(makine yanıtsız) → 11:54 reboot. Aynı desen 5 Temmuz 08:10–08:56 arasında da var.

**Alınan önlemler:**

| Önlem | Detay |
|---|---|
| 2 GB swap | `/swapfile` (root diskte, `chmod 600`); `/etc/fstab`'da `defaults,nofail` ile kalıcı |
| `vm.swappiness=10` | `/etc/sysctl.d/99-sprenses-swappiness.conf` — swap yalnız gerçek bellek baskısında devreye girer |
| `earlyoom` v1.8.2 | AL2023 deposunda paket yok → kaynaktan derlendi → `/usr/local/bin/earlyoom`. Unit: `/etc/systemd/system/earlyoom.service` (upstream hardened unit), argümanlar: `/etc/default/earlyoom`. Kullanılabilir RAM **ve** boş swap %10'un altına inince en yüksek bellekli süreci SIGTERM'ler (%5'te SIGKILL) — makine ayakta kalır. `--avoid` ile `systemd/sshd/postgres/nginx` öldürülmez (hedef tipik olarak node build olur) |
| Build kilidi + heap sınırı | `scripts/deploy-frontend.sh`: `flock` ile aynı anda tek build (ikincisi 10 dk'ya kadar sırada bekler) + `NODE_OPTIONS=--max-old-space-size=1536` |

**Kontrol komutları:**
- `free -h` / `swapon --show` — toplam 4 GB swap görünmeli (`/swapfile` + `/swapfile2`, 2026-07-18'den beri)
- `systemctl status earlyoom` — `active` olmalı
- `sudo journalctl -u earlyoom | grep -i kill` — earlyoom bir süreç sonlandırdıysa burada görünür (build gizemli şekilde ölürse önce buraya bak)
- Donma şüphesinde geçmiş analizi: `sar -r -f /var/log/sa/saGG` (GG = ayın günü) — "boş RAM çöküşü + eksik örnek" deseni bellek kilitlenmesinin imzasıdır

**Kural:** İki oturumda aynı anda deploy/ağır test tetiklemekten kaçının. Frontend build'i kilit
sayesinde kendiliğinden sıraya girer; ancak `pytest`/`vitest` gibi diğer ağır işler kilitsizdir —
onların eşzamanlılığını earlyoom + swap tolere eder ama yavaşlatır.

### Swap Doygunluğu Olayı — Claude Oturumları (2026-07-18)

**Olay:** 18 Temmuz 12:22–12:23'te earlyoom iki Vite build'ini (1364 MB ve 1013 MB RSS) SIGTERM'ledi;
araya yan kurban olarak kullanıcı-scope `dbus-broker` da (VmRSS 1 MB — öldürülmesi hiç bellek
kazandırmadı) girdi. **Kök neden:** 08:30–12:20 arasında açılan ~10 eşzamanlı uzun ömürlü Claude
(ccd-cli) oturumu — her biri ana süreç + 2 MCP sunucusu (playwright + postgres, npm/node ağacı) —
boşta kaldıkça kernel tarafından swap'a itildi ve oturum aileleri **tek başına ~1,8 GB swap** tuttu
(2 GB'ın %90'ı). earlyoom'un öldürme koşulu "RAM %10 **VE** swap %10 altı" olduğundan, swap kronik
doluyken her build denemesi (tepe ~1,4–1,8 GB) RAM'i %10 altına indirip SIGTERM yedi. Boş swap dün
gece %97 idi; oturumlar açıldıkça 4 saatte %9'a düştü (earlyoom saatlik raporlarında izlenebilir).

**Alınan önlemler (2026-07-18):**

| Önlem | Detay |
|---|---|
| Swap 2 GB → 4 GB | İkinci kalıcı dosya `/swapfile2` (2 GB, `dd` ile — xfs'te swap için `fallocate` delik riski taşır; `chmod 600` + `mkswap` + `swapon` + fstab `defaults,nofail`). **Ekleme yönlü** büyütme: dolu `/swapfile`'a dokunulmadı, `swapoff` çalıştırılmadı |
| earlyoom `--avoid` + dbus | `/etc/default/earlyoom` regex'ine `dbus-.*` eklendi — 1 MB'lık dbus-broker'ın anlamsız öldürülmesi (kullanıcı systemd oturumunu bozabilir) engellendi |
| Build öncesi bellek bekçisi | `scripts/deploy-frontend.sh`: kilit alındıktan sonra `MemAvailable + SwapFree < 2500 MB` ise build hiç başlamaz; hata mesajı en büyük swap kullanıcılarını listeler |

**Swap'ı güvenli boşaltma (drain) — kurallar:**

- **`swapoff` YASAK koşulu:** boş RAM (`MemAvailable`) < swap kullanımı iken `swapoff` **asla çalıştırılmaz** —
  2 GB'lık sayfa geri-okuması RAM'i bitirir, earlyoom'u tetikler, en kötüsünde 2026-07-06 tarzı thrash'e girer.
- **Doğal drain tercih edilir:** swap'taki sayfaların sahibi süreçler (boştaki Claude oturumları) kapanınca
  swap girdileri anında serbest kalır — `swapoff` gerekmez. Biriken boş oturumları claude.ai/code
  arayüzünden kapatmak/arşivlemek en etkili boşaltmadır.
- **Konsolidasyon (opsiyonel, bakım penceresinde):** İki dosya yerine tek 4 GB dosya istenirse: önce yeni
  4 GB dosya `swapon`, sonra boş RAM + yeni swap toplamı eski dosyanın kullanımını rahatça karşılıyorken
  `swapoff /swapfile`, ardından eski dosya silinip fstab güncellenir. Acele gerektiren bir durum değil.

**Kural (oturum hijyeni):** t3.medium 4 GB'da her eşzamanlı Claude oturumu ~0,3–1 GB sanal ayak izi
bırakır ve süreçler oturum kapatılana dek yaşar. **Biriken bitmiş oturumları kapatın** — 7+ eşzamanlı
oturum swap'ı doldurur ve build'leri earlyoom'a kurban eder.

## Sedna Senkron Timer'ı — `sprenses-sedna-sync.timer` (2026-07-12, Faz 2 #18)

Cari/çek/mutabakat Sedna senkronu artık kullanıcı butonunu beklemez — **otomatik timer** ile koşar.

| Alan | Değer |
|---|---|
| Script | `backend/cron_sedna_sync.py` (`sprenses-sedna-sync.service`, oneshot, `User=ec2-user`, `TZ=Europe/Istanbul`) |
| Kapsam | Merkezi senkronun **çekirdek finans adımları**: `cariler`, `ibans`, `checks`, `recurring_sync`, `bank_recon` — `sedna_sync._STEPS` registry'sinden `_CRON_STEP_KEYS` süzgeciyle, **admin** kullanıcısıyla |
| Zamanlama | `OnCalendar=*-*-* 09,11,13,15,17,19,21:15:00 Europe/Istanbul` + `Persistent=true` (09–21 arası 2 saatte bir, tek saatler :15) |
| Kapsam DIŞI | Satış faturaları (kendi timer'ı: `sprenses-sales-sync`), stok ve rezervasyon (Topbar butonuyla) |

**Faz farkı gerekçesi (EC2 bellek koruması):** `sprenses-sales-sync.timer` **çift saatler** :15'te
(08,10,…,22:15 Istanbul) koşar; sedna-sync **tek saatler** :15'te → iki ağır Sedna işi asla aynı anda
tetiklenmez (t3.medium 4 GB; 2026-07-06 donma dersinin devamı — ağır işler eşzamanlı çalıştırılmaz).

**Dayanıklılık:** Tünel/Sedna kapalıysa script uyarı loglayıp **0 ile çıkar** (timer'ı düşürmez);
adım-bazlı izolasyon (bir adım patlarsa diğerleri sürer, `db.rollback()` + devam). Not: cron ayrı
process olduğundan içindeki WS yayını tarayıcılara ulaşmaz — tazelik Topbar'daki
`GET /finance/sedna/last-sync` rozeti ve sayfa yüklemeleriyle görünür.

**DİKKAT — unit dosyaları `/etc/systemd/system/`'de, git'te DEĞİL** (`sprenses-sedna-sync.service` +
`.timer`; sales-sync'in aksine `scripts/systemd/` kopyası yok). Sunucu yeniden kurulumunda TZ drop-in'leri
gibi **elle yeniden oluşturulmalı**. Kontrol: `systemctl list-timers | grep sedna`.

## Process Saat Dilimi — Europe/Istanbul (2026-07-07, KRİTİK)

**Sorun:** Sunucu sistemi **UTC** (`timedatectl` → `UTC, +0000`). Python `date.today()`/`datetime.now()`
(naive) process saat dilimini kullanır → TZ ayarlanmazsa **UTC tarihi** döner. İstanbul UTC+3 olduğundan,
İstanbul gece yarısı ile 03:00 arasında (= UTC 21:00–24:00, önceki gün) backend'in "bugün"ü **bir gün
geri** kalır. Canlı belirti (07 Tem 02:44 İstanbul): Panel Nakit Akım günlük görünümü **"6 Temmuz"**
gösterdi; runway/T-Hesap/eur_balances `date.today()`'i UTC'den `2026-07-06` alıyordu.

**Çözüm — systemd drop-in ile process TZ zorlama (git'te DEĞİL, `/etc/` altında):**
```bash
sudo mkdir -p /etc/systemd/system/sprenses-api.service.d
printf '[Service]\nEnvironment=TZ=Europe/Istanbul\n' | sudo tee /etc/systemd/system/sprenses-api.service.d/timezone.conf
sudo mkdir -p /etc/systemd/system/sprenses-frontend.service.d
printf '[Service]\nEnvironment=TZ=Europe/Istanbul\n' | sudo tee /etc/systemd/system/sprenses-frontend.service.d/timezone.conf
sudo systemctl daemon-reload
sudo systemctl restart sprenses-api.service sprenses-frontend.service
```
Doğrulama: `sudo cat /proc/$(systemctl show -p MainPID --value sprenses-api.service)/environ | tr '\0' '\n' | grep TZ`
→ `TZ=Europe/Istanbul`; endpoint `runway.today` artık İstanbul gününü döndürür.

**DİKKAT — sunucu yeniden kurulursa TEKRAR oluşturulmalı** (bu `.conf` dosyaları repoda yedeklenmez).
Alternatif kalıcı çözüm: sistem TZ'sini de İstanbul yapmak (`sudo timedatectl set-timezone Europe/Istanbul`)
— ama DB zaten bağlantı başına İstanbul kullandığından ve loglar UTC beklenebildiğinden, yalnız uygulama
process'lerine TZ vermek daha az yan etkili tercih edildi. Kök CLAUDE.md "Saat Dilimi" bölümüne de işlendi.

## TLS Sertifikası — Let's Encrypt Otomatik Yenileme (2026-07-18, KRİTİK OLAY)

**Olay:** 17 Temmuz 2026 22:23 (İstanbul) — Let's Encrypt sertifikasının süresi doldu.
`certbot-renew.timer` **disabled** durumdaydı (hiç etkinleştirilmemiş), sertifika hiç yenilenmedi.
Canlı belirti (18 Tem sabahı): Panel'de "Nakit akım projeksiyonu / T hesap verisi / projeksiyon
bakiyeleri yüklenemedi" toast'ları — tarayıcı süresi dolmuş sertifikayla TLS el sıkışmasını
reddettiğinden **hiçbir API isteği sunucuya ulaşamadı** (nginx access log'da isteklerin hiç
görünmemesi ayırt edici işaretti; backend/nginx tamamen sağlıklıydı). 2026-07-05 v3 kurumsal
denetimdeki "TLS yenilemeye 12 gün" Kritik bulgusu tam öngörüldüğü gibi gerçekleşti.

**Çözüm:**
```bash
sudo certbot renew                                # nginx plugin — yeniler + nginx'i reload eder
sudo systemctl enable --now certbot-renew.timer   # kalıcı otomatik yenileme (günde 2 kez dener)
```
Doğrulama: `sudo certbot certificates` (Expiry Date geleceğe bakmalı) +
`echo | openssl s_client -connect 127.0.0.1:443 -servername sprenses.com | openssl x509 -noout -dates`.

**DİKKAT — sunucu yeniden kurulursa** certbot kurulumundan sonra `certbot-renew.timer`'ın
**enabled** olduğu mutlaka kontrol edilmeli (`systemctl list-timers | grep certbot`) — Amazon Linux
2023'te certbot paketi timer'ı varsayılan **kapalı** kurar; elle açılmazsa 90 gün sonra site yine düşer.
