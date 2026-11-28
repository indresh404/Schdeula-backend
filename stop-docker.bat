@echo off
title Schedula — Stop Docker
color 0C

echo.
echo  Stopping Schedula Docker container...
echo.

cd /d "%~dp0"
docker compose down

if %errorlevel% equ 0 (
    echo.
    echo  [OK]  Schedula stopped. Your data is safely stored in the
    echo         Docker volume "schedula_data" and will be there next time.
) else (
    echo.
    echo  [WARN] docker compose down returned an error — container may already be stopped.
)

echo.
pause
