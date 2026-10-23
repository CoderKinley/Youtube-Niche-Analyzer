@echo off
setlocal
title ViralNiche Radar
cd /d "%~dp0viralniche-radar"
if errorlevel 1 goto missing_project

echo Starting ViralNiche Radar...
echo.

where python >nul 2>&1
if errorlevel 1 goto missing_python

if not exist ".venv\Scripts\python.exe" (
    echo Creating the local Python environment...
    python -m venv .venv
    if errorlevel 1 goto setup_failed
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, dotenv, isodate" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies. The first launch needs an internet connection...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto setup_failed
)

if not exist ".env" copy /y ".env.example" ".env" >nul

echo.
echo Dashboard: http://127.0.0.1:8000
echo Keep this window open. Press Ctrl+C to stop the app.
echo You can open the dashboard before adding a YouTube API key.
echo.
".venv\Scripts\python.exe" launch.py
if errorlevel 1 goto server_failed
exit /b 0

:missing_python
echo Python was not found. Install Python 3.12 or newer with "Add Python to PATH" enabled.
echo Then double-click run.bat again.
pause
exit /b 1

:missing_project
echo The viralniche-radar folder must be beside this launcher.
pause
exit /b 1

:setup_failed
echo.
echo Setup could not finish. The error is shown above.
echo Check your internet connection, then double-click run.bat again.
pause
exit /b 1

:server_failed
echo.
echo The server stopped with an error. The details are shown above.
echo If port 8000 is already in use, open http://127.0.0.1:8000 in your browser.
pause
exit /b 1
