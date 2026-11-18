@echo off
REM Verify-then-run wrapper. The actual logic lives in install_deno.ps1 (a
REM committed, readable script) instead of piping remote code straight to iex.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_deno.ps1"
echo.
pause
