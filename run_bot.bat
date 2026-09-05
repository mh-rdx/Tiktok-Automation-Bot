@echo off
title TikTok Automation Bot (Local Daemon)
cd /d "%~dp0"
echo ===================================================
echo   Starting TikTok Automation Daemon (TIME PASS)
echo ===================================================
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe bot_orchestrator.py
) else (
    python bot_orchestrator.py
)
pause
