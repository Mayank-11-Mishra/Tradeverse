@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 first. & pause & exit /b 1)
start "AlgoDesk Backend" cmd /k "scripts\start_backend.bat"
start "AlgoDesk Frontend" cmd /k "scripts\start_frontend.bat"
echo Application: http://127.0.0.1:5173
start "" "http://127.0.0.1:5173"
