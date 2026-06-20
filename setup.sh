#!/usr/bin/env bash
# =============================================================================
#  OmniVoice — one-click setup + repair for macOS  (Apple Silicon & Intel)
#
#    ./setup.sh              FULLY AUTOMATIC — detects your Mac, installs
#                            everything, downloads weights, starts the Web UI.
#
#    ./setup.sh menu         Advanced repair / tools menu
#    ./setup.sh install      Full install / upgrade (no auto-launch)
#    ./setup.sh run          Start Web UI (same as run.sh)
#    ./setup.sh verify       Show torch / torchaudio / device (MPS or CPU)
#    ./setup.sh weights      Pre-download Hugging Face model files
#    ./setup.sh fixhttpx | fixaccelerate | deeprepair | repairomni
#    ./setup.sh torchcpu     Reinstall plain PyTorch (CPU + Apple MPS)
#    ./setup.sh update       Pull latest from GitHub (auto git init + origin)
#
#  Macs have no NVIDIA CUDA. On Apple Silicon the GPU is used via Metal/MPS;
#  on Intel Macs it runs on the CPU. The same PyTorch wheel covers both.
# =============================================================================
set -u

# ---- Resolve this script's directory and cd into it -------------------------
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
cd "$ROOT" || exit 1

VENV_DIR="$ROOT/.venv"
VPY="$VENV_DIR/bin/python"
SP=""   # site-packages, resolved after venv exists
OV_ORIGIN="https://github.com/HunterisLive-1/omni-voice.git"
TORCH_VER="2.8.0"

# Pin a torch version that actually has macOS wheels; fall back to latest if not.
PIP_TORCH=(torch==${TORCH_VER} torchaudio==${TORCH_VER})

say()  { printf '%s\n' "$*"; }
hr()   { say "============================================================"; }

# ---- Pick a Python 3.9–3.13 interpreter -------------------------------------
find_python() {
  local c
  for c in python3.12 python3.11 python3.10 python3.13 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; v=sys.version_info; raise SystemExit(0 if (3,9)<=(v.major,v.minor)<=(3,13) else 1)' >/dev/null 2>&1; then
        PYEXE="$c"; return 0
      fi
    fi
  done
  return 1
}

need_venv() {
  if [ ! -x "$VPY" ]; then
    say "No .venv — run  ./setup.sh  once (no arguments) to create it."
    return 1
  fi
  SP="$("$VPY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])' 2>/dev/null)"
  return 0
}

# ---- Git (only needed for ./setup.sh update) --------------------------------
ensure_git() {
  if command -v git >/dev/null 2>&1; then return 0; fi
  say ""
  say "Git not found. Install the Xcode command line tools (includes git):"
  say "    xcode-select --install"
  if command -v brew >/dev/null 2>&1; then
    say "Or with Homebrew:    brew install git"
  fi
  return 1
}

# =============================================================================
verify_torch_body() {
  say ""
  say "=== Verify torch / torchaudio / device ==="
  "$VPY" - <<'PY'
import torch, torchaudio
print("torch:", torch.__version__)
print("torchaudio:", torchaudio.__version__)
mps = getattr(torch.backends, "mps", None)
print("Apple MPS available:", bool(mps and mps.is_available()))
print("CUDA available:", torch.cuda.is_available())
print("Device that will be used:",
      "mps (Apple GPU)" if (mps and mps.is_available()) else "cpu")
PY
}

download_weights_body() {
  say ""
  say "=== Download k2-fsa/OmniVoice from Hugging Face ==="
  say "    Saves into ~/.cache/huggingface/hub  (main file ~2.5 GB)"
  say ""
  "$VPY" -c "from huggingface_hub import snapshot_download; p=snapshot_download('k2-fsa/OmniVoice', repo_type='model'); print('Done:', p)"
  local rc=$?
  if [ $rc -ne 0 ]; then
    say ""
    say "FAILED. Try: $VPY -m pip install -U huggingface_hub   (set HF_TOKEN if gated)"
    say "Direct files: https://huggingface.co/k2-fsa/OmniVoice/tree/main"
    return 1
  fi
}

