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
# 3) OFF-SITE (S3) — yalnız SPRENSES_BACKUP_S3 set edilirse (denetim DR-002):
#      SPRENSES_BACKUP_S3=s3://bucket/prefix scripts/db-backup.sh
#    Kurulum: scripts/provision-offsite-backup.sh (bir kez, AWS admin) →
#             scripts/enable-offsite-backup.sh   (instance'ta, IAM role eklenince)
#
#    OFF-SITE HATASI = İŞ HATASI (exit != 0). İlk sürümde yalnız "UYARI" basıyordu;
#    bu, DR-002'nin iki denetim boyunca (v3→v4) fark edilmeden AÇIK kalmasını sağlayan
#    sessizlik sınıfının ta kendisi. Artık systemd OnFailure alarmı tetiklenir
#    (error_logs CRITICAL + e-posta). YEREL yedek yine de tamamlanır ve KORUNUR —
#    önce her şey diske yazılır, off-site en sonda denenir ve yalnız çıkış kodunu etkiler.
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
#   SPRENSES_DB_NAME         (varsayılan sprenses — testler sprenses_test kullanır)
#   SPRENSES_BACKUP_STATE    (varsayılan /var/backups/sprenses-backup-state.json)
set -euo pipefail

# shellcheck source=scripts/_offsite-lib.sh
. "$(dirname "$(readlink -f "$0")")/_offsite-lib.sh"

# Yedekler finans + KVKK kapsamı veri içerir → dünya-okunur OLMAMALI (denetim DR-002).
umask 077

ENV_FILE="${SPRENSES_ENV_FILE:-/home/ec2-user/otel/backend/.env}"
BACKUP_DIR="${SPRENSES_BACKUP_DIR:-/var/backups/sprenses-db}"
UPLOADS_BACKUP_DIR="${SPRENSES_UPLOADS_DIR:-/var/backups/sprenses-uploads}"
UPLOADS_SRC="${SPRENSES_UPLOADS_SRC:-/home/ec2-user/otel/backend/uploads}"
KEEP="${SPRENSES_BACKUP_KEEP:-30}"
UPLOADS_KEEP="${SPRENSES_UPLOADS_KEEP:-30}"
MIN_FREE_MB="${SPRENSES_MIN_FREE_MB:-2000}"
# Durum dosyası yedek dizininin İÇİNDE: /var/backups kökü root'a ait (0755) ve
# yedek işi ec2-user olarak koşuyor → köke yazamaz. Rotasyon glob'u `sprenses-*.dump`
# olduğundan bu .json asla silinmez.
STATE_FILE="${SPRENSES_BACKUP_STATE:-${SPRENSES_BACKUP_DIR:-/var/backups/sprenses-db}/backup-state.json}"
DB_HOST="127.0.0.1"
DB_USER="sprenses"
DB_NAME="${SPRENSES_DB_NAME:-sprenses}"

# ─── Durum dosyası ───────────────────────────────────────────────────────────
# Uygulama (Sistem ▸ Yedekleme) ve eşik kontrolü (health-thresholds.py) yedeğin
# GERÇEKTEN çalışıp çalışmadığını buradan okur. journald'a bakmak kimsenin işi
# değil; off-site'ın kapalı/bozuk olması EKRANDA görünmeli.
DB_OK=false;      DB_FILE="";   DB_BYTES=0
UPLOADS_OK=false; UPLOADS_SNAP=""; UPLOADS_FILES=0
OFFSITE_OK=false; OFFSITE_ERR=""
OFFSITE_TARGET="${SPRENSES_BACKUP_S3:-}"

