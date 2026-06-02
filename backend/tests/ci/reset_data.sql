-- Test/CI veritabanı: migration'ların eklediği TÜM veriyi temizler.
--
-- `alembic upgrade head` şemayı kurarken bazı migration'lar referans/örnek veri de
-- ekler (modüller, roller, izinler + örnek banka hesapları, nakit akımları, oda
-- tipleri vb.). Testler temiz tablolar beklediği için (eski şema-dump yöntemiyle
-- birebir kalmak adına) bu veri silinir; ardından 02_seed.sql otoriter RBAC referans
-- verisini, seed_admin.py de admin kullanıcısını yükler.
--
-- alembic_version korunur (zincirin head'de olduğu bilgisi kaybolmasın). CASCADE ile
-- FK bağımlılık sırası otomatik çözülür; bu aşamada tüm tablolar (varsa migration
-- seed'i) cascade için güvenlidir çünkü uygulama verisi henüz yoktur.

SET client_min_messages = warning;  -- TRUNCATE ... CASCADE NOTICE gürültüsünü bastır

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
    LOOP
        EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE';
    END LOOP;
END $$;

-- TRUNCATE ... RESTART IDENTITY yalnızca bir kolona ait (OWNED BY) sequence'leri sıfırlar.
-- Standalone sequence'ler (ör. match_number_seq) bundan etkilenmez; migration'lar onları
-- ilerletmiş olabileceğinden ayrıca başlangıca döndürülür ki test DB'si sıfırdan kurulmuş
-- şemayla birebir aynı sequence durumuna sahip olsun.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT s.relname
        FROM pg_class s
        JOIN pg_namespace n ON n.oid = s.relnamespace
        WHERE s.relkind = 'S' AND n.nspname = 'public'
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d WHERE d.objid = s.oid AND d.deptype = 'a'
          )
    LOOP
        EXECUTE 'ALTER SEQUENCE public.' || quote_ident(r.relname) || ' RESTART';
    END LOOP;
END $$;
