@echo off
title Schedula - AI Timetable Scheduler
color 0A

echo.
echo  =================================================================
echo   SCHEDULA - Multi-Year AI Timetable Scheduling System (CMPN)
echo  =================================================================
echo.

:: ─── Check Python ────────────────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python is not installed or not in PATH.
    echo          Download from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ─── Locate project directory (same folder as this .bat) ─────────────────────
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: ─── Activate virtual environment if it exists ───────────────────────────────
if exist "venv\Scripts\activate.bat" (
    echo  [INFO]  Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo  [WARN]  No venv found. Using system Python.
    echo          Run: python -m venv venv  ^&  pip install -r requirements.txt
    echo.
)

:: ─── Install / check dependencies ────────────────────────────────────────────
echo  [INFO]  Verifying dependencies...
pip install -r requirements.txt --quiet --no-warn-script-location 2>nul

:: ─── Check if port 5000 is already in use ────────────────────────────────────
netstat -ano | findstr ":5000 " | findstr "LISTEN" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [WARN]  Port 5000 is already in use. Schedula may already be running.
    echo          Opening browser anyway...
    timeout /t 2 /nobreak >nul
    start "" "http://127.0.0.1:5000"
    goto :open_done
)

:: ─── Start Flask server ───────────────────────────────────────────────────────
echo  [INFO]  Starting Schedula server on http://127.0.0.1:5000 ...
echo.
echo  Admin credentials:  username: admin   password: admin123
echo  Press Ctrl+C in this window to stop the server.
echo.
echo  =================================================================
echo.

:: Open browser after a short delay (runs in background)
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"

:: Run Flask (keeps this window alive)
python app.py

:open_done
echo.
echo  [INFO]  Server stopped.
pause