fix_httpx_body() {
  say ""
  say "=== Fix corrupt httpx ==="
  "$VPY" -m pip uninstall -y httpx httpcore h11 >/dev/null 2>&1
  "$VPY" -m pip cache purge
  "$VPY" -m pip install --no-cache-dir --upgrade httpx httpcore h11 || return 1
  "$VPY" -c "import httpx; print('httpx OK:', httpx.__version__)" || return 1
}

fix_accelerate_body() {
  say ""
  say "=== Fix corrupt accelerate ==="
  if [ -n "$SP" ] && [ -d "$SP/accelerate" ]; then
    say "Removing folder accelerate/"
    rm -rf "$SP/accelerate"
    rm -rf "$SP"/accelerate*.dist-info "$SP"/accelerate*.egg-info 2>/dev/null
  fi
  "$VPY" -m pip cache purge
  say "Installing accelerate with --no-deps (keeps your torch build)"
  "$VPY" -m pip install --no-cache-dir --force-reinstall --no-deps "accelerate>=1.0" || return 1
  "$VPY" -c "import accelerate; print('accelerate OK:', accelerate.__version__)" || return 1
}

deep_repair_body() {
  say ""
  say "=== Deep repair: HF cache + accelerate + httpx + transformers + omnivoice ==="
  say "[1/3] Clearing Hugging Face hub cache for k2-fsa / OmniVoice ..."
  local hub="$HOME/.cache/huggingface/hub"
  if [ -d "$hub" ]; then
    find "$hub" -maxdepth 1 -type d \( -iname '*k2-fsa*' -o -iname '*OmniVoice*' \) -print -exec rm -rf {} + 2>/dev/null
  else
    say "No hub cache at $hub"
  fi
  say "[2/3] Removing broken packages ..."
  if [ -n "$SP" ]; then
    rm -rf "$SP/accelerate" "$SP"/accelerate*.dist-info "$SP"/accelerate*.egg-info 2>/dev/null
  fi
  "$VPY" -m pip uninstall -y omnivoice accelerate transformers tokenizers huggingface_hub httpx httpcore h11 >/dev/null 2>&1
  "$VPY" -m pip cache purge
  say "[3/3] Reinstalling without pip cache ..."
  "$VPY" -m pip install --no-cache-dir --upgrade h11 httpcore httpx "huggingface_hub>=0.26" "transformers>=5.3" "tokenizers>=0.22" omnivoice || return 1
  "$VPY" -m pip install --no-cache-dir --force-reinstall --no-deps "accelerate>=1.0" || return 1
  say "Done. Run ./run.sh and use 'Retry loading model' if needed."
}

repair_omnivoice_body() {
  say ""
  say "=== Reinstall omnivoice (no pip cache) ==="
  "$VPY" -m pip uninstall -y omnivoice >/dev/null 2>&1
  "$VPY" -m pip cache purge
  "$VPY" -m pip install --no-cache-dir --upgrade omnivoice || return 1
}

reinstall_torch_cpu_body() {
  say ""
  say "=== PyTorch ${TORCH_VER} (CPU + Apple MPS) ==="
  "$VPY" -m pip uninstall -y torch torchaudio torchvision >/dev/null 2>&1
  "$VPY" -m pip cache purge
  "$VPY" -m pip install "${PIP_TORCH[@]}" || \
    "$VPY" -m pip install torch torchaudio || return 1
  "$VPY" -c "import torch; print('torch', torch.__version__, '| mps:', bool(getattr(torch.backends,'mps',None) and torch.backends.mps.is_available()))" || return 1
}

