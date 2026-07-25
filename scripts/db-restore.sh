#!/usr/bin/env bash
# Sprenses PostgreSQL geri yükleme / restore TATBİKATI.
#
# KULLANIM:
#   scripts/db-restore.sh                  → EN SON YEREL yedeği geçici DB'ye yükle + satır say (TATBİKAT)
#   scripts/db-restore.sh --offsite        → EN SON OFF-SITE (S3) yedeği indir + geçici DB'ye yükle (DR TATBİKATI)
#   scripts/db-restore.sh <dump>           → belirtilen dump'ı geçici DB'ye (yerel yol veya s3://... )
#   scripts/db-restore.sh <dump> sprenses  → ÜRETİME geri yükle (DİKKAT: mevcut veri SİLİNİR — elle 'EVET' onayı)
#
# Tatbikat (sprenses_restore_test): DB postgres yerel-socket ile oluşturulur/yüklenir (pg_hba md5 gerekmez),
#   doğrulama sonrası DROP edilir. Üretim (sprenses): owner=sprenses olsun diye md5 ile geri yüklenir.
#
# `--offsite` NEDEN AYRI BİR MOD (denetim DR-002 kapanış kriteri): "yedek S3'e gidiyor"
# ile "S3'teki yedekten geri dönülebiliyor" AYNI ŞEY DEĞİLDİR. Yalnız PutObject veren bir
# IAM policy'de yükleme her gün yeşil görünür ama felaket anında GetObject reddedilir —
# yedek fiilen yoktur. Bu mod tam da o yolu (indir → bütünlük → geri yükle → say) koşar.
set -euo pipefail

# shellcheck source=scripts/_offsite-lib.sh
. "$(dirname "$(readlink -f "$0")")/_offsite-lib.sh"

ENV_FILE="${SPRENSES_ENV_FILE:-/home/ec2-user/otel/backend/.env}"
BACKUP_DIR="${SPRENSES_BACKUP_DIR:-/var/backups/sprenses-db}"
OFFSITE_DROPIN="/etc/systemd/system/sprenses-db-backup.service.d/offsite.conf"
DB_HOST="127.0.0.1"
DB_USER="sprenses"
DRILL_DB="sprenses_restore_test"

# Off-site hedefi: ortamdan, yoksa günlük yedeğin systemd drop-in'inden (tek kaynak —
# operatör tatbikat için URI'yi ezberlemek zorunda kalmasın, yanlış bucket'a bakmasın).
offsite_uri() {
    if [ -n "${SPRENSES_BACKUP_S3:-}" ]; then printf '%s' "$SPRENSES_BACKUP_S3"; return 0; fi
    [ -r "$OFFSITE_DROPIN" ] && sed -n 's/^Environment=SPRENSES_BACKUP_S3=//p' "$OFFSITE_DROPIN" | head -1
}

OFFSITE_MODE=0
if [ "${1:-}" = "--offsite" ]; then OFFSITE_MODE=1; shift; fi

DUMP="${1:-}"
TARGET="${2:-$DRILL_DB}"

# Geçici dosyalar TEK trap ile toplanır. (İki ayrı `trap ... EXIT` yazılırsa ikincisi
# birincisini SESSİZCE ezer; indirilen dump /tmp'de kalırdı — finans verisi orada durmamalı.)
FETCHED=""
STAGE=""
cleanup() {
    [ -n "$FETCHED" ] && rm -f "$FETCHED"
    [ -n "$STAGE" ] && rm -rf "$STAGE"
    return 0
}
trap cleanup EXIT

if [ "$OFFSITE_MODE" -eq 1 ]; then
    S3URI="$(offsite_uri)"
    [ -n "$S3URI" ] || { echo "HATA: off-site yapılandırılmamış (SPRENSES_BACKUP_S3 boş ve $OFFSITE_DROPIN yok)" >&2; exit 1; }
    echo "=== OFF-SITE TATBİKATI: $S3URI ==="
    offsite_assert_cross_region "$S3URI" || exit 1
    KEY="$(offsite_latest_key "${S3URI%/}/db")"
    [ -n "$KEY" ] || { echo "HATA: off-site'ta hiç dump yok: ${S3URI%/}/db/" >&2; exit 1; }
    FETCHED="$(mktemp /tmp/sprenses-offsite-XXXXXX.dump)"
    echo "indiriliyor: ${S3URI%/}/db/$KEY"
    aws s3 cp "${S3URI%/}/db/$KEY" "$FETCHED" >/dev/null \
        || { echo "HATA: off-site dump indirilemedi (GetObject izni var mı?)" >&2; exit 1; }
    DUMP="$FETCHED"
