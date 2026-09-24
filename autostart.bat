@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\shortcuts.ps1" -Root "%~dp0." -Action Toggle
pause
