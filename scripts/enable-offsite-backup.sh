#!/usr/bin/env bash
# Off-site (S3) DB yedeğini ETKİNLEŞTİR — EC2'ye s3:PutObject IAM role EKLENDİKTEN sonra çalıştır.
#
# KULLANIM: scripts/enable-offsite-backup.sh s3://BUCKET/sprenses-db
#
# Ne yapar: AWS erişimini doğrular → günlük yedek servisine systemd drop-in ile
#   Environment=SPRENSES_BACKUP_S3=<uri> ekler (ana .service dosyasına dokunmaz) →
#   bir test yedeği koşturup S3 yüklemesini doğrular. (Local yedek + rotasyon zaten çalışıyor.)
set -euo pipefail

S3="${1:?Kullanım: $0 s3://bucket/prefix  (ör. s3://sprenses-backups/sprenses-db)}"

echo "1) AWS erişimi kontrol ediliyor..."
if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "HATA: AWS erişimi yok. Önce EC2'ye s3:PutObject izinli IAM role ekle (bkz. docs/modules/yedekleme.md)." >&2
    exit 1
fi

echo "2) S3 yazma testi (deneme nesnesi)..."
TMP="$(mktemp)"; echo "sprenses-offsite-test $(date -u +%FT%TZ)" >"$TMP"
aws s3 cp "$TMP" "${S3%/}/.offsite-write-test" >/dev/null
aws s3 rm "${S3%/}/.offsite-write-test" >/dev/null || true
rm -f "$TMP"
echo "   S3 yazma OK: $S3"

echo "3) systemd drop-in ile Environment ekleniyor..."
sudo mkdir -p /etc/systemd/system/sprenses-db-backup.service.d
sudo tee /etc/systemd/system/sprenses-db-backup.service.d/offsite.conf >/dev/null <<EOF
[Service]
Environment=SPRENSES_BACKUP_S3=${S3%/}
EOF
sudo systemctl daemon-reload

echo "4) Test yedeği (S3 yüklemesi dahil)..."
sudo systemctl start sprenses-db-backup.service
sleep 3
sudo journalctl -u sprenses-db-backup.service -n 6 --no-pager | grep -iE "off-site|yedek OK|UYARI|HATA" || true

echo ""
echo "✅ Off-site etkin: ${S3%/} — her gün 03:00 (Istanbul) yerel + S3'e yedeklenir."
echo "   Devre dışı: sudo rm /etc/systemd/system/sprenses-db-backup.service.d/offsite.conf && sudo systemctl daemon-reload"
