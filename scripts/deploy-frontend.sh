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
#
# Build öncesi bellek bekçisi (2026-07-18): swap doygunken (çok sayıda uzun
# ömürlü Claude oturumu swap'ı doldurunca) build ortasında earlyoom SIGTERM
# gönderiyordu. Kullanılabilir RAM + boş swap toplamı build tepe ihtiyacının
# (heap 1536 MB + node/V8 yükü ≈ 1,8 GB) altındaysa build'e hiç başlanmaz.

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

# Bellek bekçisi: kilit alındıktan SONRA kontrol (sırada bekleyen build kendi
# sırası geldiğinde güncel değerlere bakar). earlyoom eşiği RAM %10 VE swap %10
# olduğundan, headroom yetersizse build'in öldürülmesi kaçınılmazdır.
MIN_HEADROOM_MB=2500
mem_avail=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
swap_free=$(awk '/^SwapFree:/{print int($2/1024)}' /proc/meminfo)
headroom=$((mem_avail + swap_free))
if [ "$headroom" -lt "$MIN_HEADROOM_MB" ]; then
    echo "✗ Yetersiz bellek: kullanılabilir RAM ${mem_avail} MB + boş swap ${swap_free} MB = ${headroom} MB (< ${MIN_HEADROOM_MB} MB)"
    echo "  Build başlatılsaydı earlyoom tarafından öldürülecekti (2026-07-18 olayı — docs/modules/sunucu.md)."
    echo "  Öneri: boştaki Claude oturumlarını kapatın; en büyük swap kullanıcıları:"
    for p in /proc/[0-9]*/status; do
        awk '/^Name:/{n=$2} /^VmSwap:/{s=$2} END{if(s>102400) printf "    %s (pid %s): %d MB swap\n", n, pid, s/1024}' pid="$(basename "$(dirname "$p")")" "$p" 2>/dev/null
    done | sort -t: -k2 -rn | head -5
    exit 1
fi

echo "→ Frontend build başlatılıyor (headroom: ${headroom} MB)..."
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
