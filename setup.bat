@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "VPY=%VENV_DIR%\Scripts\python.exe"
set "SP=%VENV_DIR%\Lib\site-packages"

REM ---------------------------------------------------------------------------
REM  OmniVoice — single setup + repair entry (only batch file besides run.bat)
REM    setup.bat              First install, or menu if .venv exists
REM    setup.bat install      Full install / upgrade (non-interactive shortcut)
REM    setup.bat run          Web UI (same as run.bat)
REM    setup.bat verify | fixhttpx | fixaccelerate | deeprepair | repairomni
REM    setup.bat torchcu128 | torchcu124 | torchcu121 | torchcu118 | torchcpu
REM    setup.bat weights   — pre-download HF model files (~several GB^)
REM ---------------------------------------------------------------------------

if /i "%~1"=="run" goto :run
if /i "%~1"=="install" goto :install
if /i "%~1"=="weights" goto :download_weights_cli
if /i "%~1"=="verify" goto :verify_torch_cli
if /i "%~1"=="fixhttpx" goto :fix_httpx_cli
if /i "%~1"=="fixaccelerate" goto :fix_accelerate_cli
if /i "%~1"=="deeprepair" goto :deep_repair_cli
if /i "%~1"=="repairomni" goto :repair_omnivoice_cli
if /i "%~1"=="torchcu128" goto :reinstall_torch_cu128_cli
if /i "%~1"=="torchcu124" goto :reinstall_torch_cu124_cli
if /i "%~1"=="torchcu121" goto :reinstall_torch_cu121_cli
if /i "%~1"=="torchcu118" goto :reinstall_torch_cu118_cli
if /i "%~1"=="torchcpu" goto :reinstall_torch_cpu_cli

if not exist "%VENV_DIR%\Scripts\activate.bat" goto :install
goto :menu

REM ===========================================================================
:menu
echo.
echo ========================================
echo  OmniVoice — setup / repair
echo ========================================
echo  1  Full install or upgrade ^(PyTorch + omnivoice + Flask^)
echo  2  Start Web UI ^(same as run.bat^)
echo  3  Verify torch / CUDA
echo  4  Fix httpx ^(null bytes in traceback^)
echo  5  Fix accelerate ^(null bytes; uses --no-deps^)
echo  6  Deep repair ^(HF hub cache + httpx stack + omnivoice^)
echo  7  Reinstall omnivoice only
echo  8  Reinstall PyTorch CUDA 12.8  ^(driver ^>= 527, RTX 40/50 series^)
echo  9  Reinstall PyTorch CPU        ^(no NVIDIA GPU, or AMD/Intel^)
echo  A  Reinstall PyTorch CUDA 11.8  ^(driver ^>= 452, older GTX/RTX cards^)
echo  B  Reinstall PyTorch CUDA 12.1  ^(driver ^>= 530^)
echo  C  Reinstall PyTorch CUDA 12.4  ^(driver ^>= 550, RTX 30/40 series^)
echo  D  Download / update model weights from Hugging Face ^(large download^)
echo  0  Exit
echo ========================================
set "CH="
set /p CH="Enter choice [0-9 or D]: "
if "%CH%"=="1" goto :install
if "%CH%"=="2" goto :run
if "%CH%"=="3" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :verify_torch_body
  pause
  goto :menu
)
if "%CH%"=="4" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :fix_httpx_body
  pause
  goto :menu
)
if "%CH%"=="5" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :fix_accelerate_body
  pause
  goto :menu
)
if "%CH%"=="6" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :deep_repair_body
  if errorlevel 1 (
    echo FAILED. Try deleting the .venv folder, then setup.bat install
  )
  pause
  goto :menu
)
if "%CH%"=="7" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :repair_omnivoice_body
  pause
  goto :menu
)
if "%CH%"=="8" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :reinstall_torch_cu128_body
  if errorlevel 1 echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  goto :menu
)
if "%CH%"=="9" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :reinstall_torch_cpu_body
  pause
  goto :menu
)
if /i "%CH%"=="a" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :reinstall_torch_cu118_body
  if errorlevel 1 echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  goto :menu
)
if /i "%CH%"=="b" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :reinstall_torch_cu121_body
  if errorlevel 1 echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  goto :menu
)
if /i "%CH%"=="c" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :reinstall_torch_cu124_body
  if errorlevel 1 echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  goto :menu
)
if /i "%CH%"=="d" (
  call :need_venv
  if errorlevel 1 ( pause & goto :menu )
  call :download_weights_body
  pause
  goto :menu
)
if "%CH%"=="0" exit /b 0
echo Invalid choice.
pause
goto :menu

