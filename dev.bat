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

powershell -NoProfile -Command "$f='api\data\runtime.json'; try{ $d=@{}; (Get-Content -Raw -LiteralPath $f | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $d[$_.Name]=$_.Value }; $d.Remove('api_port'); $d.Remove('web_port'); if($d.Count){ $d | ConvertTo-Json | Set-Content -LiteralPath $f } elseif (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f } }catch{}"

start "HaoYuan API" cmd /k "cd /d %~dp0api && ..\api\env1\Scripts\python.exe main.py"

set "APIPORT="
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "$p=$null; for($i=0;$i -lt 90 -and -not $p;$i++){ Start-Sleep -Milliseconds 500; try{ $p=[int](Get-Content -Raw -LiteralPath 'api\data\runtime.json' | ConvertFrom-Json).api_port }catch{} }; if($p){$p}else{8030}"`) do set "APIPORT=%%v"
echo [HaoYuan] API port: %APIPORT%

cd web
set "HAOYUAN_API_PORT=%APIPORT%"
call npm run dev
