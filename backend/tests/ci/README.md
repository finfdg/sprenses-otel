# Test / CI Veritabanı Bootstrap

Bu klasör, testler (pytest) için sıfırdan bir veritabanı kurmanın deterministik
yolunu içerir. Hem GitHub Actions CI'si (`.github/workflows/ci.yml`) hem de yerel
`scripts/setup-test-db.sh` aynı bootstrap'ı kullanır.

## Bootstrap nasıl çalışır

Şema artık **doğrudan migration zincirinden** kurulur (`alembic upgrade head`).
Migration zinciri prod şemasıyla birebir olduğu için ayrı bir şema dump'ına
(`01_schema.sql`) gerek kalmadı — dosya kaldırıldı. Sıra:

```
alembic upgrade head                               # şema (migration zinciri)
psql "$DATABASE_URL" -f tests/ci/reset_data.sql    # migration'ın eklediği veriyi temizle
psql "$DATABASE_URL" -f tests/ci/02_seed.sql       # roller/modüller/izinler (RBAC)
PYTHONPATH=. python tests/ci/seed_admin.py         # admin kullanıcısı
```

Sonra `python -m pytest tests/` çalışır. `conftest.py` her testi bir SAVEPOINT
içinde çalıştırıp sonunda rollback yaptığı için DB kalıcı olarak kirlenmez.

## Dosyalar

| Dosya | İçerik | Nasıl üretildi |
|---|---|---|
| `reset_data.sql` | Migration'ların eklediği TÜM veriyi temizler (alembic_version hariç TRUNCATE) ve standalone sequence'leri başa döndürür | Elle yazıldı |
| `02_seed.sql` | Referans veri: roller, modüller, izin matrisi, departmanlar, işlem kategorileri (PII yok) | `pg_dump --data-only` (yalnızca RBAC/konfig tabloları) |
| `seed_admin.py` | `admin` kullanıcısını oluşturur (migration'lar bunu yapmaz) | Elle yazıldı, idempotent |

### Neden `reset_data.sql`?

`alembic upgrade head` yalnızca şemayı kurmaz; bazı migration'lar referans/örnek veri
de ekler (modüller, roller, izinler + örnek banka hesapları, nakit akımları, oda
tipleri vb.). Bu veri sorunludur:

- **Kısmî RBAC kümesidir** (prod'un tamamı değil) ve `02_seed.sql`'in `COPY`'siyle
  (açık ID'li) PK/unique çakışması yaratır.
- **Örnek finans verisi** testlerin "temiz tablo" beklentisini bozar.

Bu yüzden alembic'ten sonra `reset_data.sql` tüm tabloları (`alembic_version` hariç)
`TRUNCATE ... RESTART IDENTITY CASCADE` ile boşaltır ve `TRUNCATE`'in dokunmadığı
standalone sequence'leri (ör. `match_number_seq`) `ALTER SEQUENCE ... RESTART` ile
sıfırlar; ardından `02_seed.sql` otoriter RBAC verisini yükler. Sonuç, eski şema-dump
yöntemiyle **birebir aynı** test DB'sidir (prod şeması + RBAC referans verisi + admin).

## Migration zinciri sağlığı

`alembic upgrade head` ve `alembic downgrade base` ikisi de sıfırdan temiz çalışır ve
ileri yönde kurulan şema prod (`sprenses`) ile **birebir** aynıdır (kolon / indeks /
kısıt / sunucu varsayılanı). Hızlı doğrulama (ayrı bir throwaway `*_test` DB'sinde):

```bash
cd backend && source venv/bin/activate
export DATABASE_URL=postgresql://sprenses:PASS@127.0.0.1:5432/sprenses_test
alembic upgrade head && alembic downgrade base   # ikisi de temiz çalışmalı
```

Şema farkını prod ile doğrulamak için (boş bir DB'ye `alembic upgrade head` çalıştırıp
aşağıdaki sorguları normalize/sıralı diff'le — hepsi BİREBİR olmalı):

```sql
-- kolonlar
SELECT table_name||'|'||column_name||'|'||data_type||'|'||is_nullable
FROM information_schema.columns WHERE table_schema='public' ORDER BY 1;
-- indeksler
SELECT tablename||'|'||indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1;
-- kısıtlar
SELECT conrelid::regclass::text||'|'||conname||'|'||pg_get_constraintdef(oid)
FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY 1;
```

> **Tarihçe:** Eskiden migration zinciri ↔ prod arasında bu görevle alakasız birkaç
> içerik farkı vardı ve dump otoriter kaynaktı. Bunlar giderildi (prod head'de stamp'li
> olduğundan değişiklikler ilgili migration'ların `create_table` bloklarına gömüldü;
> yeniden çalışmaz):
> - `credit_payments`: `tax` → `bsmv` + `commission` (`20327ad823d2`)
> - `credit_products`: `linked_account_id` sütunu + FK + `ix_credit_products_linked_account` (`20327ad823d2`)
> - `scheduled_definitions` / `scheduled_entries`: sunucu varsayılanları + `created_at`/`updated_at` nullable (`6a5525e8960a`)
> - `approval_workflows.name`: UNIQUE kısıtı kaldırıldı — prod'da yoktu; isim tekrarı
>   uygulama seviyesinde engellenir (`bfaaaa45cc57`, dosyadaki nota bakın)

## 02_seed.sql'i yenileme

RBAC referans verisi (roller / modüller / izinler / departmanlar / işlem kategorileri)
değişince `02_seed.sql` güncellenmeli:

```bash
cd backend
BASE_URL=$(grep '^DATABASE_URL' .env | cut -d= -f2-)
PW=$(echo "$BASE_URL" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')
PGPASSWORD="$PW" pg_dump "$BASE_URL" --data-only --no-owner --no-privileges \
  --table=roles --table=modules --table=role_module_permissions \
  --table=departments --table=transaction_categories -f tests/ci/02_seed.sql
```

Şema değişiklikleri için ayrı bir dump'a gerek yoktur — `alembic upgrade head` otoriter
kaynaktır. Yeni migration eklerken yukarıdaki diff ile prod birebirliğini doğrula.
