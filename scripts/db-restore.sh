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

    STAGE="$(mktemp -d /tmp/sprenses-restore-drill-XXXXXX)"
    # shellcheck disable=SC2064
    trap "rm -rf '$STAGE'" EXIT
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

    echo "TATBİKAT OK — geçici DB temizlendi. Yedek geri yüklenebilir: $DUMP"
fi
