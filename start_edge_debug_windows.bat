@echo off
setlocal
cd /d "%~dp0"

set EDGE_PATH=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE_PATH%" set EDGE_PATH=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe

if not exist "%EDGE_PATH%" (
    echo [ERROR] Microsoft Edge non trovato.
    pause
    exit /b 1
)

mkdir browser_profiles\edge_bot_profile >nul 2>nul

start "" "%EDGE_PATH%" ^
  --remote-debugging-port=9223 ^
  --remote-debugging-address=127.0.0.1 ^
  --remote-allow-origins=* ^
  --user-data-dir="%~dp0browser_profiles\edge_bot_profile" ^
  --no-first-run ^
  --no-default-browser-check ^
  --new-window ^
  https://portal.azure.com/

echo Edge avviato e collegabile su 127.0.0.1:9223
pause
