#!/usr/bin/env bash
#
# Test veritabanını sıfırdan kurar (şema + referans veri + admin kullanıcısı).
# CI ile birebir aynı bootstrap'ı yerelde çalıştırır.
#
# Kullanım:
#   TEST_DATABASE_URL=postgresql://sprenses:PASS@127.0.0.1:5432/sprenses_test \
#     ./scripts/setup-test-db.sh
#
# TEST_DATABASE_URL verilmezse backend/.env'deki DATABASE_URL'in db adını
# '_test' ile değiştirerek kullanır.
#
# Önkoşul: '_test' içeren DB önceden oluşturulmuş olmalı (postgres superuser ile):
#   sudo -u postgres psql -c "CREATE DATABASE sprenses_test OWNER sprenses;"
# ve pg_hba.conf'ta bu DB için md5 satırı bulunmalı.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
CI_DIR="$BACKEND_DIR/tests/ci"

# --- DB URL'sini belirle ---
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  BASE_URL="$(grep '^DATABASE_URL' "$BACKEND_DIR/.env" | cut -d= -f2-)"
  TEST_DATABASE_URL="$(echo "$BASE_URL" | sed -E 's#/[^/]+$#/sprenses_test#')"
fi

if [[ "$TEST_DATABASE_URL" != *"_test"* ]]; then
  echo "HATA: TEST_DATABASE_URL '_test' içermeli (prod DB'yi korumak için). Durduruldu." >&2
  exit 1
fi

export PGPASSWORD="$(echo "$TEST_DATABASE_URL" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')"

echo "==> Hedef test DB: $(echo "$TEST_DATABASE_URL" | sed -E 's|:[^:@]+@|:****@|')"

echo "==> 1/5 Şema sıfırlanıyor (public şema yeniden oluşturuluyor)..."
psql "$TEST_DATABASE_URL" -q -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

cd "$BACKEND_DIR"
# shellcheck disable=SC1091
source venv/bin/activate 2>/dev/null || true

echo "==> 2/5 Şema kuruluyor (alembic upgrade head)..."
DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head

echo "==> 3/5 Migration seed verisi temizleniyor (reset_data.sql)..."
psql "$TEST_DATABASE_URL" -q -v ON_ERROR_STOP=1 -f "$CI_DIR/reset_data.sql"

echo "==> 4/5 Referans veri yükleniyor (02_seed.sql)..."
psql "$TEST_DATABASE_URL" -q -v ON_ERROR_STOP=1 -f "$CI_DIR/02_seed.sql"

echo "==> 5/5 Admin kullanıcısı seed ediliyor..."
DATABASE_URL="$TEST_DATABASE_URL" PYTHONPATH=. python tests/ci/seed_admin.py

echo "==> Tamam. Testleri çalıştırmak için:"
echo "    cd backend && DATABASE_URL=\"$TEST_DATABASE_URL\" python -m pytest tests/ -q"
