@echo off
title Video Downloader - Server Running
cd /d "%~dp0"

echo ==========================================
echo   Starting website server...
echo   Please wait, browser will open soon...
echo ==========================================

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python is not installed.
    echo Download: https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

python -c "import yt_dlp, flask" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Installing packages, first time only...
    pip install yt-dlp flask
    if errorlevel 1 (
        echo.
        echo ERROR: Could not install packages.
        pause
        exit /b 1
    )
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>nul

echo.
echo Server is starting... browser will open automatically.
echo Close this window to stop the website.
echo ==========================================
echo.

python "%~dp0local_server.py"

echo.
echo Server stopped.
pause
