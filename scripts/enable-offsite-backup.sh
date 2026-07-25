#!/usr/bin/env bash
# Off-site (S3) yedeği ETKİNLEŞTİR — bucket + IAM role provizyonlandıktan sonra.
#
# KULLANIM: scripts/enable-offsite-backup.sh s3://BUCKET/PREFIX
# Provizyon:  scripts/provision-offsite-backup.sh <bucket> [bölge]   (bir kez, AWS admin)
#
# Ne yapar: erişimi + FARKLI BÖLGE + yazma + OKUMA doğrular → günlük yedek servisine
#   systemd drop-in ile Environment=SPRENSES_BACKUP_S3=<uri> ekler (ana .service'e
#   dokunmaz) → gerçek bir yedek koşturup S3 yüklemesini teyit eder.
#
# OKUMA (GetObject/ListBucket) doğrulaması NEDEN ZORUNLU: yalnız PutObject veren bir
# policy'de yükleme her gün yeşil görünür ama felaket anında geri dönülemez — yedek
# fiilen yoktur. Burada yazıp GERİ OKUYARAK içerik karşılaştırılır.
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
# shellcheck source=scripts/_offsite-lib.sh
. "$SCRIPT_DIR/_offsite-lib.sh"

S3="${1:?Kullanım: $0 s3://bucket/prefix  (ör. s3://sprenses-dr-2026/sprenses)}"
case "$S3" in s3://*) ;; *) echo "HATA: s3://bucket/prefix biçiminde olmalı" >&2; exit 1 ;; esac

echo "1) AWS erişimi kontrol ediliyor..."
if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "HATA: AWS erişimi yok. Önce EC2'ye IAM role ekleyin:" >&2
    echo "      scripts/provision-offsite-backup.sh <bucket> <farklı-bölge>" >&2
    exit 1
fi

echo "2) Farklı bölge kuralı (denetim DR-002 kapanış kriteri)..."
offsite_assert_cross_region "$S3" || exit 1

echo "3) S3 yazma + GERİ OKUMA testi..."
TMP="$(mktemp)"; BACK="$(mktemp)"
trap 'rm -f "$TMP" "$BACK"' EXIT
MARKER="sprenses-offsite-test $(date -u +%FT%TZ) $RANDOM"
printf '%s\n' "$MARKER" >"$TMP"
aws s3 cp "$TMP" "${S3%/}/.offsite-write-test" --sse AES256 >/dev/null \
    || { echo "HATA: S3'e YAZILAMADI (s3:PutObject izni yok mu?)" >&2; exit 1; }
aws s3 cp "${S3%/}/.offsite-write-test" "$BACK" >/dev/null \
    || { echo "HATA: S3'ten OKUNAMADI — yükleme çalışır ama GERİ YÜKLEME ÇALIŞMAZ (s3:GetObject eksik)" >&2; exit 1; }
if [ "$(cat "$BACK")" != "$MARKER" ]; then
    echo "HATA: geri okunan içerik yazılanla aynı değil — bucket/prefix'i kontrol edin" >&2
    exit 1
fi
aws s3 ls "${S3%/}/" >/dev/null \
    || { echo "HATA: LİSTELENEMEDİ (s3:ListBucket eksik) — tatbikat en son yedeği bulamaz" >&2; exit 1; }
aws s3 rm "${S3%/}/.offsite-write-test" >/dev/null 2>&1 || true
echo "   yazma + okuma + listeleme OK: $S3"

echo "4) systemd drop-in ile Environment ekleniyor..."
sudo mkdir -p /etc/systemd/system/sprenses-db-backup.service.d
sudo tee /etc/systemd/system/sprenses-db-backup.service.d/offsite.conf >/dev/null <<EOF
[Service]
Environment=SPRENSES_BACKUP_S3=${S3%/}
EOF
sudo systemctl daemon-reload

echo "5) Gerçek yedek koşusu (S3 yüklemesi dahil)..."
# Artık off-site hatası işi BAŞARISIZ yapar → `systemctl start` çıkış kodu gerçeği söyler.
if sudo systemctl start sprenses-db-backup.service; then
    sudo journalctl -u sprenses-db-backup.service -n 8 --no-pager | grep -iE "off-site|yedek OK|UYARI|HATA" || true
else
    echo "HATA: yedek koşusu başarısız — journalctl -u sprenses-db-backup.service" >&2
    sudo journalctl -u sprenses-db-backup.service -n 20 --no-pager >&2
    exit 1
fi

echo ""
echo "✅ Off-site etkin: ${S3%/} — her gün 03:00 (Istanbul) yerel + S3'e yedeklenir."
echo "   ŞİMDİ TATBİKAT YAPIN (DR-002 kapanış kanıtı):  scripts/db-restore.sh --offsite"
echo "   Devre dışı: sudo rm /etc/systemd/system/sprenses-db-backup.service.d/offsite.conf && sudo systemctl daemon-reload"
