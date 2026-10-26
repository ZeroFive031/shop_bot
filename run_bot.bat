@echo off
rem Double-click to start the bot. Close this window (or press Ctrl+C) to stop it.
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" bot.py
pause
