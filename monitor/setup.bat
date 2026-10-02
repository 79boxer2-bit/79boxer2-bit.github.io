@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title Haneul Ad Monitor Setup
set "DEST=C:\HaneulAdMonitor"
set "ZIPURL=https://github.com/79boxer2-bit/79boxer2-bit.github.io/archive/refs/heads/main.zip"

echo ==================================================
echo   하늘공인중개사 네이버 광고 감시 - 자동 설치
echo ==================================================
echo.

rem ---------- 1. Python 찾기 (없으면 설치) ----------
set "PY="
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY (
  echo [1/4] Python 이 없어 설치합니다. 2~3분 걸립니다...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo Python 자동 설치에 실패했습니다.
  echo https://www.python.org/downloads/ 에서 직접 설치한 뒤 이 파일을 다시 실행하세요.
  echo 설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause
  exit /b 1
)
for %%D in ("%PY%") do set "PYW=%%~dpDpythonw.exe"
echo [1/4] Python 확인: %PY%
echo       브라우저 연결 모듈을 설치합니다. 처음에는 1~2분 걸립니다...
"%PY%" -m pip install --quiet --disable-pip-version-check --upgrade playwright
if errorlevel 1 (
  echo 브라우저 연결 모듈 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 실행하세요.
  pause
  exit /b 1
)

rem ---------- 2. 프로그램 내려받기 ----------
echo [2/4] 프로그램을 내려받습니다...
set "TMPZIP=%TEMP%\haneul_monitor.zip"
set "TMPDIR=%TEMP%\haneul_monitor"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing '%ZIPURL%' -OutFile '%TMPZIP%'; if (Test-Path '%TMPDIR%') { Remove-Item -Recurse -Force '%TMPDIR%' }; Expand-Archive -Force '%TMPZIP%' '%TMPDIR%'"
if errorlevel 1 (
  echo 내려받기에 실패했습니다. 인터넷 연결을 확인하세요.
  pause
  exit /b 1
)
if not exist "%DEST%" mkdir "%DEST%"
rem 설정·기록 파일은 덮어쓰지 않고 프로그램 파일만 갱신
for /d %%R in ("%TMPDIR%\*") do (
  copy /Y "%%R\monitor\*.py" "%DEST%\" >nul
  for %%F in ("%%R\monitor\*.bat") do if /i not "%%~nxF"=="setup.bat" copy /Y "%%F" "%DEST%\" >nul
  copy /Y "%%R\monitor\setup.bat" "%DEST%\setup.new" >nul
  copy /Y "%%R\monitor\*.example.*" "%DEST%\" >nul
  copy /Y "%%R\monitor\README.md" "%DEST%\" >nul
)
if not exist "%DEST%\ad_monitor.py" (
  echo 프로그램 파일 복사에 실패했습니다.
  pause
  exit /b 1
)
echo [2/4] 설치 위치: %DEST%

rem ---------- 3. 단지 주소 입력 ----------
rem 예전 목록(단지 번호만 있는 것)은 지도 주소가 들어간 새 목록으로 바꾼다
if exist "%DEST%\complexes.txt" (
  findstr /c:"fin.land.naver.com/map" "%DEST%\complexes.txt" >nul 2>nul
  if errorlevel 1 (
    copy /Y "%DEST%\complexes.txt" "%DEST%\complexes.old.txt" >nul
    copy /Y "%DEST%\complexes.example.txt" "%DEST%\complexes.txt" >nul
    echo [3/4] 단지 목록을 네이버 지도 주소가 들어간 새 목록으로 바꿨습니다. ^(이전 목록: complexes.old.txt^)
  )
)
if not exist "%DEST%\complexes.txt" (
  copy /Y "%DEST%\complexes.example.txt" "%DEST%\complexes.txt" >nul
  echo.
  echo [3/4] 메모장이 열립니다.
  echo       단지 이름 뒤에 한 칸 띄우고, 네이버 부동산 단지 화면의 주소를 붙여 넣으세요.
  echo       예^) 시티프라디움1차 https://new.land.naver.com/complexes/12345
  echo       다 넣었으면 저장^(Ctrl+S^)하고 메모장을 닫으세요.
  echo.
  pause
  start /wait notepad "%DEST%\complexes.txt"
) else (
  echo [3/4] 기존 단지 목록^(complexes.txt^)을 그대로 사용합니다. 고치려면 메모장으로 여세요.
)

rem ---------- 4. 테스트 + 자동 실행 등록 ----------
echo.
echo [4/4] 모든 단지를 테스트합니다. 1~2분 걸립니다...
echo --------------------------------------------------
"%PY%" "%DEST%\ad_monitor.py" test
echo --------------------------------------------------
echo 단지마다 "네이버 단지명"이 맞는지, "우리 매물 N건"이 나오는지 확인하세요.
echo 매물이 0건이면 %DEST%\debug 폴더의 _screen.png 그림을 보내 주세요.
echo 오류가 보이면 이 창을 캡처해서 보내 주세요.
echo.

schtasks /Create /F /TN "HaneulAdMonitor" /SC DAILY /ST 11:00 /RI 180 /DU 0006:30 /TR "\"%PYW%\" \"%DEST%\ad_monitor.py\"" >nul
if errorlevel 1 (
  echo 자동 실행 등록에 실패했습니다. 이 파일을 마우스 오른쪽 - 관리자 권한으로 실행해 보세요.
) else (
  echo 자동 실행 등록 완료: PC가 켜져 있으면 매일 오전 11시, 오후 2시, 오후 5시 하루 3번 감시합니다.
)
echo.
echo 카카오톡 연결이 아직이면 %DEST%\kakao_setup.bat 을 실행하세요. 지금 바로 점검하려면 %DEST%\check_now.bat 을 실행하세요.
echo.
pause
rem 실행 중에 자기 자신을 덮어쓰지 않도록, 마지막 줄 하나로 새 설치 파일로 교체하고 끝낸다
if exist "%DEST%\setup.new" copy /Y "%DEST%\setup.new" "%DEST%\setup.bat" >nul & del "%DEST%\setup.new" & exit /b 0
