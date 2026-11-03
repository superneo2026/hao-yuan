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

echo [HaoYuan] Starting API on port 8030 (auto +1 if busy)...
if exist "api\data\runtime.json" del /q "api\data\runtime.json" >nul 2>&1
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=$null; for($i=0;$i -lt 120 -and -not $port;$i++){ Start-Sleep -Milliseconds 500; try{ if(Test-Path -LiteralPath 'api\data\runtime.json'){ $r=Get-Content -Raw -LiteralPath 'api\data\runtime.json' -ErrorAction Stop | ConvertFrom-Json; if($r.api_port){ $port=[int]$r.api_port } } }catch{}}; Start-Process ('http://127.0.0.1:' + $(if($port){$port}else{8030}))"
cd api
..\api\env1\Scripts\python.exe main.py
