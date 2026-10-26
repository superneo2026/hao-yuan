@echo off
setlocal
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8030" ^| findstr LISTENING') do (
  echo [HaoYuan] Stopping PID %%a
  taskkill /F /PID %%a >nul 2>&1
)
echo [HaoYuan] Stopped.
