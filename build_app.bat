@echo off
REM Build a standalone NXOSC_Reborn.exe on Windows.
REM   py -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt
setlocal
cd /d "%~dp0"
if "%PY%"=="" set PY=.venv\Scripts\python.exe
"%PY%" -m pip install --quiet -r requirements.txt -r requirements-dev.txt
"%PY%" -m PyInstaller --noconfirm --clean NXOSC_Reborn.spec
echo.
echo built: dist\NXOSC_Reborn\NXOSC_Reborn.exe
endlocal
