@echo off
REM Creates Desktop and Start Menu shortcuts for YouDownloader.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_shortcut.ps1"
pause