# =============================================================================
update_repo_body() {
  say ""
  say "=== Update from GitHub ==="
  say " Repo: $OV_ORIGIN"
  ensure_git || return 1

  if [ ! -d ".git" ]; then
    say ""
    say " No .git folder (e.g. GitHub ZIP). Initializing repo and linking origin..."
    say " Your .env / .venv / webui_data stay (they're gitignored)."
    git init || return 1
    if git remote get-url origin >/dev/null 2>&1; then
      git remote set-url origin "$OV_ORIGIN"
    else
      git remote add origin "$OV_ORIGIN"
    fi
    if git fetch origin main 2>/dev/null; then
      git checkout -f -B main origin/main || return 1
      git branch --set-upstream-to=origin/main main 2>/dev/null
    else
      say " Trying branch master..."
      git fetch origin master || { say " git fetch failed. Check internet."; return 1; }
      git checkout -f -B main origin/master || return 1
      git branch --set-upstream-to=origin/master main 2>/dev/null
    fi
    say " Linked and synced to GitHub (first-time ZIP setup)."
  else
    say ""
    say " Fetching and pulling (fast-forward only)..."
    git remote get-url origin >/dev/null 2>&1 || git remote add origin "$OV_ORIGIN"
    git fetch origin || { say " git fetch failed. Check internet."; return 1; }
    if ! git pull --ff-only; then
      say ""
      say " git pull failed. Local edits may block fast-forward."
      say " Try: git status   or   git stash -u   then   ./setup.sh update"
      return 1
    fi
    say " Project files updated."
  fi

  if [ -x "$VPY" ]; then
    say " Refreshing pip packages from requirements..."
    if [ -f "$ROOT/requirements.txt" ]; then
      "$VPY" -m pip install -r "$ROOT/requirements.txt" --upgrade
    else
      "$VPY" -m pip install --upgrade omnivoice "flask>=3.0"
    fi
  fi
}

# =============================================================================
install() {
  clear 2>/dev/null || true
  say ""
  hr
  say "  OmniVoice — Automatic installer (macOS)"
  say "  Detecting your Mac and installing everything..."
  hr
  say ""
  say "  [Step 1 of 5]  Checking Python installation..."
  if ! find_python; then
    hr
    say "  ERROR: Python 3.9–3.13 not found."
    hr
    say "  Install Python (3.12 recommended):"
    say "    • Homebrew:  brew install python@3.12"
    say "    • Or download: https://www.python.org/downloads/macos/"
    say "  Then run  ./setup.sh  again."
    return 1
  fi
  say "  OK: $("$PYEXE" -c 'import sys;print("Python", sys.version.split()[0])')"

  local arch; arch="$(uname -m)"
  if [ "$arch" = "arm64" ]; then
    say "  Mac type: Apple Silicon ($arch) — GPU acceleration via Metal/MPS."
  else
    say "  Mac type: Intel ($arch) — will run on CPU."
  fi
  say ""

  say "  [Step 2 of 5]  Creating virtual environment (.venv)..."
  if [ ! -x "$VPY" ]; then
    "$PYEXE" -m venv "$VENV_DIR" || { say "  ERROR: failed to create venv."; return 1; }
    say "  OK: virtual environment created."
  else
    say "  OK: using existing .venv."
  fi
  need_venv || return 1
  "$VPY" -m pip install --upgrade pip --quiet
  say ""

  say "  [Step 3 of 5]  Installing PyTorch (CPU + Apple MPS)..."
  if ! "$VPY" -m pip install "${PIP_TORCH[@]}"; then
    say "  Pinned torch ${TORCH_VER} not available for this Mac — installing latest torch."
    "$VPY" -m pip install torch torchaudio || { say "  ERROR: PyTorch install failed."; return 1; }
  fi
  say "  OK: PyTorch installed."
  say ""

  say "  [Step 4 of 5]  Installing OmniVoice + Flask..."
  "$VPY" -m pip install "numpy<2.0" --quiet
  if [ -f "$ROOT/requirements.txt" ]; then
    "$VPY" -m pip install -r "$ROOT/requirements.txt" || { say "  ERROR: dependency install failed."; return 1; }
  else
    "$VPY" -m pip install omnivoice "flask>=3.0" "accelerate>=1.0" "python-dotenv>=1.0.0" || return 1
  fi
  say "  OK: OmniVoice and Flask installed."
  say ""

  say "  [Step 5 of 5]  Downloading OmniVoice model weights (~2.5 GB)..."
  say "                 (saves to ~/.cache/huggingface/hub; 5–30 min first time)"
  if ! download_weights_body; then
    say "  WARNING: weight download had errors — the model retries on first run."
  fi

  say ""
  hr
  say "  All done! OmniVoice is ready."
  say "  Update later:  ./setup.sh update"
  hr

  if [ "${AUTO_MODE:-0}" = "1" ]; then
    say "  Starting the Web UI now (next time just run ./run.sh)..."
    sleep 2
    run_webui
    return $?
  fi
  say "  Next: run  ./run.sh  to start the Web UI."
}

