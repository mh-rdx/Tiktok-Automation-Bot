@echo off
title TikTok Bot - 1-Click Railway Session Sync
color 0b
echo =================================================================
echo        TIME PASS - TikTok Bot 1-Click Session Synchronizer
echo =================================================================
echo.
echo Connecting to Railway server: https://worker-production-4386.up.railway.app
echo.
cd /d "%~dp0"
python sync_session.py
echo.
echo =================================================================
pause
