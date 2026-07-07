#!/usr/bin/env bash
# Claude Code'u otel projesinde, MCP sırları process ortamına aktarılmış olarak başlatır.
#
# Neden: .mcp.json içindeki ${POSTGRES_CONNECTION_STRING} / ${GITHUB_PERSONAL_ACCESS_TOKEN}
# yer tutucuları, sunucular başlatılırken GERÇEK ortam değişkenlerinden expand edilir;
# settings.local.json'daki "env" bloğu bu expansion'a ulaşmıyordu → "Missing environment
# variables" uyarısı. Bu script tek kaynağı (settings.local.json) koruyarak o sırları
# process ortamına yükler, sonra claude'u exec eder. Sır git'e girmez.
set -euo pipefail

SETTINGS="/home/ec2-user/otel/.claude/settings.local.json"

if [[ ! -f "$SETTINGS" ]]; then
  echo "HATA: $SETTINGS bulunamadı" >&2
  exit 1
fi

# settings.local.json "env" bloğundaki her anahtarı bu kabuğa export et.
# Değerler '=' içerebilir (bağlantı string'i) → yalnız ilk '=' ayrılır, gerisi değerde kalır.
while IFS='=' read -r key val; do
  [[ -z "$key" ]] && continue
  export "$key=$val"
done < <(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
for k, v in d.get("env", {}).items():
    print(f"{k}={v}")
' "$SETTINGS")

cd /home/ec2-user/otel
exec claude "$@"
