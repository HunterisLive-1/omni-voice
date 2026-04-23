@echo off
REM ==============================================================================
REM  OmniVoice  --  GitHub se update  (non-tech / ZIP download users ke liye)
REM
REM    - Git check + version dikhata hai; nahi mila to winget se install koshish
REM    - GitHub se naya code (HunterisLive-1 / omni-voice)
REM    - Pehli baar sirf ZIP extract kiya ho: yahan .git nahi hota  --  setup.bat
REM      automatically link + sync karta hai.  .env  /  .venv  /  webui_data
REM      gitignore mein hain  --  aapka data safe.
REM
REM    Web UI chalane ke liye update ke baad:  run.bat
REM ==============================================================================

if "%~1"=="" (
  "%ComSpec%" /d /s /c call "%~f0" _OVU_CHILD_
  echo.
  echo  Press any key to close this window...
  pause >nul
  exit /b 0
)
if /i "%~1"=="_OVU_CHILD_" shift

cd /d "%~dp0"

echo.
echo  ============================================================
echo   OmniVoice  --  Update from GitHub
echo  ============================================================
echo   Aap ne ZIP se bhi project rakha ho  --  yahi chalane se chalega
echo  Apki  .env  /  .venv  /  webui_data  wali files aam tor par safe
echo  ============================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo  Git abhi nahi mila  --  aage  setup  Git install karega ^(winget, agar milta hai^)
) else (
  echo  Git  --  theek, version yahan:
  git --version
)
echo.
echo  Niche abhi  Git  +  code update  hoga. Thoda ruken...
echo.

call "%~dp0setup.bat" update
if errorlevel 1 exit /b 1
exit /b 0
