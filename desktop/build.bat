@echo off
setlocal
cd /d "%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo [HaoYuan] csc.exe not found. .NET Framework 4.x is required.
  exit /b 1
)
"%CSC%" /nologo /target:winexe /optimize+ /codepage:65001 ^
  /win32manifest:app.manifest ^
  /out:..\desktop.exe ^
  /r:System.Windows.Forms.dll /r:System.Drawing.dll ^
  desktop.cs
if errorlevel 1 exit /b 1
echo [HaoYuan] Built ..\desktop.exe
