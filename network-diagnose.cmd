@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\network_diagnose.ps1" %*
set "result=%errorlevel%"
pause
exit /b %result%