REM ===========================================================================
:download_weights_body
echo.
echo === Download k2-fsa/OmniVoice from Hugging Face ===
echo     Saves into your HF hub cache ^(usually %%USERPROFILE%%\.cache\huggingface\hub^)
echo     Main file model.safetensors is ~2.5 GB; full snapshot is larger.
echo.
call "%VENV_DIR%\Scripts\activate.bat"
"%VPY%" -c "from huggingface_hub import snapshot_download; p=snapshot_download('k2-fsa/OmniVoice', repo_type='model'); print('Done:', p)"
if errorlevel 1 (
  echo.
  echo FAILED. Try: pip install -U huggingface_hub   Set HF_TOKEN if access is gated.
  echo Direct files: https://huggingface.co/k2-fsa/OmniVoice/tree/main
  exit /b 1
)
echo.
exit /b 0

:download_weights_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :download_weights_body
if errorlevel 1 ( pause & exit /b 1 )
pause
exit /b 0

REM ===========================================================================
:need_venv
if not exist "%VENV_DIR%\Scripts\activate.bat" (
  echo No .venv — run setup.bat once without arguments to create it.
  exit /b 1
)
exit /b 0

REM ===========================================================================
:verify_torch_body
echo.
echo === Verify torch / torchaudio / CUDA ===
"%VPY%" -c "import torch, torchaudio; print('torch:', torch.__version__); print('torchaudio:', torchaudio.__version__); print('cuda available:', torch.cuda.is_available()); print('cuda device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
if errorlevel 1 exit /b 1
exit /b 0

:verify_torch_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :verify_torch_body
set "VTC=!ERRORLEVEL!"
pause
exit /b !VTC!

REM ===========================================================================
:fix_httpx_body
echo.
echo === Fix corrupt httpx ===
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip uninstall -y httpx httpcore h11 2>nul
python -m pip cache purge
python -m pip install --no-cache-dir --upgrade httpx httpcore h11
if errorlevel 1 exit /b 1
python -c "import httpx; print('httpx OK:', httpx.__version__)"
if errorlevel 1 exit /b 1
exit /b 0

:fix_httpx_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :fix_httpx_body
if errorlevel 1 ( pause & exit /b 1 )
echo Done. Run run.bat again.
pause
exit /b 0

