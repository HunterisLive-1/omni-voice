@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Web UI by default. Other args go to setup.bat (e.g. run.bat verify — no second pause)
if "%~1"=="" (
  call "%~dp0setup.bat" run
  set "RC=%ERRORLEVEL%"
  if not "%RC%"=="0" echo Finished with error code %RC%.
  pause
  exit /b %RC%
)

call "%~dp0setup.bat" %*
set "RC=%ERRORLEVEL%"
exit /b %RC%
