---
description: Sistem durumu — servisler, sağlık, Sedna tüneli, dinlenen portlar, git yedek
---
Bu sunucunun anlık durumunu topla ve kısa özetle:

```bash
echo "=== Servisler ==="
systemctl is-active sprenses-api sprenses-frontend nginx postgresql
echo "=== Sağlık ==="
curl -s -o /dev/null -w "api:%{http_code}  " http://127.0.0.1:8001/api/health
curl -s -o /dev/null -w "frontend:%{http_code}\n" http://127.0.0.1:3000/
echo "=== Dinlenen portlar (hepsi 127.0.0.1 olmalı — dışa açık OLMAMALI) ==="
ss -tln | grep -E ":8001|:3000|:5432|:11433" || echo "(beklenen port yok)"
echo "=== Sedna ters tüneli (127.0.0.1:11433) ==="
ss -tln | grep -q "127.0.0.1:11433" && echo "AÇIK" || echo "KAPALI → Sedna içe-aktarmaları 503 döner"
echo "=== Git yedek durumu ==="
cd /home/ec2-user/otel && git log -1 --format="son commit: %ci · %s"
git status --porcelain | head -5
git rev-parse origin/master >/dev/null 2>&1 && echo "GitHub farkı: $(git log origin/master..master --oneline 2>/dev/null | wc -l) commit ileride"
```

Çıktıyı tablo/madde halinde özetle. Bir servis `active` değilse, bir health 200 değilse, ya da **8001/3000/5432 portu `0.0.0.0`'da dinliyorsa** (güvenlik!) açıkça vurgula. Sedna tüneli kapalıysa kullanıcıya hatırlat (içe-aktarma butonları 503 döner).
