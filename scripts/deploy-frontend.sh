#!/bin/bash
# Sprenses frontend deploy scripti — build + restart
# Kullanım: ./scripts/deploy-frontend.sh
#
# Frontend `node build` ile production modda çalıştığından, kaynak dosya
# değişikliği build alınmadan yansımaz. Bu script süreçi otomatikleştirir.

set -euo pipefail

FRONTEND_DIR="/home/ec2-user/otel/frontend"
SERVICE="sprenses-frontend.service"

echo "→ Frontend build başlatılıyor..."
cd "$FRONTEND_DIR"
npm run build

echo
echo "→ Servis yeniden başlatılıyor: $SERVICE"
sudo systemctl restart "$SERVICE"

sleep 2
if sudo systemctl is-active --quiet "$SERVICE"; then
    echo "✓ Frontend deploy tamamlandı, servis aktif"
else
    echo "✗ Servis aktif değil, journalctl ile inceleyin:"
    echo "  sudo journalctl -u $SERVICE -n 50"
    exit 1
fi
