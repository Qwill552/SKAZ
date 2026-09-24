@echo off
setlocal
chcp 65001 >nul
cd /d "%TEMP%"
if exist "%~dp0_internal\packaging\uninstall.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0_internal\packaging\uninstall.ps1" -KeepLauncher %*
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\uninstall.ps1" -KeepLauncher %*
)
set "result=%errorlevel%"
pause
if not "%result%"=="0" exit /b %result%
if not exist "%~dp0_internal\packaging\uninstall.ps1" if not exist "%~dp0packaging\uninstall.ps1" goto cleanup
exit /b 0
:cleanup
(goto) 2>nul & del /f /q "%~f0" & rd "%~dp0"
