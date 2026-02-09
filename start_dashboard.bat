@echo off
REM Climate Adaptation Knowledge Base - Dashboard Launcher
REM This script initializes the database and starts the Streamlit dashboard

REM Change to the directory where this batch file is located
cd /d "%~dp0"

echo ========================================
echo  Climate Adaptation Knowledge Base
echo  Dashboard Launcher
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/
    echo.
    pause
    exit /b 1
)

echo [OK] Python found
python --version
echo.

REM Check if Streamlit is installed
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Streamlit is not installed.
    echo Installing required dependencies...
    echo.
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        echo Please run: pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed
    echo.
) else (
    echo [OK] Streamlit is installed
    echo.
)

REM Initialize database and start dashboard
echo Starting dashboard...
echo The dashboard will open automatically in your browser.
echo Press Ctrl+C to stop the server.
echo.
echo ========================================
echo.

REM Run Streamlit (this will auto-open browser and initialize database)
streamlit run dashboard.py

REM If Streamlit exits, check for errors
if errorlevel 1 (
    echo.
    echo [ERROR] Dashboard failed to start.
    echo.
    pause
    exit /b 1
)

