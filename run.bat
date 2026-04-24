@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM -----------------------------------------------------------------------
REM  run.bat -- start OmniVoice Web UI
REM
REM  Double-click this file, or run it from cmd.
REM  If the window still closes instantly:
REM    1) Open a cmd window here (Shift + right-click -> "Open in Terminal")
REM    2) Run:  run.bat
REM    Any error message will stay on screen.
REM
REM  All output is ASCII-only so Windows never has codepage trouble.
REM -----------------------------------------------------------------------

set "VENV_DIR=%~dp0.venv"
set "VPY=%VENV_DIR%\Scripts\python.exe"

REM -- If any arg is passed, forward to setup.bat (e.g. run.bat verify) --
if not "%~1"=="" (
  call "%~dp0setup.bat" %*
  set "RC=!ERRORLEVEL!"
  if not "!RC!"=="0" (
    echo.
    echo   setup.bat exited with error code !RC!
    echo.
    pause
  )
  endlocal & exit /b %RC%
)

REM -- 1) venv must exist -------------------------------------------------
if not exist "%VENV_DIR%\Scripts\activate.bat" goto :err_no_venv
if not exist "%VPY%" goto :err_no_venv_python

REM -- 2) Flask must import ----------------------------------------------
"%VPY%" -c "import flask" 1>nul 2>nul
if errorlevel 1 goto :err_no_flask

REM -- 3) omnivoice must import ------------------------------------------
"%VPY%" -c "import omnivoice" 1>nul 2>nul
if errorlevel 1 goto :err_no_omnivoice

REM -- 4) All good: start the Web UI -------------------------------------
echo.
echo   Starting OmniVoice Web UI...
echo   Browser will open at http://127.0.0.1:8765
echo   GPU loads the model only after you press Generate speech (not before).
echo   (first download can take 5 to 30 minutes)
echo.
echo   Press Ctrl+C to stop the server.
echo.

call "%~dp0setup.bat" run
set "RC=!ERRORLEVEL!"

if "!RC!"=="0" goto :clean_exit
goto :err_webui_crashed

REM =======================================================================
:err_no_venv
echo.
echo  ============================================================
echo   ERROR: .venv folder not found -- setup has not been run yet
echo  ============================================================
echo.
echo   How to fix:
echo     1. Double-click setup.bat  ^(it is automatic^)
echo     2. Wait for install to finish
echo     3. Double-click run.bat again
echo.
goto :end_with_pause

:err_no_venv_python
echo.
echo  ============================================================
echo   ERROR: .venv exists but Python is missing from it:
echo     "%VPY%"
echo  ============================================================
echo.
echo   How to fix:
echo     1. Delete the .venv folder in this directory
echo     2. Double-click setup.bat to reinstall
echo.
goto :end_with_pause

:err_no_flask
echo.
echo  ============================================================
echo   ERROR: Flask not installed ^(or .venv Python is broken^)
echo  ============================================================
echo.
echo   How to fix:
echo     Open cmd here and run:   setup.bat install
echo     Or delete the .venv folder and double-click setup.bat
echo.
goto :end_with_pause

:err_no_omnivoice
echo.
echo  ============================================================
echo   ERROR: omnivoice package not found in .venv
echo  ============================================================
echo.
echo   How to fix:
echo     Open cmd here and run:   setup.bat repairomni
echo     Or:                      setup.bat install
echo.
goto :end_with_pause

:err_webui_crashed
echo.
echo  ============================================================
echo   Web UI exited with error code !RC!
echo  ============================================================
echo.
echo   Common fixes ^(open cmd here and run one of these^):
echo     setup.bat verify         check torch / CUDA install
echo     setup.bat deeprepair     broken packages / null bytes errors
echo     setup.bat fixhttpx       httpx null bytes error
echo     setup.bat fixaccelerate  accelerate import error
echo.
echo   If model download failed:
echo     - Check your internet connection
echo     - If Hugging Face asked for auth: set HF_TOKEN=hf_xxx
echo     - Then run:  setup.bat weights
echo.
goto :end_with_pause

:end_with_pause
echo.
pause
endlocal & exit /b 1

:clean_exit
endlocal & exit /b 0
