---
description: Backend (pytest) ve/veya frontend (vitest) testlerini doğru test DB ile çalıştır
argument-hint: "[backend|frontend|all] [opsiyonel pytest yol/filtre]"
---
Bu projenin testlerini çalıştır. Argüman: `$ARGUMENTS` (boşsa hedef = **all**).

**ÖNEMLİ — backend test DB izolasyonu:**
- pytest YALNIZCA adı `_test` içeren bir DB'ye bağlanmalı (`conftest.py` prod DB'yi reddeder).
- DB şifresi `.env`'den **runtime'da** çıkarılır — bu dosyaya ASLA hardcode edilmez (dosya git'e commit'lenir).

### Backend (hedef `backend` veya `all`)
```bash
cd /home/ec2-user/otel/backend && source venv/bin/activate
PASS=$(grep -E "^DATABASE_URL" .env | sed -E 's#postgresql://[^:]+:([^@]+)@.*#\1#')
export DATABASE_URL="postgresql://sprenses:${PASS}@127.0.0.1:5432/sprenses_test"
python -m pytest tests/ -q
```
Argümanda pytest yol/filtre verilmişse (ör. `test_checks.py`, `-k sedna`, `tests/test_onay.py::TestX`) `tests/` yerine onu kullan.
Kapsam istenirse: `--cov=app --cov-report=term-missing` ekle (CI eşiği %60, yerel ölçüm ~%66).

### Frontend (hedef `frontend` veya `all`)
```bash
cd /home/ec2-user/otel/frontend && npx vitest run
```

Çıktıyı özetle: kaç geçti / kaldı / atlandı. Hata varsa ilgili `dosya:satır`'ı göster ve düzeltme önermeden önce kök nedeni açıkla. Testlerin gerçekten çalıştığını ve sonucu olduğu gibi raporla.
