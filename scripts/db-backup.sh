#!/usr/bin/env bash
# Sprenses PostgreSQL otomatik yedek — pg_dump -Fc (sıkıştırılmış custom format) + rotasyon.
#
# systemd ile günlük çalışır: sprenses-db-backup.service / .timer (03:00).
# Manuel: scripts/db-backup.sh
#
# Off-site (S3) OPSİYONEL — yalnız SPRENSES_BACKUP_S3 set edilirse:
#   SPRENSES_BACKUP_S3=s3://bucket/prefix scripts/db-backup.sh
# (EC2'de IAM role / aws creds gerekir; yoksa atlanır, yerel yedek korunur.)
#
# Ortam değişkenleriyle ayarlanabilir:
#   SPRENSES_BACKUP_DIR (varsayılan /var/backups/sprenses-db)
#   SPRENSES_BACKUP_KEEP (varsayılan 30 — tutulacak son yedek sayısı)
#   SPRENSES_ENV_FILE (varsayılan /home/ec2-user/otel/backend/.env)
set -euo pipefail

ENV_FILE="${SPRENSES_ENV_FILE:-/home/ec2-user/otel/backend/.env}"
BACKUP_DIR="${SPRENSES_BACKUP_DIR:-/var/backups/sprenses-db}"
KEEP="${SPRENSES_BACKUP_KEEP:-30}"
DB_HOST="127.0.0.1"
DB_USER="sprenses"
DB_NAME="sprenses"

# DB şifresi .env'deki DATABASE_URL'den (kodda/argümanda parola tutulmaz; PGPASSWORD ile geçilir)
PASS="$(grep -oP '^DATABASE_URL=postgresql://sprenses:\K[^@]+' "$ENV_FILE" | head -1 || true)"
if [ -z "$PASS" ]; then
    echo "HATA: DATABASE_URL şifresi okunamadı: $ENV_FILE" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/sprenses-${TS}.dump"

# pg_dump custom format (-Fc): sıkıştırılmış; pg_restore ile (seçici/paralel) geri yüklenir.
# Önce .tmp'ye yaz, başarılıysa atomik mv → yarım dosya asla .dump uzantısı almaz.
PGPASSWORD="$PASS" pg_dump -h "$DB_HOST" -U "$DB_USER" -Fc "$DB_NAME" -f "${OUT}.tmp"
mv "${OUT}.tmp" "$OUT"

# Bütünlük doğrulaması: pg_restore TOC'u okuyabilmeli (bozuk/yarım dump'ı yakalar)
if ! pg_restore --list "$OUT" >/dev/null 2>&1; then
    echo "HATA: yedek bütünlük kontrolü başarısız (pg_restore --list): $OUT" >&2
    rm -f "$OUT"
    exit 1
fi

# Rotasyon: en yeni $KEEP dışındakileri sil
ls -1t "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

# Off-site (opsiyonel)
if [ -n "${SPRENSES_BACKUP_S3:-}" ]; then
    if aws s3 cp "$OUT" "${SPRENSES_BACKUP_S3%/}/sprenses-${TS}.dump" --sse AES256; then
        echo "off-site OK: ${SPRENSES_BACKUP_S3%/}/sprenses-${TS}.dump"
    else
        echo "UYARI: S3 yükleme başarısız (yerel yedek korundu)" >&2
    fi
fi

echo "yedek OK: $OUT ($(du -h "$OUT" | cut -f1)) — toplam $(ls -1 "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null | wc -l) yedek"
