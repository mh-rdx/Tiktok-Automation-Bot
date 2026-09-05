@echo off
title TikTok Bot - 1-Click Session Login
color 0b
echo =================================================================
echo        TIME PASS - TikTok Bot 1-Click Session Login
echo =================================================================
echo.
echo Launching TikTok login browser...
echo.
cd /d "%~dp0"
python sync_session.py
echo.
echo =================================================================
pause
