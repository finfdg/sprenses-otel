# systemd drop-in'leri — alarm bağlantıları

Bu dosyalar `/etc/systemd/system/<birim>.service.d/onfailure.conf` olarak kurulur ve
ana unit dosyalarına **dokunmadan** başarısızlık alarmını bağlar (denetim DR-003).

`/etc` git'te tutulmadığından (denetim DEBT-003/SRV-003) sunucu yeniden kurulursa
bunlar kaybolur — kaynak burasıdır.

## Toplu kurulum

```bash
sudo cp ../sprenses-alert@.service /etc/systemd/system/
for u in sprenses-db-backup sprenses-exchange-rates sprenses-sedna-sync \
         sprenses-sales-sync sprenses-ai-digest; do
  sudo mkdir -p /etc/systemd/system/$u.service.d
  sudo cp $u-onfailure.conf /etc/systemd/system/$u.service.d/onfailure.conf
done
sudo systemctl daemon-reload
```

## Doğrulama

```bash
for u in sprenses-db-backup sprenses-exchange-rates sprenses-sedna-sync \
         sprenses-sales-sync sprenses-ai-digest; do
  printf "%-26s %s\n" "$u" "$(systemctl show -p OnFailure --value $u.service)"
done
```

Her satırda `sprenses-alert@<birim>.service` görünmeli.

## Alarm testi

```bash
# Hiçbir şey yazmaz/göndermez — alıcı çözümlemesini gösterir
scripts/systemd-failure-alert.py sprenses-db-backup.service --dry-run
```

Gerçek uçtan uca test için bilerek başarısız olan geçici bir birim oluşturulur
(`ExecStart=/bin/false` + `OnFailure=sprenses-alert@%N.service`) — **izinli
kullanıcılara gerçek alarm e-postası gider**, önce haber ver.
