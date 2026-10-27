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

echo "[HaoYuan] Starting API on port 8030 (auto +1 if busy)..."
(
  PORT=""
  for _ in $(seq 1 120); do
    if [ -f api/data/runtime.json ]; then
      PORT="$(python3 -c "import json;print(json.load(open('api/data/runtime.json')).get('api_port') or '')" 2>/dev/null || true)"
      [ -n "$PORT" ] && break
    fi
    sleep 0.5
  done
  PORT="${PORT:-8030}"
  echo "[HaoYuan] API ready at http://127.0.0.1:$PORT"
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:$PORT" || true; fi
) &
cd api
exec ../api/env1/bin/python main.py
