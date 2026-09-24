@echo off
setlocal
chcp 65001 >nul
if exist "%~dp0_internal\packaging\install.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0_internal\packaging\install.ps1" %*
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\install.ps1" %*
)
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
