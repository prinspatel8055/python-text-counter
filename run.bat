@echo off
title 3D Text Counter ^& Deep Analytics
echo ============================================================
echo    3D TEXT COUNTER  -  starting up
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found on your PATH.
  echo Install Python 3.9+ from https://python.org and tick "Add to PATH".
  pause
  exit /b 1
)

echo Checking dependencies...
python -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Installing required packages ^(one time only^)...
  python -m pip install -r requirements.txt
)

echo.
echo Launching server...
python app.py
pause
