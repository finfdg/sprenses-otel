#!/usr/bin/env bash
# Sprenses PostgreSQL geri yükleme / restore TATBİKATI.
#
# KULLANIM:
#   scripts/db-restore.sh                  → EN SON yedeği geçici DB'ye yükle + satır say (TATBİKAT — güvenli)
#   scripts/db-restore.sh <dump>           → belirtilen dump'ı geçici DB'ye (tatbikat)
#   scripts/db-restore.sh <dump> sprenses  → ÜRETİME geri yükle (DİKKAT: mevcut veri SİLİNİR — elle 'EVET' onayı)
#
# Tatbikat (sprenses_restore_test): DB postgres yerel-socket ile oluşturulur/yüklenir (pg_hba md5 gerekmez),
#   doğrulama sonrası DROP edilir. Üretim (sprenses): owner=sprenses olsun diye md5 ile geri yüklenir.
set -euo pipefail

ENV_FILE="${SPRENSES_ENV_FILE:-/home/ec2-user/otel/backend/.env}"
BACKUP_DIR="${SPRENSES_BACKUP_DIR:-/var/backups/sprenses-db}"
DB_HOST="127.0.0.1"
DB_USER="sprenses"
DRILL_DB="sprenses_restore_test"

DUMP="${1:-$(ls -1t "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null | head -1 || true)}"
TARGET="${2:-$DRILL_DB}"

[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "HATA: dump bulunamadı: '${DUMP:-<yok>}'" >&2; exit 1; }
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
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$TARGET'" | grep -q 1; then
        sudo -u postgres psql -c "DROP DATABASE \"$TARGET\";" >/dev/null
    fi
    sudo -u postgres psql -c "CREATE DATABASE \"$TARGET\" OWNER $DB_USER;" >/dev/null
    sudo -u postgres pg_restore --no-owner --no-privileges -d "$TARGET" "$DUMP"
    echo "=== '$TARGET' satır sayıları (yedeğin geri yüklenebilirliği) ==="
    for t in users roles modules finance_events vendor_transactions checks credit_products reservations audit_logs; do
        n="$(sudo -u postgres psql -d "$TARGET" -tAc "SELECT count(*) FROM $t;" 2>/dev/null || echo '?')"
        printf '  %-22s %s\n' "$t" "$n"
    done
    sudo -u postgres psql -c "DROP DATABASE \"$TARGET\";" >/dev/null
    echo "TATBİKAT OK — geçici DB temizlendi. Yedek geri yüklenebilir: $DUMP"
fi