elif [ -n "$DUMP" ] && [ "${DUMP#s3://}" != "$DUMP" ]; then
    FETCHED="$(mktemp /tmp/sprenses-offsite-XXXXXX.dump)"
    echo "indiriliyor: $DUMP"
    aws s3 cp "$DUMP" "$FETCHED" >/dev/null || { echo "HATA: indirilemedi: $DUMP" >&2; exit 1; }
    DUMP="$FETCHED"
elif [ -z "$DUMP" ]; then
    DUMP="$(ls -1t "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null | head -1 || true)"
fi

[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "HATA: dump bulunamadı: '${DUMP:-<yok>}'" >&2; exit 1; }

# İndirilen dosya gerçekten geri yüklenebilir bir dump mı? (yarım/boş/HTML hata sayfası)
pg_restore --list "$DUMP" >/dev/null 2>&1 \
    || { echo "HATA: dump bütünlük kontrolünü geçemedi (pg_restore --list): $DUMP" >&2; exit 1; }
PASS="$(grep -oP '^DATABASE_URL=postgresql://sprenses:\K[^@]+' "$ENV_FILE" | head -1 || true)"
[ -n "$PASS" ] || { echo "HATA: DATABASE_URL şifresi okunamadı: $ENV_FILE" >&2; exit 1; }

echo "Geri yükleniyor: $DUMP → $TARGET"

if [ "$TARGET" = "sprenses" ]; then
    # ── ÜRETİME geri yükleme ─────────────────────────────────────────────
    echo "!!! ÜRETİM DB'sine ($TARGET) geri yüklenecek — MEVCUT TÜM VERİ SİLİNECEK !!!"
    read -r -p "Onaylamak için 'EVET' yazın: " ok
    [ "$ok" = "EVET" ] || { echo "iptal edildi"; exit 1; }
    # owner=sprenses olsun diye sprenses rolüyle (md5) geri yükle; mevcut nesneleri temizle
    PGPASSWORD="$PASS" pg_restore -h "$DB_HOST" -U "$DB_USER" --clean --if-exists \
        --no-owner --no-privileges -d "$TARGET" "$DUMP"
    echo "=== '$TARGET' satır sayıları ==="
    for t in users roles modules finance_events vendor_transactions checks credit_products reservations audit_logs; do
        n="$(PGPASSWORD="$PASS" psql -h "$DB_HOST" -U "$DB_USER" -d "$TARGET" -tAc "SELECT count(*) FROM $t;" 2>/dev/null || echo '?')"
        printf '  %-22s %s\n' "$t" "$n"
    done
    echo "GERİ YÜKLEME TAMAM: $DUMP → $TARGET"
