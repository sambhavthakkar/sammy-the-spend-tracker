#!/usr/bin/env bash
# Build a data-preserving deploy package for Oracle Free Tier.
# - App code tarball (no .venv, no secrets, no personal_data by default)
# - Separate personal_data tarball (KEEP SAFE — this is user history)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
STAMP="$(date +%F-%H%M)"
OUT="${ORACLE_PACKAGE_DIR:-$HOME/budgetbot-oracle-package}"
mkdir -p "$OUT"

APP_TGZ="$OUT/budgetbot-app-$STAMP.tgz"
DATA_TGZ="$OUT/budgetbot-personal-data-$STAMP.tgz"

echo "Packaging app code → $APP_TGZ"
tar -czf "$APP_TGZ" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='personal_data' \
  --exclude='uploads' \
  --exclude='logs' \
  --exclude='*.db' \
  --exclude='*.db-*' \
  --exclude='.env' \
  -C "$ROOT" \
  src main.py requirements.txt Makefile Dockerfile docker-compose.yml \
  docs deploy scripts .env.example README.md .gitignore

if [[ -d personal_data ]]; then
  echo "Packaging personal_data (preserve users) → $DATA_TGZ"
  tar -czf "$DATA_TGZ" -C "$ROOT" personal_data
else
  echo "WARN: no personal_data/ directory — skipping data package"
fi

echo ""
echo "Done. Files in $OUT:"
ls -lh "$OUT"/*"$STAMP"* 2>/dev/null || ls -lh "$OUT"
echo ""
echo "Next:"
echo "  1) scp $APP_TGZ ubuntu@ORACLE_IP:~/"
echo "  2) scp $DATA_TGZ ubuntu@ORACLE_IP:~/"
echo "  3) scp .env ubuntu@ORACLE_IP:~/budgetbot/.env   # after unpack, chmod 600"
echo "  4) Follow docs/deploy-oracle.md"
