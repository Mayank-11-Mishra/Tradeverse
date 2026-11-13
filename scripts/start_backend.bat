@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run scripts\setup_windows.ps1 first. & pause & exit /b 1)
if not defined ALLOW_LIVE_TRADING set ALLOW_LIVE_TRADING=no
if not defined ALLOW_MOCK_BROKER set ALLOW_MOCK_BROKER=yes
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
