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

> ⚠️ **Önemli:** `alembic upgrade head` şu an **sıfırdan temiz uygulanmıyor.**
> Bazı autogenerate migration'ları (`6a5525e8960a`, `7d052738619a`,
> `d2c0d2b06bd3`) `checks` / `check_uploads` tablolarını yanlış sırada
> drop/recreate ediyor (`checks.upload_id` FK'si `check_uploads`'a bağlıyken
> önce `check_uploads` düşürülmeye çalışılıyor → `DependentObjectsStillExist`).
> Production ve mevcut test DB'leri migration'larla **kademeli** kurulduğu için
> bu hata fark edilmemiş; sıfırdan replay'de ortaya çıkıyor.

Bu yüzden CI, production şemasıyla birebir olan bir **şema dump'ı** kullanır.
Bu aynı zamanda CLAUDE.md'de belgelenen mevcut yerel test-DB kurulum yönteminin
(pg_dump) kodlanmış hâlidir.

**Yapılması gereken (ayrı iş):** Migration zinciri sıfırdan uygulanabilir hâle
getirilmeli (drop sırası düzeltilmeli / CASCADE eklenmeli). O düzeltmeden sonra
CI doğrudan `alembic upgrade head` kullanabilir ve bu dump'lar kaldırılabilir.

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
