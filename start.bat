@echo off
rem med-roster — МедГрафик: Поликлиника (Windows, от Windows 7)
cd /d "%~dp0"

echo ==========================================
echo   med-roster - MedGrafik: Poliklinika
echo   Server: http://127.0.0.1:8000
echo ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.8+.
    pause
    exit /b 1
)

rem open the browser after a short delay (server needs a moment to start)
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
