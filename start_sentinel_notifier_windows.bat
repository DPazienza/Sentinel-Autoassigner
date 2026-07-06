@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -like '*app_webview.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] Virtual environment non trovato.
    echo Esegui prima install_sentinel_notifier_windows.bat
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0app\app_webview.py" --ui webview
exit /b 0

