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
) else (
  api\env1\Scripts\python.exe -c "import fastapi, uvicorn, aiosqlite" >nul 2>&1
  if errorlevel 1 (
    echo [HaoYuan] Python dependencies are incomplete; repairing them...
    api\env1\Scripts\python.exe -m pip install %PIP_ARGS% -r api\requirements.txt
  )
)

set "PYTHONPATH=%CD%\api"
api\env1\Scripts\python.exe -c "from configs.secrets import ensure_config_file; print('[HaoYuan] Global config:', ensure_config_file()[0])"
set "PYTHONPATH="

if exist "web\dist\index.html" if not exist "web\node_modules" goto use_prebuilt
goto ensure_web_deps

:use_prebuilt
echo [HaoYuan] Using prebuilt frontend ^(web\dist^).
goto start_api

:ensure_web_deps
set "NPM_ARGS=--no-audit --no-fund --prefer-offline --fetch-retries=2 --fetch-retry-mintimeout=2000 --fetch-retry-maxtimeout=10000 --fetch-timeout=30000"
if not "%HAOYUAN_NPM_REGISTRY%"=="" set "NPM_ARGS=%NPM_ARGS% --registry=%HAOYUAN_NPM_REGISTRY%"
if not exist "web\node_modules\vite\package.json" goto repair_web_deps
if not exist "web\node_modules\vue\package.json" goto repair_web_deps
if not exist "web\node_modules\@vitejs\plugin-vue\package.json" goto repair_web_deps
goto build_frontend

:repair_web_deps
if exist "web\dist\index.html" (
  echo [HaoYuan] Frontend dependencies are incomplete; using the prebuilt frontend in web\dist.
  goto use_existing_dist
)
if exist "web\node_modules" (
  echo [HaoYuan] Detected incomplete frontend dependencies, cleaning them automatically...
  rmdir /s /q "web\node_modules"
)
set "NPM_RETRY=0"

:install_web_deps
echo [HaoYuan] Installing frontend dependencies...
pushd web
call npm install %NPM_ARGS%
if not errorlevel 1 goto install_web_deps_ok
echo [HaoYuan] npm install failed; retrying without package-lock.json...
if exist "node_modules" rmdir /s /q "node_modules"
call npm install %NPM_ARGS% --no-package-lock
if not errorlevel 1 goto install_web_deps_ok
popd
echo [HaoYuan] npm install failed. Configure an accessible registry, e.g.:
echo     set HAOYUAN_NPM_REGISTRY=https://registry.npmjs.org
if exist "web\dist\index.html" goto use_existing_dist
exit /b 1

:install_web_deps_ok
popd
if exist "web\node_modules\vite\package.json" goto build_frontend
if "%NPM_RETRY%"=="1" goto deps_still_broken
set "NPM_RETRY=1"
if exist "web\node_modules" rmdir /s /q "web\node_modules"
goto install_web_deps

:deps_still_broken
if exist "web\dist\index.html" goto use_existing_dist
exit /b 1

:build_frontend
echo [HaoYuan] Building frontend...
pushd web
call npm run build
if errorlevel 1 (
  popd
  if exist "web\dist\index.html" goto use_existing_dist
  exit /b 1
)
popd
goto start_api

:use_existing_dist
echo [HaoYuan] Using the existing web\dist build.
goto start_api

:start_api
echo [HaoYuan] Starting API on port 8030 (auto +1 if busy)...
if exist "api\data\runtime.json" del /q "api\data\runtime.json" >nul 2>&1
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=$null; for($i=0;$i -lt 120 -and -not $port;$i++){ Start-Sleep -Milliseconds 500; try{ if(Test-Path -LiteralPath 'api\data\runtime.json'){ $r=Get-Content -Raw -LiteralPath 'api\data\runtime.json' -ErrorAction Stop | ConvertFrom-Json; if($r.api_port){ $port=[int]$r.api_port } } }catch{}}; Start-Process ('http://127.0.0.1:' + $(if($port){$port}else{8030}))"
cd api
..\api\env1\Scripts\python.exe main.py
