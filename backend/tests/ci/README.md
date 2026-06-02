# Test / CI Veritabanı Bootstrap

Bu klasör, testler (pytest) için sıfırdan bir veritabanı kurmanın deterministik
yolunu içerir. Hem GitHub Actions CI'si (`.github/workflows/ci.yml`) hem de yerel
`scripts/setup-test-db.sh` bu dosyaları kullanır.

## Dosyalar

| Dosya | İçerik | Nasıl üretildi |
|---|---|---|
| `01_schema.sql` | Tüm tabloların DDL'i (şema) | `pg_dump --schema-only --no-owner --no-privileges` |
| `02_seed.sql` | Referans veri: roller, modüller, izin matrisi, departmanlar, işlem kategorileri (PII yok) | `pg_dump --data-only` (yalnızca RBAC/konfig tabloları) |
| `seed_admin.py` | `admin` kullanıcısını oluşturur (migration'lar bunu yapmaz) | Elle yazıldı, idempotent |

## Kurulum sırası

```
psql "$DATABASE_URL" -f tests/ci/01_schema.sql   # şema
psql "$DATABASE_URL" -f tests/ci/02_seed.sql     # roller/modüller/izinler
PYTHONPATH=. python tests/ci/seed_admin.py        # admin kullanıcısı
```

Sonra `python -m pytest tests/` çalışır. `conftest.py` her testi bir SAVEPOINT
içinde çalıştırıp sonunda rollback yaptığı için DB kalıcı olarak kirlenmez.

## Neden migration zinciri değil de şema dump'ı?

> ✅ **Düzeltildi:** `alembic upgrade head` artık **sıfırdan temiz uygulanıyor** ve
> `alembic downgrade base` ile tam geri alma da temiz çalışıyor (boş bir DB'de uçtan
> uca doğrulandı). Eskiden bazı autogenerate migration'ları `checks` / `check_uploads`
> tablolarını yanlış sırada drop/recreate ediyordu (`checks.upload_id` FK'si
> `check_uploads`'a bağlıyken önce `check_uploads` düşürülüyor →
> `DependentObjectsStillExist`). Bu gürültü temizlendi:
>
> - `d2c0d2b06bd3` — `checks` tablosu artık model/prod ile birebir (3 ek sütun +
>   `ix_checks_bank_tx` indeksi + `uq_check_no_vendor_date` kısıtı) olarak doğrudan
>   oluşturuluyor; sonradan ekleyen ara migration yoktu, bu yüzden doğduğu yere taşındı.
> - `6a5525e8960a`, `7d052738619a` — alakasız `checks`/`check_uploads` drop/recreate ve
>   diğer autogenerate gürültüsü (indeks/sütun) kaldırıldı; gerçek amaçları
>   (`scheduled_*` ve `agency_groups`) korundu.
> - `69c783a240bc` — downgrade artık upgrade'de kaldırdığı `invoices`/`invoice_attachments`
>   tablolarını ve `finance.faturalar` modülünü geri yüklüyor (`downgrade base` için).
> - `b7c8d9e0f1a2`, `df2165d9264c` — başka migration'ın sahip olduğu indeksleri
>   (`ix_bank_tx_category`, `ix_messages_conv_deleted_created`) artık tekrar yönetmiyor
>   (downgrade'de çift drop / `UndefinedObject` önlendi).

Yine de CI şimdilik production şemasıyla birebir olan **şema dump'ını** kullanmaya
devam ediyor. Sebep: bu görevle **alakasız**, önceden var olan birkaç küçük içerik
farkı migration zinciri ↔ model/prod arasında sürüyor —
`credit_payments` (`tax` ↔ `bsmv`/`commission`), `credit_products.linked_account_id`
(+ `ix_credit_products_linked_account`), ve `scheduled_definitions`/`scheduled_entries`
sunucu varsayılanları/nullability. Bu yüzden prod şemasıyla birebir dump testler için
hâlâ otoriter kaynak. Dump aynı zamanda CLAUDE.md'de belgelenen yerel test-DB kurulum
yönteminin (pg_dump) kodlanmış hâlidir.

**Sonraki adım (opsiyonel, ayrı iş):** Yukarıdaki ilgisiz farklar da giderilip
migration zinciri ↔ model tam eşleşince, CI doğrudan `alembic upgrade head` kullanabilir
ve bu dump'lar kaldırılabilir. Migration zincirinin sağlığını hızlı doğrulamak için
(ayrı bir `*_test` DB'sinde):

```bash
cd backend && source venv/bin/activate
export DATABASE_URL=postgresql://sprenses:PASS@127.0.0.1:5432/sprenses_test
alembic upgrade head && alembic downgrade base   # ikisi de temiz çalışmalı
```

## Şema değiştiğinde dump'ları yenileme

Model/migration ile şema değişince dump'lar güncellenmeli:

```bash
cd backend
BASE_URL=$(grep '^DATABASE_URL' .env | cut -d= -f2-)
PW=$(echo "$BASE_URL" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')
PGPASSWORD="$PW" pg_dump "$BASE_URL" --schema-only --no-owner --no-privileges -f tests/ci/01_schema.sql
PGPASSWORD="$PW" pg_dump "$BASE_URL" --data-only --no-owner --no-privileges \
  --table=roles --table=modules --table=role_module_permissions \
  --table=departments --table=transaction_categories -f tests/ci/02_seed.sql
```
