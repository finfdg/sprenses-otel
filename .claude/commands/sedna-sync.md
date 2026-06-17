---
description: Sedna ters tüneli + bağlantı teşhisi (içe-aktarma neden 503 / çalışmıyor?)
---
Sedna (muhasebe SQL Server) bağlantı ön-koşullarını teşhis et. **Not:** gerçek senkron UI'daki Topbar "Sedna" butonundan çalışır (kullanıcı oturumu + `use` izni gerekir); bu komut CLI'dan tetiklemez, bağlantının çalışıp çalışamayacağını kontrol eder.

```bash
echo "=== Ters tünel (127.0.0.1:11433) ==="
ss -tln | grep -q "127.0.0.1:11433" && echo "AÇIK ✓" || echo "KAPALI ✗ → tüm Sedna içe-aktarmaları 503 döner"
echo "=== SEDNA_PASSWORD ayarlı mı (.env — değer YAZDIRILMAZ) ==="
grep -qE "^SEDNA_PASSWORD=.+" /home/ec2-user/otel/backend/.env && echo "Ayarlı ✓" || echo "BOŞ ✗ → özellik kapalı, buton gizli"
echo "=== Son Sedna/tünel logları ==="
sudo journalctl -u sprenses-api.service -n 300 --no-pager 2>/dev/null | grep -iE "sedna|tünel|tunnel|11433|SednaUnavailable|pymssql" | tail -15 || echo "(ilgili log yok)"
```

Yorumla:
- Tünel KAPALI ise: LAN makinesinden ters SSH tünelinin (`-R 11433`) ayakta olduğunu kontrol et; sertleştirilmiş anahtar tüneli bozmamalı (`docs/modules/ssh-tunel-guvenligi.md`, `scripts/ssh-key-audit.py`).
- `SEDNA_PASSWORD` boşsa özellik bilinçli kapalıdır.
- Loglarda `pymssql`/charset hatası varsa: `CP1254` collation şart (Türkçe), `%`-tuzağı (LIKE paramsız).
Sonucu net özetle: sync **çalışabilir mi**, değilse hangi ön-koşul eksik.