REM ===========================================================================
:fix_accelerate_body
echo.
echo === Fix corrupt accelerate ===
echo If pip uninstall fails, site-packages folders are removed by hand.
echo.
pushd "%SP%"
if exist accelerate (
  echo Removing folder accelerate\
  rd /s /q accelerate
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -Directory -ErrorAction SilentlyContinue | " ^
  "Where-Object { $_.Name -like 'accelerate*.dist-info' -or $_.Name -like 'accelerate*.egg-info' } | " ^
  "ForEach-Object { Write-Host ('Removing ' + $_.Name); Remove-Item -LiteralPath $_.FullName -Recurse -Force }"
popd
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip cache purge
echo.
echo Installing accelerate with --no-deps ^(does not replace your CUDA torch^)
python -m pip install --no-cache-dir --force-reinstall --no-deps "accelerate>=1.0"
if errorlevel 1 exit /b 1
python -c "import accelerate; print('accelerate OK:', accelerate.__version__)"
if errorlevel 1 exit /b 1
python -c "import torch; v=torch.__version__; print('torch:', v, '| cuda:', torch.cuda.is_available()); raise SystemExit(0 if torch.cuda.is_available() else 10)"
if errorlevel 10 (
  echo.
  echo *** PyTorch CUDA is NOT available. If you have an NVIDIA GPU:
  echo *** Open setup.bat menu and pick the right CUDA build:
  echo ***   driver ^>= 527  → option 8  ^(CUDA 12.8^)
  echo ***   driver ^>= 550  → option C  ^(CUDA 12.4^)
  echo ***   driver ^>= 530  → option B  ^(CUDA 12.1^)
  echo ***   driver ^>= 452  → option A  ^(CUDA 11.8^)
  echo *** Check your driver: run  nvidia-smi  and look for "CUDA Version".
  echo *** CPU-only on purpose: ignore the lines above.
  echo.
)
exit /b 0

:fix_accelerate_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :fix_accelerate_body
if errorlevel 1 ( pause & exit /b 1 )
echo Done. Run run.bat again.
pause
exit /b 0

REM ===========================================================================
:deep_repair_body
echo.
echo === Deep repair: HF cache + accelerate + httpx + hub + transformers + omnivoice ===
call "%VENV_DIR%\Scripts\activate.bat"
echo [1/3] Clearing Hugging Face hub cache for k2-fsa / OmniVoice ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root = Join-Path $env:USERPROFILE '.cache\huggingface\hub'; " ^
  "if (-not (Test-Path -LiteralPath $root)) { Write-Host 'No hub cache at' $root; exit 0 }; " ^
  "Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | " ^
  "  Where-Object { $_.Name -match 'k2-fsa|OmniVoice' } | " ^
  "  ForEach-Object { Write-Host ('Removing ' + $_.Name); Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }"
echo.
echo [2/3] Removing broken packages ...
pushd "%SP%"
if exist accelerate rd /s /q accelerate 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'accelerate*.dist-info' -or $_.Name -like 'accelerate*.egg-info' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
popd
python -m pip uninstall -y omnivoice accelerate transformers tokenizers huggingface_hub httpx httpcore h11 2>nul
python -m pip cache purge
echo.
echo [3/3] Reinstalling without pip cache ...
echo accelerate is installed with --no-deps so pip does not swap CUDA torch for CPU 2.11.x
python -m pip install --no-cache-dir --upgrade h11 httpcore httpx "huggingface_hub>=0.26" "transformers>=5.3" "tokenizers>=0.22" omnivoice
if errorlevel 1 exit /b 1
python -m pip install --no-cache-dir --force-reinstall --no-deps "accelerate>=1.0"
if errorlevel 1 exit /b 1
echo.
echo NVIDIA GPU: if torch is not 2.8.x+cu128, use menu 8 or setup.bat torchcu128
echo Done. Run run.bat and use Retry loading model if needed.
exit /b 0

:deep_repair_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :deep_repair_body
if errorlevel 1 (
  echo FAILED. Try deleting the .venv folder, then setup.bat install
  pause
  exit /b 1
)
pause
exit /b 0

REM ===========================================================================
:repair_omnivoice_body
echo.
echo === Reinstall omnivoice (no pip cache^) ===
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip uninstall -y omnivoice 2>nul
python -m pip cache purge
python -m pip install --no-cache-dir --upgrade omnivoice
if errorlevel 1 exit /b 1
exit /b 0

:repair_omnivoice_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :repair_omnivoice_body
if errorlevel 1 ( pause & exit /b 1 )
echo Done. Run run.bat again.
pause
exit /b 0

REM ===========================================================================
:reinstall_torch_cu128_body
echo.
echo === PyTorch 2.8.0 + CUDA 12.8 ===
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip uninstall -y torch torchaudio torchvision 2>nul
python -m pip cache purge
python -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 exit /b 1
python -c "import torch; print('torch', torch.__version__, '| cuda:', torch.cuda.is_available())"
if errorlevel 1 exit /b 1
exit /b 0

:reinstall_torch_cu128_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :reinstall_torch_cu128_body
if errorlevel 1 (
  echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  exit /b 1
)
pause
exit /b 0

REM ===========================================================================
:reinstall_torch_cu118_body
echo.
echo === PyTorch CUDA 11.8 ^(driver ^>= 452, older GTX/RTX cards^) ===
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip uninstall -y torch torchaudio torchvision 2>nul
python -m pip cache purge
python -m pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cu118
if errorlevel 1 exit /b 1
python -c "import torch; print('torch', torch.__version__, '| cuda:', torch.cuda.is_available())"
if errorlevel 1 exit /b 1
exit /b 0

:reinstall_torch_cu118_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :reinstall_torch_cu118_body
if errorlevel 1 (
  echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  exit /b 1
)
pause
exit /b 0

REM ===========================================================================
:reinstall_torch_cu121_body
echo.
echo === PyTorch CUDA 12.1 ^(driver ^>= 530^) ===
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip uninstall -y torch torchaudio torchvision 2>nul
python -m pip cache purge
python -m pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cu121
if errorlevel 1 exit /b 1
python -c "import torch; print('torch', torch.__version__, '| cuda:', torch.cuda.is_available())"
if errorlevel 1 exit /b 1
exit /b 0

:reinstall_torch_cu121_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :reinstall_torch_cu121_body
if errorlevel 1 (
  echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  exit /b 1
)
pause
exit /b 0

REM ===========================================================================
:reinstall_torch_cu124_body
echo.
echo === PyTorch CUDA 12.4 ^(driver ^>= 550^) ===
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip uninstall -y torch torchaudio torchvision 2>nul
python -m pip cache purge
python -m pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cu124
if errorlevel 1 exit /b 1
python -c "import torch; print('torch', torch.__version__, '| cuda:', torch.cuda.is_available())"
if errorlevel 1 exit /b 1
exit /b 0

:reinstall_torch_cu124_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :reinstall_torch_cu124_body
if errorlevel 1 (
  echo Install failed. See https://pytorch.org/get-started/locally/
  pause
  exit /b 1
)
pause
exit /b 0

REM ===========================================================================
:reinstall_torch_cpu_body
echo.
echo === PyTorch 2.8.0 CPU ===
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip uninstall -y torch torchaudio torchvision 2>nul
python -m pip cache purge
python -m pip install torch==2.8.0 torchaudio==2.8.0
if errorlevel 1 exit /b 1
python -c "import torch; print('torch', torch.__version__, '| cuda:', torch.cuda.is_available())"
if errorlevel 1 exit /b 1
exit /b 0

:reinstall_torch_cpu_cli
call :need_venv
if errorlevel 1 ( pause & exit /b 1 )
call :reinstall_torch_cpu_body
if errorlevel 1 ( pause & exit /b 1 )
pause
exit /b 0

REM ===========================================================================
:install
echo.
echo ========================================
echo  OmniVoice - Windows install
echo ========================================
echo.

set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo ERROR: Python 3 not found. Install from https://www.python.org/downloads/
  echo        Enable "Add python.exe to PATH" or use the "py" launcher.
  echo.
  pause
  exit /b 1
)

