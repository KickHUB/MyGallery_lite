@echo off
setlocal

pushd "%~dp0" || exit /b 1
set "VENV_DIR=%~dp0venv"
set "VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_PYTHON%" goto :venv_ready

echo [INFO] venv not found. Creating venv...
py -3 -m venv venv
if errorlevel 1 python -m venv venv

if not exist "%VENV_PYTHON%" goto :venv_failed

"%VENV_PYTHON%" -m pip install -U pip setuptools wheel packaging
goto :venv_ready

:venv_failed
echo [ERROR] Failed to create venv. Check python/py installation and path.
popd
endlocal
pause
exit /b 1

:venv_ready
set "VIRTUAL_ENV=%VENV_DIR%"
set "PATH=%VENV_DIR%\Scripts;%PATH%"
set "PYTHONUTF8=1"

if exist "%VENV_ACTIVATE%" call "%VENV_ACTIVATE%"
"%VENV_PYTHON%" core\app\run_app.py --repair

popd
endlocal
pause
