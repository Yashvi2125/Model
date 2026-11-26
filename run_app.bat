@echo off
title MileMates AI - Local Runner
cd /d "%~dp0"

echo ============================================================
echo   MileMates AI - Group Trip Planner
echo ============================================================
echo.

REM 1. Check Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.11 or 3.12 from python.org.
    pause
    exit /b 1
)

REM 2. Check Node.js
where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js is not installed or not in PATH.
    echo Please install Node.js from nodejs.org.
    pause
    exit /b 1
)

REM 3. Setup Virtual Environment
if not exist ".venv" (
    echo [1/4] Creating Python virtual environment...
    python -m venv .venv
)

REM 4. Install backend dependencies
echo [2/4] Checking backend dependencies...
call .venv\Scripts\activate.bat
pip install -q -r requirements-server.txt

REM 5. Setup .env if missing
if not exist ".env" (
    echo [3/4] Creating default .env from .env.example...
    copy .env.example .env >nul
)

REM 6. Install frontend dependencies
echo [4/4] Checking frontend dependencies...
cd frontend
if not exist "node_modules" (
    echo Installing npm packages...
    call npm install
)
cd ..

echo.
echo ============================================================
echo   Starting MileMates AI Services
echo   Backend  : http://localhost:8000
echo   Frontend : http://localhost:5173
echo ============================================================
echo.

start "MileMates Backend" powershell -ExecutionPolicy Bypass -File .\start_dev.ps1
timeout /t 3 /nobreak >nul
start "MileMates Frontend" powershell -ExecutionPolicy Bypass -File .\start_frontend.ps1

echo App is launching! Open http://localhost:5173 in your browser.
timeout /t 5 >nul
start http://localhost:5173
