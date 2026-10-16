@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\pair_existing_uart.ps1" %*
set "result=%errorlevel%"
pause
exit /b %result%
