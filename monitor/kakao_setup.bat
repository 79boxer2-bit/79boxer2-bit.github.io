@echo off
chcp 65001 >nul
setlocal
title Haneul Kakao Setup
cd /d "%~dp0"
set "PY="
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python 을 찾을 수 없습니다. setup.bat 을 먼저 실행하세요.
  pause
  exit /b 1
)
"%PY%" ad_monitor.py kakao-setup
echo.
pause
