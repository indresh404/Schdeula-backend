@echo off
title Schedula - Stop Docker
color 0C

echo.
echo  =================================================================
echo     SCHEDULA - Stopping Docker Container
echo  =================================================================
echo.

cd /d "%~dp0"
docker compose down

if %ERRORLEVEL% equ 0 (
    echo.
    echo  [OK]  Schedula container stopped.
    echo        All timetable, faculty, and settings are preserved in ./data.
) else (
    echo.
    echo  [INFO] docker compose down completed (container may already be stopped).
)

echo.
pause
