@echo off
chcp 65001 >nul
schtasks /Delete /F /TN "HaneulAdMonitor"
echo 광고 감시 예약을 해제했습니다.
pause
