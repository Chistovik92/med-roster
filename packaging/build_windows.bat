@echo off
rem ============================================================================
rem  Сборка установщика Windows «МедГрафик: Поликлиника».
rem
rem  Результат: dist\MedGrafik\MedGrafik.exe            (автономная папка)
rem             packaging\MedGrafik-Setup-<VERSION>.exe  (установщик NSIS)
rem
rem  Требования: Python 3.8+ (для Windows 7 — именно 3.8), NSIS (makensis).
rem
rem  Использование:
rem      build_windows.bat            — сборка с python из PATH
rem      build_windows.bat py -3.8    — сборка с конкретным интерпретатором
rem ============================================================================
setlocal
cd /d "%~dp0.."

set "PY=python"
if not "%~1"=="" set "PY=%~1"

where %PY% >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Интерпретатор "%PY%" не найден.
    exit /b 1
)

rem --- версия из app/__init__.py ---
for /f "delims=" %%v in ('%PY% packaging\get_version.py') do set "VERSION=%%v"

echo.
echo ==========================================
echo  Сборка MedGrafik v%VERSION% (Windows)
echo ==========================================
echo.

rem --- виртуальное окружение + зависимости ---
if not exist build\venv (
    echo [1/4] Создание виртуального окружения...
    %PY% -m venv build\venv || exit /b 1
)
call build\venv\Scripts\activate.bat

echo [2/4] Установка зависимостей...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || exit /b 1

echo [3/4] Сборка автономного приложения (PyInstaller)...
python -m PyInstaller --noconfirm --clean packaging\medgrafik.spec || exit /b 1

echo [4/4] Сборка установщика (NSIS)...
where makensis >nul 2>&1
if errorlevel 1 (
    echo [ПРОПУСК] makensis не найден — установщик не собран.
    echo          Установите NSIS и запустите:
    echo          makensis /DVERSION=%VERSION% packaging\installer_windows.nsi
    goto :done
)
cd packaging
makensis /DVERSION=%VERSION% installer_windows.nsi
cd ..

:done
echo.
echo Готово. Артефакты:
echo   dist\MedGrafik\MedGrafik.exe
if exist packaging\MedGrafik-Setup-%VERSION%.exe echo   packaging\MedGrafik-Setup-%VERSION%.exe
endlocal
