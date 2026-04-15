@echo off
setlocal enabledelayedexpansion
REM =============================================
REM  EthOS Drive Build Script
REM  Builds Windows executable using PyInstaller
REM  Run this .bat from anywhere — it auto-detects the project root.
REM =============================================

REM Navigate to project root (parent of build/)
cd /d "%~dp0\.."
echo Working directory: %CD%

echo.
echo ========================================
echo  EthOS Drive Build
echo ========================================
echo.

REM --- Check Python ---
python --version 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python not found in PATH.
    echo Install Python 3.11+ from https://python.org
    goto :fail
)

REM --- Create venv if missing ---
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create venv.
        goto :fail
    )
)

REM --- Activate venv ---
call venv\Scripts\activate.bat

REM --- Install dependencies ---
echo Installing dependencies...
pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    goto :fail
)

REM --- Install PyInstaller if missing ---
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install --quiet pyinstaller
)

REM --- Clean previous build ---
echo Cleaning previous build...
if exist "dist" rmdir /s /q "dist"
if exist "build" if exist "build\EthOS Drive" rmdir /s /q "build\EthOS Drive"

REM --- Build with PyInstaller ---
echo.
echo Building executable with PyInstaller...
echo.

python -m PyInstaller ^
    --name "EthOS Drive" ^
    --windowed ^
    --onedir ^
    --icon "src\resources\icons\ethos-drive.ico" ^
    --add-data "src\resources\icons;resources\icons" ^
    --hidden-import "PySide6.QtSvg" ^
    --hidden-import "PySide6.QtNetwork" ^
    --hidden-import "engineio.async_drivers.threading" ^
    --hidden-import "socketio" ^
    --hidden-import "httpx" ^
    --hidden-import "xxhash" ^
    --hidden-import "keyring" ^
    --hidden-import "keyring.backends" ^
    --hidden-import "keyring.backends.Windows" ^
    --hidden-import "watchdog" ^
    --hidden-import "watchdog.observers" ^
    --hidden-import "pydantic" ^
    --collect-all "ethos_drive" ^
    --paths "src" ^
    --noconfirm ^
    --clean ^
    "src\ethos_drive\main.py"

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed. See output above.
    goto :fail
)

echo.
echo ========================================
echo  BUILD SUCCESSFUL
echo  Output: dist\EthOS Drive\EthOS Drive.exe
echo ========================================
echo.

REM --- Optional: Inno Setup installer ---
where iscc >nul 2>&1
if errorlevel 1 (
    echo NOTE: Inno Setup not found — skipping installer creation.
    echo   To create a setup .exe:
    echo   1. Install Inno Setup from https://jrsoftware.org/isinfo.php
    echo   2. Run: iscc src\resources\installer\ethos-drive.iss
) else (
    echo Building installer with Inno Setup...
    iscc "src\resources\installer\ethos-drive.iss"
    if errorlevel 1 (
        echo ERROR: Installer build failed.
        goto :fail
    )
    echo Installer: dist\EthOSDriveSetup.exe
)

echo.
goto :end

:fail
echo.
echo Build FAILED.
echo.

:end
pause