run_webui() {
  if [ ! -x "$VPY" ]; then
    say "No .venv found. Run ./setup.sh first."
    return 1
  fi
  need_venv || return 1
  export PYTORCH_ENABLE_MPS_FALLBACK=1
  say ""
  say "Starting Web UI:  $VPY  $ROOT/webui.py"
  say "Device: Apple GPU (MPS) is used automatically on Apple Silicon; CPU otherwise."
  say "The model loads only when you press Generate in the browser."
  say ""
  "$VPY" -u "$ROOT/webui.py"
}

# =============================================================================
menu() {
  while true; do
    say ""
    say "========================================"
    say " OmniVoice — setup / repair (macOS)"
    say "========================================"
    say " 1  Full install or upgrade (PyTorch + omnivoice + Flask)"
    say " 2  Start Web UI (same as run.sh)"
    say " 3  Verify torch / device (MPS or CPU)"
    say " 4  Fix httpx (null bytes in traceback)"
    say " 5  Fix accelerate (null bytes; uses --no-deps)"
    say " 6  Deep repair (HF cache + httpx stack + omnivoice)"
    say " 7  Reinstall omnivoice only"
    say " 8  Reinstall PyTorch (CPU + Apple MPS)"
    say " D  Download / update model weights from Hugging Face"
    say " U  Update project from GitHub"
    say " 0  Exit"
    say "========================================"
    printf "Enter choice: "
    read -r CH
    case "$CH" in
      1) AUTO_MODE=0; install ;;
      2) run_webui ;;
      3) need_venv && verify_torch_body ;;
      4) need_venv && fix_httpx_body ;;
      5) need_venv && fix_accelerate_body ;;
      6) need_venv && deep_repair_body ;;
      7) need_venv && repair_omnivoice_body ;;
      8) need_venv && reinstall_torch_cpu_body ;;
      [Dd]) need_venv && download_weights_body ;;
      [Uu]) update_repo_body ;;
      0) return 0 ;;
      *) say "Invalid choice." ;;
    esac
  done
}

# =============================================================================
AUTO_MODE=0
cmd="${1:-}"
case "$cmd" in
  menu)          menu ;;
  run)           run_webui ;;
  install)       AUTO_MODE=0; install ;;
  weights)       need_venv && download_weights_body ;;
  verify)        need_venv && verify_torch_body ;;
  fixhttpx)      need_venv && fix_httpx_body ;;
  fixaccelerate) need_venv && fix_accelerate_body ;;
  deeprepair)    need_venv && deep_repair_body ;;
  repairomni)    need_venv && repair_omnivoice_body ;;
  torchcpu)      need_venv && reinstall_torch_cpu_body ;;
  update)        update_repo_body ;;
  "")
    # No args: fully automatic. If .venv works, just launch; else install.
    AUTO_MODE=1
    if [ -x "$VPY" ] && "$VPY" -c "import flask, omnivoice" >/dev/null 2>&1; then
      say ""
      say " OmniVoice is already installed. Starting Web UI..."
      say " (Tip: run  ./setup.sh menu  for repair tools)"
      run_webui
    else
      [ -x "$VPY" ] && say " .venv exists but packages are broken — reinstalling..."
      install
    fi
    ;;
  *)
    say "Unknown command: $cmd"
    say "Try: ./setup.sh  |  menu | install | run | verify | weights | update"
    exit 1
    ;;
esac
