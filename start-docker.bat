@echo off
setlocal EnableDelayedExpansion
title Schedula — Docker Launcher
color 0A

:: ════════════════════════════════════════════════════════════════
::  SCHEDULA  —  One-Click Docker Launcher  (v2.8)
::  Double-click this file to build & start Schedula in Docker.
::  Requires: Docker Desktop (https://www.docker.com/products/docker-desktop)
:: ════════════════════════════════════════════════════════════════

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║   SCHEDULA — AI Timetable Scheduler  (Docker Edition)   ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

:: ── Locate project directory (same folder as this .bat) ─────────
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

:: ── Configurable port (change if 5000 is taken on your machine) ──
set "PORT=5000"
set "CONTAINER=schedula_app"
set "IMAGE=schedula:latest"
set "URL=http://localhost:%PORT%"

:: ════════════════════════════════════════════════════════════════
:: STEP 1 — Check Docker is installed and running
:: ════════════════════════════════════════════════════════════════
echo  [1/5] Checking Docker...

where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Docker is not installed or not in PATH.
    echo          Download Docker Desktop from:
    echo          https://www.docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Docker Desktop is not running.
    echo          Please start Docker Desktop and try again.
    echo.
    echo  Attempting to start Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe" 2>nul
    start "" "%LOCALAPPDATA%\Docker\Docker Desktop.exe" 2>nul
    echo  Waiting 20 seconds for Docker to start...
    timeout /t 20 /nobreak >nul
    docker info >nul 2>&1
    if !errorlevel! neq 0 (
        echo  [ERROR] Docker still not ready. Please start it manually.
        pause
        exit /b 1
    )
)
echo  [OK]  Docker is running.

:: ════════════════════════════════════════════════════════════════
:: STEP 2 — Stop & remove old container if running
:: ════════════════════════════════════════════════════════════════
echo  [2/5] Checking for existing container...

docker ps -a --filter "name=%CONTAINER%" --format "{{.Names}}" | findstr /i "%CONTAINER%" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [INFO] Stopping and removing old container ^(%CONTAINER%^)...
    docker compose down --remove-orphans >nul 2>&1
    docker stop %CONTAINER% >nul 2>&1
    docker rm   %CONTAINER% >nul 2>&1
    echo  [OK]  Old container removed.
) else (
    echo  [OK]  No existing container found.
)

:: ════════════════════════════════════════════════════════════════
:: STEP 3 — Build the image (uses cache for fast rebuilds)
:: ════════════════════════════════════════════════════════════════
echo  [3/5] Building Schedula Docker image...
echo         (First build may take 2-3 minutes; subsequent builds are fast)
echo.

docker compose build --pull
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Docker build failed. Check output above for details.
    pause
    exit /b 1
)
echo.
echo  [OK]  Image built successfully.

:: ════════════════════════════════════════════════════════════════
:: STEP 4 — Start the container
:: ════════════════════════════════════════════════════════════════
echo  [4/5] Starting Schedula container on port %PORT%...

docker compose up -d
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Failed to start container. Check output above.
    pause
    exit /b 1
)

:: Wait for health check to pass (up to 30 seconds)
echo  [INFO] Waiting for server to become ready...
set /a TRIES=0
:WAIT_LOOP
set /a TRIES+=1
timeout /t 2 /nobreak >nul
docker inspect --format="{{.State.Health.Status}}" %CONTAINER% 2>nul | findstr /i "healthy" >nul 2>&1
if %errorlevel% equ 0 goto :READY
:: Fallback: try HTTP directly
powershell -Command "try { $null = Invoke-WebRequest -Uri '%URL%/api/timetable' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 goto :READY
if %TRIES% lss 15 goto :WAIT_LOOP

:READY
echo  [OK]  Schedula is ready!

:: ════════════════════════════════════════════════════════════════
:: STEP 5 — Open browser
:: ════════════════════════════════════════════════════════════════
echo  [5/5] Opening browser at %URL% ...
start "" "%URL%"

:: ════════════════════════════════════════════════════════════════
:: Done — show management tips
:: ════════════════════════════════════════════════════════════════
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  ✅  Schedula is running!                               ║
echo  ║                                                          ║
echo  ║  URL   : %URL%                              ║
echo  ║  Admin : username=admin  password=admin123               ║
echo  ║  Data  : stored in Docker volume "schedula_data"         ║
echo  ║                                                          ║
echo  ║  Useful commands:                                        ║
echo  ║    View logs  :  docker compose logs -f                  ║
echo  ║    Stop       :  docker compose down                     ║
echo  ║    Restart    :  docker compose restart                  ║
echo  ║    Shell into :  docker exec -it schedula_app bash       ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

endlocal
pause