else
    # ── TATBİKAT (geçici DB) — postgres yerel-socket (pg_hba/md5 gerekmez) ─
    #
    # DUMP'I SAHNELE: yedekler 2026-07-25'te sertleştirildi (dosya 0600 / dizin 0700,
    # sahibi ec2-user) → `sudo -u postgres pg_restore` ONLARI OKUYAMAZ ve tatbikat
    # "Permission denied" ile ölüyordu. Sertleştirme doğru (finans+KVKK verisi dünyaya
    # açık olmamalı) ama felaket kurtarmayı sessizce kırmıştı — ilk gerçek tatbikatta
    # yakalandı. Çözüm: dump'ı postgres'in okuyabileceği geçici bir kopyaya al, tatbikat
    # bitince sil. Kaynak yedeğin izinleri DEĞİŞMEZ.
    # `sudo -u postgres` çalışma dizinini miras alır; postgres /home/ec2-user/otel'i
    # okuyamadığından her çağrıda "could not change directory" uyarısı basıyordu
    # (zararsız ama tatbikat çıktısını kirletiyor, gerçek hatayı gizleyebilir).
    cd /tmp

    STAGE="$(mktemp -d /tmp/sprenses-restore-drill-XXXXXX)"   # tek `cleanup` trap'i siler
    chmod 755 "$STAGE"
    cp "$DUMP" "$STAGE/dump"
    chmod 644 "$STAGE/dump"

    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$TARGET'" | grep -q 1; then
        sudo -u postgres psql -c "DROP DATABASE \"$TARGET\";" >/dev/null
    fi
    sudo -u postgres psql -c "CREATE DATABASE \"$TARGET\" OWNER $DB_USER;" >/dev/null
    sudo -u postgres pg_restore --no-owner --no-privileges -d "$TARGET" "$STAGE/dump"
    echo "=== '$TARGET' satır sayıları (yedeğin geri yüklenebilirliği) ==="
    for t in users roles modules finance_events vendor_transactions checks credit_products reservations audit_logs; do
        n="$(sudo -u postgres psql -d "$TARGET" -tAc "SELECT count(*) FROM $t;" 2>/dev/null || echo '?')"
        printf '  %-22s %s\n' "$t" "$n"
    done
    sudo -u postgres psql -c "DROP DATABASE \"$TARGET\";" >/dev/null

    # ── uploads snapshot tatbikatı (DR-001) ──────────────────────────────
    # DB tek başına yetmez: geri yüklense bile dosyalar yoksa her file_url dangling
    # kalır. Kapanış kriteri "tatbikat örnek dosyayı doğrular" diyor → burada yapılır.
    UPLOADS_BACKUP_DIR="${SPRENSES_UPLOADS_DIR:-/var/backups/sprenses-uploads}"
    UPLOADS_SRC="${SPRENSES_UPLOADS_SRC:-/home/ec2-user/otel/backend/uploads}"
    SNAP="$(ls -1d "$UPLOADS_BACKUP_DIR"/*/ 2>/dev/null | sort | tail -1 || true)"
    if [ -n "$SNAP" ]; then
        SNAP_N="$(find "$SNAP" -type f | wc -l)"
        echo "=== uploads snapshot tatbikatı ==="
        echo "  snapshot : $(basename "${SNAP%/}") ($SNAP_N dosya)"
        # Rastgele 5 mali belge: snapshot ↔ kaynak checksum karşılaştırması
        OK=0; BAD=0
        while IFS= read -r rel; do
            [ -z "$rel" ] && continue
            a="$(md5sum "$SNAP$rel" 2>/dev/null | cut -d" " -f1)"
            b="$(md5sum "$UPLOADS_SRC/$rel" 2>/dev/null | cut -d" " -f1)"
            if [ -n "$a" ] && [ "$a" = "$b" ]; then OK=$((OK+1)); else BAD=$((BAD+1)); fi
        done <<< "$(cd "$SNAP" && find . -type f \( -name "*.pdf" -o -name "*.xls*" \) \
                    | sed "s|^\./||" | shuf -n 5 2>/dev/null)"
        echo "  örneklem : $OK eşleşti / $BAD uyuşmadı"
        [ "$BAD" -gt 0 ] && echo "  UYARI: snapshot ile kaynak arasında fark var" >&2
    else
        echo "UYARI: uploads snapshot bulunamadı — DB geri yüklense bile dosyalar KAYIP" >&2
    fi

    # ── off-site uploads tatbikatı (DR-002) ──────────────────────────────
    # DB'yi S3'ten geri getirmek yetmez: instance tamamen kaybolduğunda YEREL
    # snapshot da yoktur → belgeler yalnız S3'ten gelebilir. Burada gerçekten
    # S3'ten İNDİRİP kaynakla checksum karşılaştırıyoruz (listelemek kanıt değil).
    if [ "$OFFSITE_MODE" -eq 1 ]; then
        echo "=== off-site uploads tatbikatı ==="
        OS_OK=0; OS_BAD=0
        OS_TMP="$(mktemp -d /tmp/sprenses-offsite-uploads-XXXXXX)"
        while IFS= read -r key; do
            [ -z "$key" ] && continue
            if aws s3 cp "${S3URI%/}/uploads/$key" "$OS_TMP/probe" >/dev/null 2>&1 \
               && [ "$(md5sum "$OS_TMP/probe" | cut -d' ' -f1)" = \
                    "$(md5sum "$UPLOADS_SRC/$key" 2>/dev/null | cut -d' ' -f1)" ]; then
                OS_OK=$((OS_OK+1))
            else
                OS_BAD=$((OS_BAD+1)); echo "  uyuşmadı/indirilemedi: $key" >&2
            fi
            rm -f "$OS_TMP/probe"
        done <<< "$(aws s3 ls "${S3URI%/}/uploads/" --recursive 2>/dev/null \
                    | awk '{print $NF}' | sed "s|^.*/uploads/||" | grep -E '\.(pdf|xlsx?|jpe?g)$' \
                    | shuf -n 5 2>/dev/null)"
        rm -rf "$OS_TMP"
        echo "  örneklem : $OS_OK indirildi+eşleşti / $OS_BAD sorunlu"
        [ "$OS_BAD" -gt 0 ] && { echo "HATA: off-site belge doğrulaması başarısız" >&2; exit 1; }
        [ "$OS_OK" -eq 0 ] && { echo "HATA: off-site'ta hiç belge bulunamadı — uploads aynalanmamış" >&2; exit 1; }
    fi

    echo "TATBİKAT OK — geçici DB temizlendi. Yedek geri yüklenebilir: $DUMP"
    # `[ ... ] && echo` YAZMA: script'in SON komutu olduğunda koşul yanlışsa çıkış kodu
    # 1 olur ve `set -e` altında tatbikat başarısız görünür.
    if [ "$OFFSITE_MODE" -eq 1 ]; then
        echo "OFF-SITE TATBİKATI GEÇTİ — S3'teki kopyadan uçtan uca geri dönülebilir."
    fi
fi
