---
description: Alembic migration oluştur, ÜRETİLEN DOSYAYI GÖZDEN GEÇİR, sonra uygula
argument-hint: "<migration açıklaması>"
---
Alembic migration akışı. Açıklama: `$ARGUMENTS`.

**1) Revize üret:**
```bash
cd /home/ec2-user/otel/backend && source venv/bin/activate
alembic revision --autogenerate -m "$ARGUMENTS"
```

**2) ⚠️ UYGULAMADAN ÖNCE üretilen dosyayı GÖZDEN GEÇİR (zorunlu):**
- `alembic/versions/`'daki yeni dosyayı **oku**. `--autogenerate` sık sık yanlış üretir: gereksiz `drop_index`/`drop_table`, `server_default` farkı, enum/JSON kolon yeniden-oluşturma, sıralama hataları. Yanlış komutları **elle düzelt**.
- `down_revision` zincirin başını doğru gösteriyor mu? (CI test DB'yi bu zincirden kurar — zincir prod ile birebir olmalı, `backend/tests/ci/README.md`.)
- Şüpheli `DROP`/veri-kaybı riski varsa **kullanıcıya sor**, körlemesine uygulama.

**3) Onaylanınca uygula:**
```bash
alembic upgrade head
```

**4) Deploy:** kod da değiştiyse `/deploy backend`.

Migration'ı asla gözden geçirmeden `upgrade head` yapma. Geri alma gerekirse: `alembic downgrade -1`.
