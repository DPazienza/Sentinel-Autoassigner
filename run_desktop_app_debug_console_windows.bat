@echo off
setlocal enabledelayedexpansion

title Sentinel Auto Assign Bot Desktop - Debug Console

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment non trovato.
    echo Esegui prima install_windows.bat
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo ============================================================
echo  Sentinel Auto Assign Bot Desktop - DEBUG CONSOLE
echo ============================================================
echo Questa versione lascia la shell aperta solo per debug/errori.
echo Per uso normale usa:
echo   run_desktop_app_windows.bat
echo ============================================================
echo.

python app.py

pause
exit /b 0
