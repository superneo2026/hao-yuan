#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti tcp:8030 || true)"
  if [ -n "$PIDS" ]; then
    kill -9 $PIDS || true
    sleep 0.5
  fi
fi

if [ ! -x "api/env1/bin/python" ]; then
  echo "[HaoYuan] Creating Python virtual environment..."
  python3 -m venv api/env1
  api/env1/bin/python -m pip install --upgrade pip
  api/env1/bin/python -m pip install -r api/requirements.txt
fi

if [ ! -d "web/node_modules" ]; then
  echo "[HaoYuan] Installing frontend dependencies..."
  (cd web && npm install --no-audit --no-fund)
fi

echo "[HaoYuan] Building frontend..."
(cd web && npm run build)

echo "[HaoYuan] Starting API and web UI on http://127.0.0.1:8030"
cd api
exec ../api/env1/bin/python main.py