if not exist "%VENV_DIR%\Scripts\activate.bat" (
  echo Creating virtual environment: .venv
  %PYEXE% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo ERROR: Failed to create venv.
    echo.
    pause
    exit /b 1
  )
) else (
  echo Using existing virtual environment: .venv
)

if not exist "%VPY%" (
  echo ERROR: venv python missing: %VPY%
  echo.
  pause
  exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo.
echo Detecting NVIDIA GPU and CUDA driver version...
set "_DETECT=none|cpu"
"%VPY%" -c "import subprocess,re,sys; r=subprocess.run(['nvidia-smi'],capture_output=True,text=True,timeout=10); m=re.search(r'CUDA Version: (\d+)\.(\d+)',r.stdout); mj,mn=(int(m.group(1)),int(m.group(2))) if m else (0,0); v=mj*10+mn; rec='cu128' if v>=128 else 'cu124' if v>=124 else 'cu121' if v>=121 else 'cu118' if v>=118 else 'cpu'; print(str(mj)+'.'+str(mn)+'|'+rec if m else 'none|cpu')" >"%TEMP%\ov_detect.tmp" 2>nul
if exist "%TEMP%\ov_detect.tmp" (
    set /p _DETECT=<"%TEMP%\ov_detect.tmp"
    del "%TEMP%\ov_detect.tmp" >nul 2>&1
)
set "_CUDA_VER=none"
set "_REC_BUILD=cpu"
for /f "tokens=1,2 delims=|" %%A in ("!_DETECT!") do (
    set "_CUDA_VER=%%A"
    set "_REC_BUILD=%%B"
)

set "_AUTO=5"
set "_AUTO_LABEL=CPU only"
if "!_CUDA_VER!"=="none" (
    echo   No NVIDIA GPU detected ^(nvidia-smi not found or no GPU^).
) else (
    echo   NVIDIA GPU found — driver CUDA version: !_CUDA_VER!
    if "!_REC_BUILD!"=="cu128" ( set "_AUTO=1" & set "_AUTO_LABEL=CUDA 12.8 ^(recommended^)" )
    if "!_REC_BUILD!"=="cu124" ( set "_AUTO=3" & set "_AUTO_LABEL=CUDA 12.4 ^(recommended^)" )
    if "!_REC_BUILD!"=="cu121" ( set "_AUTO=4" & set "_AUTO_LABEL=CUDA 12.1 ^(recommended^)" )
    if "!_REC_BUILD!"=="cu118" ( set "_AUTO=2" & set "_AUTO_LABEL=CUDA 11.8 ^(recommended^)" )
    if "!_REC_BUILD!"=="cpu"   ( set "_AUTO=5" & set "_AUTO_LABEL=CPU only — driver too old, please update NVIDIA drivers" )
)
echo.
echo Choose PyTorch build:
echo   1 = NVIDIA GPU, CUDA 12.8  ^(driver ^>= 527  e.g. RTX 40/50 series^)
echo   2 = NVIDIA GPU, CUDA 11.8  ^(driver ^>= 452, older GTX/RTX cards^)
echo   3 = NVIDIA GPU, CUDA 12.4  ^(driver ^>= 550^)
echo   4 = NVIDIA GPU, CUDA 12.1  ^(driver ^>= 530^)
echo   5 = CPU only               ^(no NVIDIA GPU, or AMD/Intel GPU^)
echo.
echo   Auto-detected recommendation: !_AUTO! ^(!_AUTO_LABEL!^)
echo.
set "TORCH_CHOICE="
set /p TORCH_CHOICE="Enter 1-5 [default !_AUTO!]: "
if "!TORCH_CHOICE!"=="" set "TORCH_CHOICE=!_AUTO!"

if "!TORCH_CHOICE!"=="1" (
    echo.
    echo Installing PyTorch with CUDA 12.8...
    "%VPY%" -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
) else if "!TORCH_CHOICE!"=="2" (
    echo.
    echo Installing PyTorch with CUDA 11.8...
    "%VPY%" -m pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cu118
) else if "!TORCH_CHOICE!"=="3" (
    echo.
    echo Installing PyTorch with CUDA 12.4...
    "%VPY%" -m pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cu124
) else if "!TORCH_CHOICE!"=="4" (
    echo.
    echo Installing PyTorch with CUDA 12.1...
    "%VPY%" -m pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cu121
) else (
    echo.
    echo Installing PyTorch CPU build...
    "%VPY%" -m pip install torch==2.8.0 torchaudio==2.8.0
)
if errorlevel 1 (
  echo.
  echo ERROR: PyTorch install failed. See https://pytorch.org/get-started/locally/
  echo.
  pause
  exit /b 1
)

echo.
echo Installing omnivoice package...
"%VPY%" -m pip install omnivoice
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo.
echo Installing Flask (Web UI^)...
"%VPY%" -m pip install "flask>=3.0"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo.
echo ========================================
echo  Install finished.
echo ========================================
echo  Double-click run.bat for the Web UI.
echo  Repairs: double-click setup.bat ^(menu^) or run: setup.bat deeprepair
echo  Large weights ^(model.safetensors, etc.^) are NOT on GitHub — see README.
echo  Optional: set HF_TOKEN if Hugging Face requires it.
echo ========================================
echo.
set "PREDL="
set /p PREDL="Download OmniVoice weights from Hugging Face now? ~several GB [y/N]: "
if /i "!PREDL!"=="y" (
  call :download_weights_body
  if errorlevel 1 echo Weight download had errors — they will retry on first run.bat
)
echo.
pause
exit /b 0

REM ===========================================================================
:run
if not exist "%VENV_DIR%\Scripts\activate.bat" (
  echo No .venv found. Run setup.bat first.
  echo.
  pause
  exit /b 1
)

if not exist "%VPY%" (
  echo ERROR: venv python not found:
  echo   %VPY%
  echo Run setup.bat install to repair.
  echo.
  pause
  exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"

echo.
echo Starting Web UI with:
echo   %VPY%
echo   %~dp0webui.py
echo.
echo If this window closes instantly, open cmd here and run: setup.bat install
echo.

"%VPY%" -u "%~dp0webui.py"
set "ERR=!ERRORLEVEL!"
exit /b !ERR!
