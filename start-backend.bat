@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" setup.py
    ".venv\Scripts\python.exe" server.py
) else (
    python setup.py
    python server.py
)
if errorlevel 1 pause
