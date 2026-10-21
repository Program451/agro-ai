@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AgroAI - Hosting connection
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -u connect-hosting.py
) else (
    python -u connect-hosting.py
)
pause
