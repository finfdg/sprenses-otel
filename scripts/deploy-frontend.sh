#!/bin/bash
# Sprenses frontend deploy scripti — build + restart
# Kullanım: ./scripts/deploy-frontend.sh
#
# Frontend `node build` ile production modda çalıştığından, kaynak dosya
# değişikliği build alınmadan yansımaz. Bu script süreci otomatikleştirir.
#
# Eşzamanlılık + bellek koruması (2026-07-06): iki Claude oturumu aynı anda
# deploy tetiklediğinde iki paralel Vite build 4 GB RAM'i tüketip makineyi
# kilitliyordu (swap'sız thrash → OOM log'suz donma). flock build'leri
# sıraya alır, NODE_OPTIONS build heap'ini sınırlar. Detay: docs/modules/sunucu.md

set -euo pipefail

FRONTEND_DIR="/home/ec2-user/otel/frontend"
SERVICE="sprenses-frontend.service"
LOCK_FILE="/tmp/sprenses-frontend-deploy.lock"

# Aynı anda tek build: kilit doluysa 10 dk'ya kadar sırada bekle
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "→ Başka bir deploy sürüyor, sıra bekleniyor (en çok 10 dk)..."
    flock -w 600 9 || { echo "✗ Kilit 10 dk içinde alınamadı, vazgeçildi"; exit 1; }
fi

echo "→ Frontend build başlatılıyor..."
cd "$FRONTEND_DIR"
NODE_OPTIONS="--max-old-space-size=1536" npm run build

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
