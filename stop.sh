#!/usr/bin/env bash
set -euo pipefail
PID="$(lsof -ti tcp:8030 || true)"
if [ -n "$PID" ]; then
  echo "[HaoYuan] Stopping PID $PID"
  kill -9 $PID || true
fi
echo "[HaoYuan] Stopped."
