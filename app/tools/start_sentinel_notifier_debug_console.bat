@echo off
setlocal enabledelayedexpansion

title Sentinel Notifier Desktop - Debug Console

cd /d "%~dp0"

if not exist "%~dp0..\..\.venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment non trovato.
    echo Esegui prima install_sentinel_notifier_windows.bat
    pause
    exit /b 1
)

call "%~dp0..\..\.venv\Scripts\activate.bat"

echo ============================================================
echo  Sentinel Notifier Desktop - DEBUG CONSOLE
echo ============================================================
echo Questa versione lascia la shell aperta solo per debug/errori.
echo Per uso normale usa:
echo   start_sentinel_notifier_windows.bat
echo ============================================================
echo.

python ..\app_webview.py --ui webview --debug

pause
exit /b 0

