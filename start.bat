@echo off
rem med-roster — МедГрафик: Поликлиника (Windows, от Windows 7)
cd /d "%~dp0"

echo ==========================================
echo   med-roster - MedGrafik: Poliklinika
echo   Server: http://127.0.0.1:25625
echo ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.8+.
    pause
    exit /b 1
)

rem Проверка: не запущен ли уже сервис на порту 25625.
netstat -aon | findstr ":25625 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [ПРЕДУПРЕЖДЕНИЕ] Сервис уже запущен на порту 25625.
    echo Остановите его: запустите stop.bat или нажмите
    echo "Выключить сервис" в окне программы, затем повторите запуск.
    echo.
    pause
    exit /b 1
)

rem open the browser after a short delay (server needs a moment to start)
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:25625"

python -m uvicorn app.main:app --host 127.0.0.1 --port 25625
pause
