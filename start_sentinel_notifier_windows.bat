@echo off
setlocal

cd /d "%~dp0"

set "APP_WEBVIEW=%~dp0app\app_webview.py"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

"%POWERSHELL_EXE%" -NoProfile -Command "$target=[IO.Path]::GetFullPath('%APP_WEBVIEW%'); $p=Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -and $_.CommandLine -like ('*' + $target + '*') } | Select-Object -First 1; if($p){ exit 10 } else { exit 0 }" >nul 2>&1
if "%ERRORLEVEL%"=="10" (
    echo [INFO] Sentinel Notifier e' gia' in esecuzione.
    exit /b 0
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] Virtual environment non trovato.
    echo Esegui prima install_sentinel_notifier_windows.bat
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0app\app_webview.py" --ui webview
exit /b 0

