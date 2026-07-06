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
| Frontend | `frontend/src/routes/dashboard/sistem/sunucu/+page.svelte` |
| Test | `backend/tests/test_system_server.py` |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/server/info` | view | CPU/RAM/disk metrikleri + servis durumları |
| POST | `/api/system/server/services/{service_name}/restart` | use | Whitelist'li servisi yeniden başlat |
| GET | `/api/system/server/services/{service_name}/logs` | view | Servis journald logları (son N satır) |

## Frontend UI Yapısı
- Tasarım sistemi: `PageHeader` + `StatCard` (CPU/RAM/disk) + servis durum listesi.
- **Polling istisnası:** Sistem metrikleri WS ile taşınmaz → 30 sn'lik `setInterval` ile `GET /server/info`
  fetch edilir. Sayfa kapanınca timer durur (`onDestroy`). Bu, CLAUDE.md "Polling yasak" kuralının
  **bilinçli sınırlı istisnasıdır** (başka sayfalarda polling yapılamaz).

## Audit Log Entegrasyonu
- `entity_type`: `server_service` — `action`: restart (servis yeniden başlatma kaydedilir)

## Geliştirme Kuralları
- **Servis whitelist:** Yalnız izin verilen servis adları (`sprenses-api`, `sprenses-frontend`, `nginx`,
  `postgresql` vb.) restart/log alabilir — keyfi servis adı reddedilir (komut enjeksiyonu/kapsam koruması).
- **sudo NOPASSWD:** `systemctl restart/status/logs` için `ec2-user`'a dar kapsamlı NOPASSWD sudoers kuralı
  gerekir; aksi halde restart endpoint'i çalışmaz.
- **Onay akışı istisnası:** Servis restart operasyonel/anlık bir bakım eylemidir; `check_approval`'dan
  geçmez (audit ile izlenir) — bilinçli muafiyet.

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
- `free -h` / `swapon --show` — 2 GB swap görünmeli
- `systemctl status earlyoom` — `active` olmalı
- `sudo journalctl -u earlyoom | grep -i kill` — earlyoom bir süreç sonlandırdıysa burada görünür (build gizemli şekilde ölürse önce buraya bak)
- Donma şüphesinde geçmiş analizi: `sar -r -f /var/log/sa/saGG` (GG = ayın günü) — "boş RAM çöküşü + eksik örnek" deseni bellek kilitlenmesinin imzasıdır

**Kural:** İki oturumda aynı anda deploy/ağır test tetiklemekten kaçının. Frontend build'i kilit
sayesinde kendiliğinden sıraya girer; ancak `pytest`/`vitest` gibi diğer ağır işler kilitsizdir —
onların eşzamanlılığını earlyoom + swap tolere eder ama yavaşlatır.

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
