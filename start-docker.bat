@echo off
setlocal EnableDelayedExpansion
title Schedula - Docker One-Click Launcher
color 0A

:: ════════════════════════════════════════════════════════════════
::  SCHEDULA  -  One-Click Docker Launcher  (v2.8)
::  Multi-Year AI Timetable Scheduling System (CMPN)
:: ════════════════════════════════════════════════════════════════

echo.
echo  =================================================================
echo     SCHEDULA - Multi-Year AI Timetable Scheduler (Docker)
echo  =================================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PORT=5000"
set "URL=http://localhost:%PORT%"
set "CONTAINER=schedula_app"

:: ─── Step 1: Check Docker Installation ─────────────────────────
echo  [1/4] Verifying Docker installation...
where docker >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  [ERROR] Docker is not installed or not in system PATH.
    echo          Download Docker Desktop: https://www.docker.com/products/docker-desktop
    echo.
    echo  Would you like to start Schedula in Native Python mode instead? (Y/N)
    set /p FALLBACK="> "
    if /i "!FALLBACK!"=="Y" (
        call start.bat
        exit /b 0
    )
    pause
    exit /b 1
)

:: ─── Step 2: Check Docker Daemon ───────────────────────────────
echo  [2/4] Checking Docker daemon status...
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [INFO]  Docker Desktop is not currently running.
    echo          Attempting to launch Docker Desktop automatically...
    
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe" 2>nul
    start "" "%LOCALAPPDATA%\Docker\Docker Desktop.exe" 2>nul
    
    echo  [WAIT]  Waiting for Docker engine to initialize (up to 30s)...
    set /a DOCKER_WAIT=0
    :CHECK_DAEMON_LOOP
    timeout /t 3 /nobreak >nul
    set /a DOCKER_WAIT+=3
    docker info >nul 2>&1
    if !ERRORLEVEL! equ 0 goto :DAEMON_READY
    if !DOCKER_WAIT! lss 30 goto :CHECK_DAEMON_LOOP
    
    echo.
    echo  [WARN]  Docker daemon took too long to respond.
    echo          Please start Docker Desktop manually, then run this file again.
    echo.
    echo  Would you like to start Schedula in Native Python mode instead? (Y/N)
    set /p FALLBACK="> "
    if /i "!FALLBACK!"=="Y" (
        call start.bat
        exit /b 0
    )
    pause
    exit /b 1
)

:DAEMON_READY
echo  [OK]    Docker daemon is active and responsive.

:: ─── Step 3: Build & Start Container ────────────────────────────
echo  [3/4] Building and starting Schedula container...
echo         (Persistent data mounted at: ./data)
echo.

docker compose up --build -d
if %ERRORLEVEL% neq 0 (
    echo.
    echo  [ERROR] docker compose failed. Check output above.
    pause
    exit /b 1
)

:: ─── Step 4: Healthcheck & Browser Launch ───────────────────────
echo.
echo  [4/4] Waiting for web service to become healthy...
set /a ATTEMPTS=0
:POLL_SERVER
set /a ATTEMPTS+=1
timeout /t 2 /nobreak >nul

powershell -Command "try { $r = Invoke-WebRequest -Uri '%URL%/api/timetable' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% equ 0 goto :SERVER_READY

if %ATTEMPTS% lss 20 (
    <nul set /p=.
    goto :POLL_SERVER
)

:SERVER_READY
echo.
echo  [OK]    Schedula is running and fully initialized!
echo.
echo  =================================================================
echo    Dashboard URL:    %URL%
echo    Admin Login:      admin  /  admin123
echo    Container Name:   %CONTAINER%
echo    Data Storage:     ./data (Mounted volume - persistent)
echo  =================================================================
echo.
echo  Useful Management Commands:
echo    View live logs :  docker compose logs -f
echo    Stop container :  double-click stop-docker.bat
echo    Restart        :  docker compose restart
echo.

:: Automatically open default browser
start "" "%URL%"

pause
