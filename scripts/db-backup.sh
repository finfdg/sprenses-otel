#!/usr/bin/env bash
# Sprenses otomatik yedek — PostgreSQL (pg_dump -Fc) + yüklenen dosyalar (uploads/).
#
# systemd ile günlük çalışır: sprenses-db-backup.service / .timer (03:00).
# Manuel: scripts/db-backup.sh
#
# KAPSAM (2026-07-25, denetim DR-001):
#   1) DB  → sprenses-<ts>.dump           (pg_dump -Fc, bütünlük doğrulamalı, KEEP kopya)
#   2) uploads/ → uploads-snapshots/<ts>/ (rsync --link-dest hardlink snapshot, KEEP_UPLOADS kopya)
#
#   uploads NEDEN tar DEĞİL: 285 MB'ın çoğu zaten sıkıştırılmış (pdf/xls/jpg) → tar.gz ~250 MB
#   ve 30 günlük tam kopya ≈ 7,5 GB olurdu (30 GB diskte kabul edilemez). Hardlink snapshot'ta
#   DEĞİŞMEYEN dosya ek yer kaplamaz → 30 snapshot ≈ tek kopya + değişimler. Her snapshot yine
#   TAM bir dizin gibi görünür (restore = doğrudan kopyala, çıkarma adımı yok).
#
# Off-site (S3) OPSİYONEL — yalnız SPRENSES_BACKUP_S3 set edilirse (DR-002 hâlâ AÇIK):
#   SPRENSES_BACKUP_S3=s3://bucket/prefix scripts/db-backup.sh
# (EC2'de IAM role / aws creds gerekir; yoksa atlanır, yerel yedek korunur.)
# uploads off-site'a tar.gz olarak gider — S3'e dizin göndermek pahalı (dosya başına istek).
#
# Ortam değişkenleriyle ayarlanabilir:
#   SPRENSES_BACKUP_DIR      (varsayılan /var/backups/sprenses-db)
#   SPRENSES_UPLOADS_DIR     (varsayılan /var/backups/sprenses-uploads)
#   SPRENSES_UPLOADS_SRC     (varsayılan /home/ec2-user/otel/backend/uploads)
#   SPRENSES_BACKUP_KEEP     (varsayılan 30)
#   SPRENSES_UPLOADS_KEEP    (varsayılan 30)
#   SPRENSES_MIN_FREE_MB     (varsayılan 2000 — altındaysa yedek ALINMAZ)
#   SPRENSES_SKIP_UPLOADS=1  (yalnız DB yedeği al)
#   SPRENSES_ENV_FILE        (varsayılan /home/ec2-user/otel/backend/.env)
set -euo pipefail

# Yedekler finans + KVKK kapsamı veri içerir → dünya-okunur OLMAMALI (denetim DR-002).
umask 077

ENV_FILE="${SPRENSES_ENV_FILE:-/home/ec2-user/otel/backend/.env}"
BACKUP_DIR="${SPRENSES_BACKUP_DIR:-/var/backups/sprenses-db}"
UPLOADS_BACKUP_DIR="${SPRENSES_UPLOADS_DIR:-/var/backups/sprenses-uploads}"
UPLOADS_SRC="${SPRENSES_UPLOADS_SRC:-/home/ec2-user/otel/backend/uploads}"
KEEP="${SPRENSES_BACKUP_KEEP:-30}"
UPLOADS_KEEP="${SPRENSES_UPLOADS_KEEP:-30}"
MIN_FREE_MB="${SPRENSES_MIN_FREE_MB:-2000}"
DB_HOST="127.0.0.1"
DB_USER="sprenses"
DB_NAME="sprenses"

# ─── Disk bekçisi ────────────────────────────────────────────────────────────
# Disk dolarsa PostgreSQL DURUR (denetim SRV-001). Yedek işi, koruduğu sistemi
# öldürmemeli → yer yoksa yedek almayı reddet ve GÖRÜNÜR hata ver.
mkdir -p "$BACKUP_DIR"
FREE_MB="$(df -Pm "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
if [ "$FREE_MB" -lt "$MIN_FREE_MB" ]; then
    echo "HATA: disk alanı yetersiz — boş ${FREE_MB} MB < gereken ${MIN_FREE_MB} MB; yedek alınmadı" >&2
    exit 1
fi

# DB şifresi .env'deki DATABASE_URL'den (kodda/argümanda parola tutulmaz; PGPASSWORD ile geçilir)
PASS="$(grep -oP '^DATABASE_URL=postgresql://sprenses:\K[^@]+' "$ENV_FILE" | head -1 || true)"
if [ -z "$PASS" ]; then
    echo "HATA: DATABASE_URL şifresi okunamadı: $ENV_FILE" >&2
    exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/sprenses-${TS}.dump"

# ─── 1) Veritabanı ───────────────────────────────────────────────────────────
# pg_dump custom format (-Fc): sıkıştırılmış; pg_restore ile (seçici/paralel) geri yüklenir.
# Önce .tmp'ye yaz, başarılıysa atomik mv → yarım dosya asla .dump uzantısı almaz.
PGPASSWORD="$PASS" pg_dump -h "$DB_HOST" -U "$DB_USER" -Fc "$DB_NAME" -f "${OUT}.tmp"
mv "${OUT}.tmp" "$OUT"
chmod 600 "$OUT"

