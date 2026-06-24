@echo off
cd /d "%~dp0"
echo Questo elimina database e log locali.
set /p CONFIRM=Scrivi YES per continuare: 
if /I not "%CONFIRM%"=="YES" exit /b 0
if exist "..\data\bot_state.sqlite3" del /f /q "..\data\bot_state.sqlite3"
if exist "..\logs\app.log" del /f /q "..\logs\app.log"
echo Reset completato.
pause
