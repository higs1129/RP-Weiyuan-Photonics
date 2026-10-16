@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap.ps1" -Mode rollback
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
