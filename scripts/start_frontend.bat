@echo off
setlocal
cd /d "%~dp0..\frontend"
if not exist node_modules (echo Run scripts\setup_windows.ps1 first. & pause & exit /b 1)
call npm run dev
