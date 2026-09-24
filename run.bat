@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m server.tray %*
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
