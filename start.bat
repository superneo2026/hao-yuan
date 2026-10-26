@echo off
setlocal
cd /d "%~dp0"

call "%~dp0stop.bat" >nul 2>&1

if not exist "api\env1\Scripts\python.exe" (
  echo [HaoYuan] Creating Python virtual environment...
  python -m venv api\env1
  api\env1\Scripts\python.exe -m pip install --upgrade pip
  api\env1\Scripts\python.exe -m pip install -r api\requirements.txt
)

if not exist "web\node_modules" (
  echo [HaoYuan] Installing frontend dependencies...
  pushd web
  call npm install --no-audit --no-fund
  popd
)

echo [HaoYuan] Building frontend...
pushd web
call npm run build
popd

echo [HaoYuan] Starting API and web UI on http://127.0.0.1:8030
start "" http://127.0.0.1:8030
cd api
..\api\env1\Scripts\python.exe main.py