# SON BAŞARILI off-site zamanı koşumlar arası TAŞINIR. Yalnız "bu koşum başarılı mı"
# saklansaydı, üst üste başarısız koşumlarda "en son ne zaman gerçekten off-site'a
# çıktık" bilgisi kaybolurdu — DR'da cevaplanması gereken ilk soru odur.
# `|| true` ŞART: ilk koşumda durum dosyası yoktur, sed 2 döner ve `set -e` + `pipefail`
# altında script daha DB'ye dokunmadan sessizce ölürdü (bu tuzağa bir kez düşüldü).
OFFSITE_LAST_OK="$(sed -n 's/.*"last_ok": *"\([^"]*\)".*/\1/p' "$STATE_FILE" 2>/dev/null | head -1 || true)"

write_state() {
    local tmp="${STATE_FILE}.tmp"
    mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
    # Hata metni JSON'u bozmasın: satır sonu → boşluk, çift tırnak → tek tırnak
    OFFSITE_ERR="$(printf '%s' "$OFFSITE_ERR" | tr '\n\r\t' '   ' | tr '"' "'" | cut -c1-400)"
    local now; now="$(date --iso-8601=seconds)"
    [ "$OFFSITE_OK" = "true" ] && OFFSITE_LAST_OK="$now"
    cat >"$tmp" <<EOF
{
  "ts": "$now",
  "db": {"ok": $DB_OK, "file": "$DB_FILE", "bytes": $DB_BYTES},
  "uploads": {"ok": $UPLOADS_OK, "snapshot": "$UPLOADS_SNAP", "files": $UPLOADS_FILES},
  "offsite": {"configured": $([ -n "$OFFSITE_TARGET" ] && echo true || echo false),
              "ok": $OFFSITE_OK,
              "target": "$OFFSITE_TARGET",
              "last_ok": "$OFFSITE_LAST_OK",
              "error": "$OFFSITE_ERR"}
}
EOF
    mv "$tmp" "$STATE_FILE" && chmod 644 "$STATE_FILE"
}
# Hangi yoldan çıkarsak çıkalım durum yazılsın (disk bekçisi erken exit dahil).
trap write_state EXIT

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

DB_OK=true
DB_FILE="$OUT"
DB_BYTES="$(stat -c%s "$OUT")"

echo "DB yedeği OK: $OUT ($(du -h "$OUT" | cut -f1)) — toplam $(ls -1 "$BACKUP_DIR"/sprenses-*.dump 2>/dev/null | wc -l) yedek"

# ─── 2) Yüklenen dosyalar (uploads/) ─────────────────────────────────────────
# DB geri yüklense bile bu dosyalar olmadan her file_url dangling kalır: banka ekstreleri,
# cari Excel'leri, çek/rezervasyon/kontrat PDF'leri = geri getirilemez mali belge (DR-001).
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
        UPLOADS_OK=true

        # Bütünlük: kaynak ile snapshot dosya sayısı eşleşmeli
        SRC_N="$(find "$UPLOADS_SRC" -type f | wc -l)"
        SNAP_N="$(find "$SNAP" -type f | wc -l)"
        UPLOADS_FILES="$SNAP_N"
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

# ─── 3) Off-site (S3) — DR-002 ───────────────────────────────────────────────
# Buraya gelindiğinde YEREL yedek tamamdır ve bundan sonrası onu ASLA silmez/bozmaz.
# Off-site başarısızsa exit != 0 → systemd OnFailure alarmı (sessiz kalmaz).
if [ -z "$OFFSITE_TARGET" ]; then
    OFFSITE_ERR="yapılandırılmamış (SPRENSES_BACKUP_S3 boş)"
    echo "NOT: off-site (S3) yapılandırılmamış — yedekler yalnız BU diskte (denetim DR-002 AÇIK)."
    echo "     Kurulum: scripts/provision-offsite-backup.sh → scripts/enable-offsite-backup.sh"
    exit 0
fi

OFFSITE_FAIL=0
DB_KEY="${OFFSITE_TARGET%/}/db/sprenses-${TS}.dump"

if aws s3 cp "$OUT" "$DB_KEY" --sse AES256; then
    echo "off-site DB OK: $DB_KEY"
else
    OFFSITE_ERR="DB yüklenemedi: $DB_KEY"
    echo "HATA: S3 DB yükleme başarısız — $DB_KEY (yerel yedek korundu)" >&2
    OFFSITE_FAIL=1
fi

# uploads: TAM MİRROR (`aws s3 sync`), günlük tar.gz DEĞİL.
#   · tar.gz yolu her gün 285 MB'ın TAMAMINI yüklerdi (ayda ~8,5 GB depo + transfer);
#     sync yalnız DEĞİŞENİ yükler → ilk koşumdan sonra günlük birkaç MB.
#   · `--delete` BİLEREK YOK: kaynakta yanlışlıkla/kötü niyetle silinen dosya off-site
#     kopyadan da silinmesin (ransomware/yanlış rm senaryosu). Bucket versioning
#     üzerine yazmalara karşı ikinci katman.
if [ -n "$UPLOADS_SNAP" ]; then
    if aws s3 sync "$UPLOADS_SNAP/" "${OFFSITE_TARGET%/}/uploads/" --sse AES256 --only-show-errors; then
        echo "off-site uploads OK: ${OFFSITE_TARGET%/}/uploads/ ($UPLOADS_FILES dosya aynalandı)"
    else
        OFFSITE_ERR="${OFFSITE_ERR:+$OFFSITE_ERR; }uploads senkronu başarısız"
        echo "HATA: uploads off-site senkronu başarısız" >&2
        OFFSITE_FAIL=1
    fi
fi

if [ "$OFFSITE_FAIL" -eq 0 ]; then
    OFFSITE_OK=true
    OFFSITE_ERR=""
else
    exit 1   # trap write_state çalışır → durum dosyasına hata düşer, OnFailure alarmı gider
fi
