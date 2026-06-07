@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] Virtual environment non trovato.
    echo Esegui prima install_windows.bat
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
exit /b 0
