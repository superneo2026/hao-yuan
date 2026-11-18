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

PIP_ARGS=()
if [ -n "${HAOYUAN_PIP_INDEX_URL:-}" ]; then
  PIP_ARGS+=(--index-url "$HAOYUAN_PIP_INDEX_URL")
fi

if [ ! -x "api/env1/bin/python" ]; then
  echo "[HaoYuan] Creating Python virtual environment..."
  python3 -m venv api/env1
  api/env1/bin/python -m pip install --upgrade pip "${PIP_ARGS[@]}"
  api/env1/bin/python -m pip install "${PIP_ARGS[@]}" -r api/requirements.txt
fi

# 首次安装即生成可编辑的模型配置文件（已存在则保留）。
PYTHONPATH=api api/env1/bin/python -c "from configs.secrets import ensure_config_file; print('[HaoYuan] Global config:', ensure_config_file()[0])" || true

# npm 发行包自带 dist 且没有 node_modules：直接使用，避免每次联网。
# 源码部署（没有 dist，或存在 node_modules）则安装依赖并保持前端为最新。
NEED_WEB=1
if [ -f "web/dist/index.html" ] && [ ! -d "web/node_modules" ]; then
  NEED_WEB=0
fi

if [ "$NEED_WEB" = "1" ]; then
  if [ ! -d "web/node_modules" ]; then
    REGISTRY="${HAOYUAN_NPM_REGISTRY:-$(npm config get registry 2>/dev/null || echo default)}"
    echo "[HaoYuan] Installing frontend dependencies (registry: $REGISTRY)..."
    NPM_ARGS=(install --no-audit --no-fund)
    if [ -n "${HAOYUAN_NPM_REGISTRY:-}" ]; then
      NPM_ARGS+=(--registry "$HAOYUAN_NPM_REGISTRY")
    fi
    if ! (cd web && npm "${NPM_ARGS[@]}"); then
      if [ -f "web/dist/index.html" ]; then
        echo "[HaoYuan] npm install failed; continuing with the prebuilt frontend in web/dist."
      else
        echo "[HaoYuan] npm install failed. Configure an accessible registry (e.g. export HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/) and retry." >&2
        exit 1
      fi
    fi
  fi
  if [ -d "web/node_modules" ]; then
    echo "[HaoYuan] Building frontend..."
    (cd web && npm run build) || {
      if [ -f "web/dist/index.html" ]; then
        echo "[HaoYuan] Frontend build failed; serving the existing web/dist build."
      else
        exit 1
      fi
    }
  fi
else
  echo "[HaoYuan] Using prebuilt frontend (web/dist)."
fi

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
