@echo off
title TikTok Automation Bot (Local Daemon)
cd /d "%~dp0"
echo ===================================================
echo   TikTok Automation Daemon (TIME PASS)
echo ===================================================

echo [1/2] Syncing latest code from GitHub...
git pull origin main

echo.
echo [2/2] Launching Bot Orchestrator...
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe bot_orchestrator.py
) else (
    python bot_orchestrator.py
)
pause
