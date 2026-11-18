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
elif ! api/env1/bin/python -c "import fastapi, uvicorn, aiosqlite" >/dev/null 2>&1; then
  echo "[HaoYuan] Python dependencies are incomplete; repairing them..."
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

frontend_deps_ready() {
  [ -f "web/node_modules/vite/package.json" ] &&
    [ -f "web/node_modules/vue/package.json" ] &&
    [ -f "web/node_modules/@vitejs/plugin-vue/package.json" ]
}

clean_frontend_deps() {
  echo "[HaoYuan] 检测到不完整的前端依赖（上次安装可能被网络中断），自动清理后重装..."
  rm -rf "web/node_modules"
}

install_frontend_deps() {
  NPM_ARGS=(install --no-audit --no-fund --prefer-offline --fetch-retries=2 --fetch-retry-mintimeout=2000 --fetch-retry-maxtimeout=10000 --fetch-timeout=30000)
  if [ -n "${HAOYUAN_NPM_REGISTRY:-}" ]; then
    NPM_ARGS+=(--registry "$HAOYUAN_NPM_REGISTRY")
  fi
  (cd web && npm "${NPM_ARGS[@]}")
}

if [ "$NEED_WEB" = "1" ]; then
  SKIP_BUILD=0
  if ! frontend_deps_ready; then
    if [ -d "web/node_modules" ]; then
      clean_frontend_deps
    fi
    REGISTRY="${HAOYUAN_NPM_REGISTRY:-$(npm config get registry 2>/dev/null || echo default)}"
    echo "[HaoYuan] Installing frontend dependencies (registry: $REGISTRY)..."
    if ! install_frontend_deps; then
      if [ -f "web/dist/index.html" ]; then
        echo "[HaoYuan] npm install failed; continuing with the prebuilt frontend in web/dist."
        SKIP_BUILD=1
      else
        echo "[HaoYuan] npm install failed. Configure an accessible registry (e.g. export HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/) and retry." >&2
        exit 1
      fi
    elif ! frontend_deps_ready; then
      # 依赖目录残缺（例如磁盘/网络中断）：清理后再做一次完整安装。
      clean_frontend_deps
      if ! install_frontend_deps; then
        if [ -f "web/dist/index.html" ]; then
          echo "[HaoYuan] npm install failed; continuing with the existing web/dist build."
          SKIP_BUILD=1
        else
          exit 1
        fi
      fi
    fi
  fi

  if [ "$SKIP_BUILD" = "0" ] && frontend_deps_ready; then
    echo "[HaoYuan] Building frontend..."
    (cd web && npm run build) || {
      if [ -f "web/dist/index.html" ]; then
        echo "[HaoYuan] Frontend build failed; serving the existing web/dist build."
      else
        exit 1
      fi
    }
  elif [ -f "web/dist/index.html" ]; then
    echo "[HaoYuan] Using the existing prebuilt frontend (web/dist)."
  else
    exit 1
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
