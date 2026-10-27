#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORTS="8030 8130"
if [ -f api/data/runtime.json ]; then
  EXTRA="$(python3 -c "import json;r=json.load(open('api/data/runtime.json'));print(' '.join(str(v) for v in (r.get('api_port'), r.get('web_port')) if v))" 2>/dev/null || true)"
  PORTS="$PORTS $EXTRA"
fi

if command -v lsof >/dev/null 2>&1; then
  for PORT in $PORTS; do
    PIDS="$(lsof -ti tcp:"$PORT" || true)"
    if [ -n "$PIDS" ]; then
      echo "[HaoYuan] Stopping port $PORT (PID $PIDS)"
      kill -9 $PIDS || true
    fi
  done
fi
echo "[HaoYuan] Stopped."
