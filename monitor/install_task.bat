@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 창 없이 실행되는 pythonw 를 찾는다
set "PYW="
for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%P"
if not defined PYW for /f "delims=" %%P in ('where pyw 2^>nul') do if not defined PYW set "PYW=%%P"
if not defined PYW (
  echo Python 을 찾을 수 없습니다. README 1단계대로 Python 을 설치하고 "Add python.exe to PATH" 를 체크했는지 확인하세요.
  pause
  exit /b 1
)

rem 매일 오전 11시, 오후 2시, 오후 5시 (3시간마다 하루 3번) 실행합니다.
schtasks /Create /F /TN "HaneulAdMonitor" /SC DAILY /ST 11:00 /RI 180 /DU 0006:30 /TR "\"%PYW%\" \"%~dp0ad_monitor.py\""
if errorlevel 1 (
  echo 예약 등록에 실패했습니다. 이 파일을 마우스 오른쪽 버튼 - 관리자 권한으로 실행해 보세요.
) else (
  echo 등록 완료: 매일 11시·14시·17시에 광고 감시가 실행됩니다. 기록은 monitor.log 에 쌓입니다.
  echo 끄려면 uninstall_task.bat 을 실행하세요.
)
pause
