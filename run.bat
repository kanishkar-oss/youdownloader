@echo off
cd /d "%~dp0"

REM Prefer the project-local virtual environment created by setup.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
    goto :eof
)

REM Fall back to the Python launcher, then to whatever 'python' resolves to.
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 main.py
) else (
    python main.py
)
