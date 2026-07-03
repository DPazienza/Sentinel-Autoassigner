@echo off
setlocal enabledelayedexpansion

title Sentinel Notifier Desktop - Installer
cd /d "%~dp0"

echo ============================================================
echo  Sentinel Notifier Desktop - Windows Installer
echo ============================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python non trovato nel PATH.
    echo Installa Python 3.10+ e seleziona "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist .venv (
    echo [1/4] Creazione virtual environment...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Creazione virtualenv fallita.
        pause
        exit /b 1
    )
) else (
    echo [OK] Virtual environment gia' presente.
)

echo [2/4] Attivazione virtual environment...
call ".venv\Scripts\activate.bat"

echo [3/4] Installazione dipendenze...
python -m pip install --upgrade pip
pip install -r app\requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Installazione dipendenze fallita.
    pause
    exit /b 1
)

echo [4/4] Installazione componenti Playwright...
python -m playwright install chromium
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Installazione Playwright fallita.
    pause
    exit /b 1
)

echo.
echo INSTALLAZIONE COMPLETATA.
echo Avvia l'app con start_sentinel_notifier_windows.bat
pause
exit /b 0

