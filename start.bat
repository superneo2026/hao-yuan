@echo off
setlocal
cd /d "%~dp0"

call "%~dp0stop.bat" >nul 2>&1

set "PIP_ARGS="
if not "%HAOYUAN_PIP_INDEX_URL%"=="" set "PIP_ARGS=--index-url %HAOYUAN_PIP_INDEX_URL%"

if not exist "api\env1\Scripts\python.exe" (
  echo [HaoYuan] Creating Python virtual environment...
  python -m venv api\env1
  api\env1\Scripts\python.exe -m pip install --upgrade pip %PIP_ARGS%
  api\env1\Scripts\python.exe -m pip install %PIP_ARGS% -r api\requirements.txt
)

set "PYTHONPATH=%CD%\api"
api\env1\Scripts\python.exe -c "from configs.secrets import ensure_config_file; print('[HaoYuan] Global config:', ensure_config_file()[0])"
set "PYTHONPATH="

if not exist "web\dist\index.html" goto build_web
if exist "web\node_modules" goto build_web
echo [HaoYuan] Using prebuilt frontend ^(web\dist^).
goto start_api

:build_web
echo [HaoYuan] Preparing frontend ^(install if needed, then build^)...
set "NPM_ARGS=--no-audit --no-fund"
if not "%HAOYUAN_NPM_REGISTRY%"=="" set "NPM_ARGS=%NPM_ARGS% --registry=%HAOYUAN_NPM_REGISTRY%"
if exist "web\node_modules" goto build_frontend
pushd web
call npm install %NPM_ARGS%
if errorlevel 1 (
  popd
  echo [HaoYuan] npm install failed. Configure an accessible registry, e.g.:
  echo     set HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/
  exit /b 1
)
popd

:build_frontend
echo [HaoYuan] Building frontend...
pushd web
call npm run build
if errorlevel 1 (
  popd
  exit /b 1
)
popd

:start_api
echo [HaoYuan] Starting API on port 8030 (auto +1 if busy)...
if exist "api\data\runtime.json" del /q "api\data\runtime.json" >nul 2>&1
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=$null; for($i=0;$i -lt 120 -and -not $port;$i++){ Start-Sleep -Milliseconds 500; try{ if(Test-Path -LiteralPath 'api\data\runtime.json'){ $r=Get-Content -Raw -LiteralPath 'api\data\runtime.json' -ErrorAction Stop | ConvertFrom-Json; if($r.api_port){ $port=[int]$r.api_port } } }catch{}}; Start-Process ('http://127.0.0.1:' + $(if($port){$port}else{8030}))"
cd api
..\api\env1\Scripts\python.exe main.py
