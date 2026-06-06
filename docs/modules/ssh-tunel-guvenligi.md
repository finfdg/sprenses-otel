# SSH Ters Tünel Güvenliği + authorized_keys Sertleştirme Denetimi

**Tarih:** 2026-06-06 · **Kapsam:** EC2 `~ec2-user/.ssh/authorized_keys`, Sedna ters SSH tüneli

Sedna muhasebe DB'sine erişim, Ubuntu LAN makinesinden EC2'ye açılan **ters SSH tüneliyle**
sağlanır (`-R 127.0.0.1:11433:192.168.2.245:1433`). Tünelin EC2 tarafındaki anahtarı yanlış
sınırlandırılırsa, Ubuntu'da o özel anahtara erişen biri **EC2 sunucusundaki tüm dosyaları
okuyabilir**. Bu doküman açığı, düzeltmeyi ve kalıcı denetim/zorlama sistemini anlatır.

---

## 1. Açık — `restrict` tek başına YETMEZ

Tünel anahtarı başlangıçta şu seçeneklerdeydi:

```
restrict,port-forwarding,permitlisten="127.0.0.1:11433"  ssh-ed25519 …  sedna-reverse-tunnel
```

`restrict` yalnızca **PTY / etkileşimli kabuğu** kapatır (`no-pty`); **komut çalıştırmayı
engellemez**. Bu yüzden anahtara sahip biri tünel yerine şunu çalıştırabilir:

```bash
ssh -i tunnelkey ec2-user@EC2 'cat ~/otel/backend/.env'
```

→ sshd komutu çalıştırır (PTY gerekmez) → **`.env` (DB şifresi, SECRET_KEY) ve tüm ec2-user
dosyaları okunur.** Ayrıca `permitopen` tanımsız olduğundan `-L`/`-D` ile iç servislere
(PostgreSQL 5432, **IMDS 169.254.169.254 → AWS IAM kimlikleri**) pivot mümkündü.

Bu, atılabilir bir test anahtarıyla canlı kanıtlandı (komut çalıştı, `.env` okundu).

---

## 2. Düzeltme — yalnızca-tünel anahtarı

```
restrict,port-forwarding,permitlisten="127.0.0.1:11433",permitopen="127.0.0.1:1",command="echo tunnel-only-no-shell"  ssh-ed25519 …  sedna-reverse-tunnel
```

| Seçenek | Etki | Doğrulama |
|---|---|---|
| `command="..."` | Forced komut — keyfi komut/kabuk **çalışmaz** (dosya okuma kapanır) | `cat .env` → "tunnel-only-no-shell" |
| `permitopen="127.0.0.1:1"` | `-L`/`-D` yalnız **ölü porta** → DB/IMDS pivotu yok | `-L …:5432` reddedilir |
| `permitlisten="127.0.0.1:11433"` | `-R` yalnız bu bind'e | SQL tüneli çalışır |
| `restrict` | no-pty / no-agent / no-X11 | — |

**Kritik incelikler:**
- `command=` ters tüneli (`-N -R`) **bozmaz** — `-N` oturum kanalı açmadığından forced komut
  hiç tetiklenmez; tünel kurulur. (Matris testiyle doğrulandı.)
- **`permitopen="none"` KULLANMA** — OpenSSH 8.7 bunu geçersiz host sayıp anahtarı **tümden
  reddeder** (`Permission denied`). Onun yerine ölü port (`127.0.0.1:1`) ver.
- Yedek: `~/.ssh/authorized_keys.bak.pre-harden.*`.

---

## 3. Kalıcı denetim + zorlama sistemi

`scripts/ssh-key-audit.py` + systemd path/timer ile **yeni eklenen her tünel anahtarı
otomatik sertleşir**.

### Denetim scripti — `scripts/ssh-key-audit.py`

**Kural:** options içinde `permitlisten=` / `permitopen=` / `port-forwarding` geçen her
anahtar (= forward/tünel anahtarı) **hem `command=` hem `permitopen=`** taşımalıdır.

- **Sınıflandırma:**
  - *Forward anahtarı* eksik `command=`/`permitopen=` → **IHLAL** (otomatik düzeltilir)
  - *Opsiyon-suz anahtar* (admin, kabuk açık) → **UYARI** (otomatik düzeltilmez — kasıtlı olabilir)
  - *restrict var ama command= yok, forward değil* → **UYARI** (komut çalıştırılabilir)
- **Modlar:** `(varsayılan)` denetim+exit 1 · `--fix` eksikleri ekle · `--quiet` cron/systemd
- **Güvenli `--fix`:** anahtar **verisine asla dokunmaz** (yalnız options ön-ekini değiştirir),
  mevcut `permitlisten` değerini korur, **atomik** yazar (`os.replace`), önce **yedek** alır
  (`*.bak.audit.*`, son 10 tutulur), yeni satırı yeniden ayrıştırıp doğrular.

```bash
python3 scripts/ssh-key-audit.py            # denetim (salt-okunur)
python3 scripts/ssh-key-audit.py --fix      # eksik guvenlik opsiyonlarini ekle
```

### Otomatik zorlama — systemd

`scripts/systemd/` altında (kurulumu `/etc/systemd/system/`):

- **`ssh-key-audit.path`** — `authorized_keys` her değiştiğinde (`PathModified`) servisi tetikler
  → zayıf tünel anahtarı **~1 sn içinde** sertleşir. (Canlı test: ekle→1sn→`[DUZELTILDI]`.)
- **`ssh-key-audit.service`** — oneshot, `--fix --quiet` çalıştırır (User=ec2-user).
- **`ssh-key-audit.timer`** — günlük heartbeat denetim.

**İdempotent:** servis kendi yazdığı dosyayı tekrar tetikler ama ihlal kalmadığından ikinci
çalışma no-op olur (sonsuz döngü yok).

```bash
# Durum / log
systemctl status ssh-key-audit.path
journalctl -u ssh-key-audit.service --since today
# Devre dışı bırakma (gerekirse)
sudo systemctl disable --now ssh-key-audit.path ssh-key-audit.timer
```

---

## 4. Kalıntı risk — admin anahtarları

`authorized_keys`'te **opsiyon-suz, tam-erişimli** iki anahtar var: `otelyeni`,
`sprenses-migration@otel-eski`. Bunlar normal SSH yönetimi içindir (silinmedi). **Bu
anahtarların ÖZEL kısımları Ubuntu LAN makinesinde BULUNMAMALI** — bulunursa sedna
sertleştirmesinden bağımsız tam kabuk yolu açılır. Tünel için yalnız kısıtlı sedna anahtarı
yeterlidir. Denetim scripti bunları her çalışmada **UYARI** olarak hatırlatır.

**Önlem (opsiyonel):** anahtar zayıf seçeneklerle açık kaldığı süre boyunca Ubuntu makinesi
güvenilmezse `.env` içindeki `SECRET_KEY` ve DB şifresi okunmuş olabilir → ihtiyaten rotasyon.
