@echo off
setlocal
cd /d "%~dp0"

set CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if not exist "%CHROME_PATH%" set CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe

if not exist "%CHROME_PATH%" (
    echo [ERROR] Google Chrome non trovato.
    pause
    exit /b 1
)

mkdir browser_profiles\chrome_bot_profile >nul 2>nul

start "" "%CHROME_PATH%" ^
  --remote-debugging-port=9222 ^
  --remote-debugging-address=127.0.0.1 ^
  --remote-allow-origins=* ^
  --user-data-dir="%~dp0browser_profiles\chrome_bot_profile" ^
  --no-first-run ^
  --no-default-browser-check ^
  --new-window ^
  https://portal.azure.com/

echo Chrome avviato e collegabile su 127.0.0.1:9222
pause
