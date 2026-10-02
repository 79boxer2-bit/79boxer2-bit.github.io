@echo off
chcp 65001 >nul
setlocal
title Haneul Copy Report
cd /d "%~dp0"
set "PY="
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set PYTHONIOENCODING=utf-8
"%PY%" ad_monitor.py report > "%TEMP%\haneul_report.txt" 2>&1
powershell -NoProfile -Command "Get-Content -Encoding UTF8 '%TEMP%\haneul_report.txt' | Set-Clipboard"
echo.
echo 진단 보고서를 복사했습니다.
echo 클로드 대화창을 누르고 Ctrl+V 로 붙여 넣은 뒤 보내 주세요.
echo.
pause
