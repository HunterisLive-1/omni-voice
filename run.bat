@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul 2>&1

REM -----------------------------------------------------------------------
REM  run.bat — start OmniVoice Web UI
REM  Double-click this file or: run.bat
REM  If it closes instantly, open cmd here and run: setup.bat install
REM -----------------------------------------------------------------------

REM Pass extra args directly to setup.bat (e.g. run.bat verify, run.bat weights)
if not "%~1"=="" (
  call "%~dp0setup.bat" %*
  exit /b %ERRORLEVEL%
)

REM --- Check .venv exists before doing anything else ---
if not exist "%~dp0.venv\Scripts\activate.bat" (
  echo.
  echo  ============================================================
  echo   ERROR: .venv not found — you must run setup.bat first!
  echo  ============================================================
  echo.
  echo  Steps:
  echo    1. Double-click setup.bat
  echo    2. Choose your PyTorch build ^(1 = CUDA 12.8, 5 = CPU^)
  echo    3. Wait for install to finish
  echo    4. Double-click run.bat again
  echo.
  pause
  exit /b 1
)

REM --- Quick import check: Flask + omnivoice must be importable ---
"%~dp0.venv\Scripts\python.exe" -c "import flask" 2>nul
if errorlevel 1 (
  echo.
  echo  ============================================================
  echo   ERROR: Flask not found in .venv
  echo   Fix: double-click setup.bat ^> choose option 1 to reinstall
  echo  ============================================================
  echo.
  pause
  exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -c "import omnivoice" 2>nul
if errorlevel 1 (
  echo.
  echo  ============================================================
  echo   ERROR: omnivoice package not found in .venv
  echo   Fix: double-click setup.bat ^> choose option 1 or 7
  echo  ============================================================
  echo.
  pause
  exit /b 1
)

REM --- All good: start the Web UI ---
echo.
echo  Starting OmniVoice Web UI...
echo  Browser will open at http://127.0.0.1:8765
echo  ^(first run downloads model weights — this can take several minutes^)
echo.
echo  Press Ctrl+C to stop the server.
echo.

call "%~dp0setup.bat" run
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo  ============================================================
  echo   Web UI exited with error code %RC%
  echo.
  echo   Common fixes:
  echo     setup.bat deeprepair   ^(broken packages / null bytes^)
  echo     setup.bat fixhttpx     ^(httpx null bytes error^)
  echo     setup.bat verify       ^(check torch / CUDA^)
  echo.
  echo   If model download fails: check your internet connection,
  echo   or set HF_TOKEN if Hugging Face requires authentication.
  echo   Then run: setup.bat weights
  echo  ============================================================
  echo.
)
pause
exit /b %RC%
