@echo off
setlocal
cd /d "%~dp0"
set "PORTS=8030 8130"
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "try { $r = Get-Content -Raw -LiteralPath 'api\data\runtime.json' | ConvertFrom-Json; @($r.api_port, $r.web_port) | Where-Object { $_ -gt 0 } } catch { }"`) do call set "PORTS=%%PORTS%% %%v"
for %%p in (%PORTS%) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr LISTENING') do (
    echo [HaoYuan] Stopping PID %%a ^(port %%p^)
    taskkill /F /PID %%a >nul 2>&1
  )
)
echo [HaoYuan] Stopped.
