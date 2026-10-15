@echo off
rem Starts Atlas on Google Cloud Shell and makes it available at http://127.0.0.1:3000.
rem Keep this window open while you use Atlas; close it (or press Ctrl+C) to stop.
title Atlas - keep this window open
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-in-cloud-shell.ps1" %*
echo.
echo Atlas has stopped. Press any key to close this window.
pause > nul
