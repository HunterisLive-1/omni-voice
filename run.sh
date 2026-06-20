#!/usr/bin/env bash
# -----------------------------------------------------------------------------
#  run.sh — start the OmniVoice Web UI on macOS
#
#  Usage:
#    ./run.sh              start the Web UI
#    ./run.sh verify       forwarded to setup.sh (any arg is forwarded)
#
#  First time:  run  ./setup.sh  (it installs everything, then launches this).
#  Apple Silicon Macs use the GPU via Metal/MPS automatically; Intel runs on CPU.
# -----------------------------------------------------------------------------
set -u

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

say() { printf '%s\n' "$*"; }

# -- Any argument? forward to setup.sh (e.g. ./run.sh verify) -----------------
if [ "$#" -gt 0 ]; then
  bash "$ROOT/setup.sh" "$@"
  exit $?
fi

# -- 1) venv must exist -------------------------------------------------------
if [ ! -x "$VPY" ]; then
  say ""
  say " ============================================================"
  say "  ERROR: .venv not found — setup has not been run yet"
  say " ============================================================"
  say ""
  say "  How to fix:"
  say "    1. Run:  ./setup.sh   (it is automatic)"
  say "    2. Wait for install to finish"
  say "    3. Run:  ./run.sh     again"
  say ""
  exit 1
fi

# -- 2) Flask must import -----------------------------------------------------
if ! "$VPY" -c "import flask" >/dev/null 2>&1; then
  say ""
  say "  ERROR: Flask not installed (or .venv Python is broken)"
  say "  Fix:  ./setup.sh install   (or delete .venv and run ./setup.sh)"
  say ""
  exit 1
fi

# -- 3) omnivoice must import -------------------------------------------------
if ! "$VPY" -c "import omnivoice" >/dev/null 2>&1; then
  say ""
  say "  ERROR: omnivoice package not found in .venv"
  say "  Fix:  ./setup.sh repairomni    or    ./setup.sh install"
  say ""
  exit 1
fi

# -- 4) All good: start the Web UI -------------------------------------------
say ""
say "  Starting OmniVoice Web UI..."
say "  Browser: http://127.0.0.1:8765"
say "  Apple Silicon GPU (MPS) is used automatically; Intel Macs use the CPU."
say "  The model loads only after you press 'Generate speech'."
say "  (first download can take 5 to 30 minutes)"
say ""
say "  Press Ctrl+C to stop the server."
say ""

# Let unsupported MPS ops fall back to CPU instead of crashing on Apple Silicon.
export PYTORCH_ENABLE_MPS_FALLBACK=1

"$VPY" -u "$ROOT/webui.py"
RC=$?

if [ "$RC" -ne 0 ]; then
  say ""
  say " ============================================================"
  say "  Web UI exited with error code $RC"
  say " ============================================================"
  say ""
  say "  Common fixes:"
  say "    ./setup.sh verify         check torch / device"
  say "    ./setup.sh deeprepair     broken packages / null bytes errors"
  say "    ./setup.sh fixhttpx       httpx null bytes error"
  say "    ./setup.sh fixaccelerate  accelerate import error"
  say ""
fi
exit $RC
