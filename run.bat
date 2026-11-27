@echo off
setlocal
title Schedula - Timetable Scheduling System
cd /d "%~dp0"

echo =====================================================================
echo           Schedula - Multi-Year Timetable Scheduling System
echo =====================================================================
echo.

:: 1. Check if virtual environment exists
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not detected. Checking for system Python...
    where python >nul 2>nul
    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] Python is not installed or not in your system PATH.
        echo Please install Python 3.10+ from https://www.python.org/
        echo Make sure to check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
    echo [INFO] Creating Python virtual environment (venv)...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Installing required dependencies from requirements.txt...
    "venv\Scripts\pip.exe" install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo.
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment setup complete!
    echo.
)

:: 2. Launch browser automatically in the background
echo [INFO] Opening default browser at http://127.0.0.1:5000 ...
start "" cmd /c "ping 127.0.0.1 -n 3 >nul & start http://127.0.0.1:5000"

:: 3. Run the Schedula server
echo [INFO] Starting Schedula application server...
echo.
echo =====================================================================
echo   Local URL:    http://127.0.0.1:5000
echo   Admin Login:  admin / admin123
echo   Stop Server:  Press Ctrl + C in this window
echo =====================================================================
echo.

"venv\Scripts\python.exe" app.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Application exited with error code %ERRORLEVEL%.
    pause
)
