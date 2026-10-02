@echo off
chcp 65001 >nul
setlocal
title Haneul Copy Debug
cd /d "%~dp0"
set "F="
for %%X in ("debug\*_fields.txt") do if not defined F set "F=%%X"
if not defined F (
  echo 분석 파일이 아직 없습니다. setup.bat 을 먼저 끝까지 실행한 뒤 다시 실행하세요.
  pause
  exit /b 1
)
powershell -NoProfile -Command "Get-Content -Encoding UTF8 '%F%' -TotalCount 400 | Set-Clipboard"
echo.
echo 복사했습니다.
echo 클로드 대화창을 누르고 Ctrl+V 로 붙여 넣은 뒤 보내 주세요.
echo.
pause
