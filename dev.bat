@echo off
setlocal
cd /d "%~dp0"
if not exist "api\env1\Scripts\python.exe" (
  python -m venv api\env1
  api\env1\Scripts\python.exe -m pip install -r api\requirements.txt
)
if not exist "web\node_modules" (
  pushd web
  call npm install --no-audit --no-fund
  popd
)
start "HaoYuan API" cmd /k "cd /d %~dp0api && ..\api\env1\Scripts\python.exe main.py"
cd web
call npm run dev