# Bütünlük doğrulaması: pg_restore TOC'u okuyabilmeli (bozuk/yarım dump'ı yakalar)
if ! pg_restore --list "$OUT" >/dev/null 2>&1; then
    echo "HATA: yedek bütünlük kontrolü başarısız (pg_restore --list): $OUT" >&2
    rm -f "$OUT"
    exit 1
fi

# Rotasyon: en yeni $KEEP dışındakileri sil
ls -1t "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

# Geçmişten kalan gevşek izinleri de sıkılaştır (0644 → 0600; denetim DR-002)
chmod 600 "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null || true
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

echo "DB yedeği OK: $OUT ($(du -h "$OUT" | cut -f1)) — toplam $(ls -1 "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null | wc -l) yedek"

# ─── 2) Yüklenen dosyalar (uploads/) ─────────────────────────────────────────
# DB geri yüklense bile bu dosyalar olmadan her file_url dangling kalır: banka ekstreleri,
# cari Excel'leri, çek/rezervasyon/kontrat PDF'leri = geri getirilemez mali belge (DR-001).
UPLOADS_SNAP=""
if [ "${SPRENSES_SKIP_UPLOADS:-0}" != "1" ] && [ -d "$UPLOADS_SRC" ]; then
    mkdir -p "$UPLOADS_BACKUP_DIR"
    chmod 700 "$UPLOADS_BACKUP_DIR" 2>/dev/null || true
    SNAP="$UPLOADS_BACKUP_DIR/$TS"
    PREV="$(ls -1d "$UPLOADS_BACKUP_DIR"/*/ 2>/dev/null | grep -v "/${TS}/$" | sort | tail -1 || true)"

    LINK_ARG=()
    [ -n "$PREV" ] && LINK_ARG=(--link-dest="${PREV%/}")

    # .tmp'ye yaz → başarılıysa atomik mv (yarım snapshot tarih adını almaz)
    rm -rf "${SNAP}.tmp"
    if rsync -a --delete "${LINK_ARG[@]}" "${UPLOADS_SRC}/" "${SNAP}.tmp/"; then
        mv "${SNAP}.tmp" "$SNAP"
        UPLOADS_SNAP="$SNAP"

        # Bütünlük: kaynak ile snapshot dosya sayısı eşleşmeli
        SRC_N="$(find "$UPLOADS_SRC" -type f | wc -l)"
        SNAP_N="$(find "$SNAP" -type f | wc -l)"
        if [ "$SRC_N" -ne "$SNAP_N" ]; then
            echo "UYARI: uploads snapshot dosya sayısı uyuşmuyor (kaynak $SRC_N / snapshot $SNAP_N)" >&2
        fi

        # Rotasyon — ADA göre sırala, mtime'a DEĞİL.
        # `ls -dt` (mtime) BURADA ÇALIŞMAZ: `rsync -a` dizin zaman damgalarını KAYNAKTAN
        # kopyalar → tüm snapshot dizinleri aynı mtime'ı alır (canlıda dördü de
        # 2026-07-17 10:30:22 çıktı) ve sıralama anlamsızlaşır; rotasyon EN YENİYİ
        # silebilirdi. Dizin adı YYYYMMDD-HHMMSS olduğundan sözlüksel sıralama = zaman
        # sıralaması. `sort -r` ile en yeniden eskiye, ilk KEEP tanesi korunur.
        ls -1d "$UPLOADS_BACKUP_DIR"/*/ 2>/dev/null | sort -r | tail -n +"$((UPLOADS_KEEP + 1))" \
            | xargs -r rm -rf

        echo "uploads snapshot OK: $SNAP ($SNAP_N dosya) — toplam $(ls -1d "$UPLOADS_BACKUP_DIR"/*/ 2>/dev/null | wc -l) snapshot, dizin $(du -sh "$UPLOADS_BACKUP_DIR" | cut -f1)"
    else
        echo "UYARI: uploads snapshot alınamadı (DB yedeği korundu)" >&2
        rm -rf "${SNAP}.tmp"
    fi
fi

# ─── 3) Off-site (opsiyonel — DR-002) ────────────────────────────────────────
if [ -n "${SPRENSES_BACKUP_S3:-}" ]; then
    if aws s3 cp "$OUT" "${SPRENSES_BACKUP_S3%/}/sprenses-${TS}.dump" --sse AES256; then
        echo "off-site DB OK: ${SPRENSES_BACKUP_S3%/}/sprenses-${TS}.dump"
    else
        echo "UYARI: S3 DB yükleme başarısız (yerel yedek korundu)" >&2
    fi

    # uploads S3'e tar.gz olarak (dizin senkronu dosya başına istek = pahalı/yavaş)
    if [ -n "$UPLOADS_SNAP" ]; then
        TARBALL="$UPLOADS_BACKUP_DIR/uploads-${TS}.tgz"
        if tar czf "$TARBALL" -C "$UPLOADS_SNAP" . \
           && tar tzf "$TARBALL" >/dev/null 2>&1 \
           && aws s3 cp "$TARBALL" "${SPRENSES_BACKUP_S3%/}/uploads-${TS}.tgz" --sse AES256; then
            echo "off-site uploads OK: ${SPRENSES_BACKUP_S3%/}/uploads-${TS}.tgz"
        else
            echo "UYARI: uploads off-site yükleme başarısız" >&2
        fi
        rm -f "$TARBALL"   # yerelde snapshot zaten var, tar yalnız taşıma aracıydı
    fi
else
    echo "NOT: off-site (S3) yapılandırılmamış — SPRENSES_BACKUP_S3 boş. Yedekler yalnız BU diskte (DR-002)."
fi
