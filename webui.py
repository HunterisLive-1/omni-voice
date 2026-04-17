"""
OmniVoice local Web UI — opens in your browser when you run run.bat.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import warnings
import webbrowser
from pathlib import Path

# Suppress HF hub symlinks warning — cache still works on Windows without Developer
# Mode, it just uses file copies instead of symlinks (slightly more disk space).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Suppress the "unauthenticated requests" banner for public models.
# Users who need a token can still set HF_TOKEN and it will be picked up automatically.
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

# Suppress tokenizers parallelism warning that appears on some Windows configs.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Filter any remaining UserWarnings from huggingface_hub about symlinks / auth.
warnings.filterwarnings(
    "ignore",
    message=r".*(symlink|unauthenticated|HF_TOKEN|huggingface_hub).*",
    category=UserWarning,
)

try:
    from flask import Flask, Response, jsonify, render_template_string, request
except ImportError:
    print("Flask is required for the Web UI. Run:  setup.bat install")
    sys.exit(1)

YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@HunterIsLive-18"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("OMNIVOICE_PORT", "8765"))

_app = Flask(__name__)
_app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB uploads

# Suppress werkzeug's per-request access log lines ("127.0.0.1 - - POST /generate 200").
# Those lines corrupt the \r-based terminal progress bar during generation.
# Startup messages ("Running on …") are printed manually in main() instead.
import logging as _logging
_logging.getLogger("werkzeug").setLevel(_logging.ERROR)

_model = None
_model_lock = threading.Lock()
_load_error: str | None = None
_load_thread: threading.Thread | None = None
_device_info: str = "detecting…"

# Speaking-style presets: OmniVoice only accepts specific instruct tokens (see README).
# We map “narrator / storyteller / …” to those tags plus decoding options (speed, steps, chunking).
SPEAKING_STYLE_PRESETS: dict[str, dict] = {
    "default": {
        "label": "Default — neutral",
        "instruct": None,
        "speed": None,
        "gen": {},
    },
    "narrator": {
        "label": "Narrator — calm documentary",
        "instruct": "middle-aged, moderate pitch",
        "speed": 0.92,
        "gen": {"guidance_scale": 2.15},
    },
    "storyteller": {
        "label": "Storyteller — warm",
        "instruct": "young adult, moderate pitch",
        "speed": 0.94,
        "gen": {"guidance_scale": 2.28, "class_temperature": 0.1},
    },
    "excited": {
        "label": "Excited / energetic",
        "instruct": "young adult, high pitch",
        "speed": 1.08,
        "gen": {"guidance_scale": 2.45, "class_temperature": 0.2},
    },
    "news": {
        "label": "News / formal reader",
        "instruct": "middle-aged, moderate pitch, american accent",
        "speed": 1.02,
        "gen": {"guidance_scale": 2.05},
    },
    "whisper": {
        "label": "Whisper / soft",
        "instruct": "whisper, low pitch",
        "speed": 0.88,
        "gen": {"guidance_scale": 2.22},
    },
    "casual": {
        "label": "Casual conversation",
        "instruct": "young adult, moderate pitch",
        "speed": 1.0,
        "gen": {"class_temperature": 0.06},
    },
}

QUALITY_PRESETS: dict[str, dict] = {
    "fast": {
        "label": "Faster preview (shorter decode)",
        "gen": {
            "num_step": 24,
            "audio_chunk_duration": 18.0,
            "audio_chunk_threshold": 40.0,
        },
    },
    "balanced": {
        "label": "Balanced",
        "gen": {},
    },
    "high": {
        "label": "Higher quality (slower, smaller chunks)",
        "gen": {
            "num_step": 46,
            "guidance_scale": 2.35,
            "audio_chunk_duration": 12.0,
            "audio_chunk_threshold": 22.0,
        },
    },
}

SPEAKING_STYLE_ORDER = tuple(SPEAKING_STYLE_PRESETS.keys())
QUALITY_ORDER = tuple(QUALITY_PRESETS.keys())

# Sound design: pick a fixed “character” (valid instruct tags). "custom" uses Speaking style + tags.
DESIGN_VOICE_PROFILES: dict[str, dict] = {
    "custom": {
        "label": "Custom — use Speaking style + extra tags",
        "instruct": None,
        "speed": None,
    },
    "vf_warm": {
        "label": "Female · warm & clear",
        "instruct": "female, young adult, moderate pitch",
        "speed": None,
    },
    "vf_story": {
        "label": "Female · soft storyteller",
        "instruct": "female, young adult, low pitch",
        "speed": 0.95,
    },
    "vm_news": {
        "label": "Male · news / formal",
        "instruct": "male, middle-aged, moderate pitch, american accent",
        "speed": 1.02,
    },
    "vm_narrator": {
        "label": "Male · deep narrator",
        "instruct": "male, middle-aged, low pitch",
        "speed": 0.92,
    },
    "vm_young": {
        "label": "Male · young energetic",
        "instruct": "male, young adult, high pitch",
        "speed": 1.06,
    },
    "neutral_auto": {
        "label": "Neutral · model picks voice",
        "instruct": None,
        "speed": None,
    },
}

DESIGN_VOICE_ORDER = tuple(DESIGN_VOICE_PROFILES.keys())


def _sanitize_preset_key(
    raw: str | None, allowed: dict[str, dict], *, fallback: str
) -> str:
    k = (raw or "").strip().lower()
    return k if k in allowed else fallback


def _resolve_style_and_quality(
    style_raw: str | None, quality_raw: str | None
) -> tuple[dict, float | None]:
    """Merge generation kwargs and optional speaking speed."""
    st = SPEAKING_STYLE_PRESETS[
        _sanitize_preset_key(style_raw, SPEAKING_STYLE_PRESETS, fallback="default")
    ]
    qu = QUALITY_PRESETS[
        _sanitize_preset_key(quality_raw, QUALITY_PRESETS, fallback="balanced")
    ]
    gen: dict = {**st["gen"], **qu["gen"]}
    speed = st.get("speed")
    return gen, speed if isinstance(speed, int | float) else None


def _normalized_gender(raw: str | None) -> str | None:
    g = (raw or "").strip().lower()
    return g if g in ("male", "female") else None


def _instruct_for_clone(style_raw: str | None, gender_raw: str | None) -> str | None:
    st = SPEAKING_STYLE_PRESETS[
        _sanitize_preset_key(style_raw, SPEAKING_STYLE_PRESETS, fallback="default")
    ]
    ins = st.get("instruct")
    base = ins if isinstance(ins, str) and ins.strip() else None
    g = _normalized_gender(gender_raw)
    parts = [p for p in (g, base) if p]
    return ", ".join(parts) if parts else None


def _instruct_for_design(
    style_raw: str | None,
    user_instruct: str | None,
    *,
    voice_profile_raw: str | None,
    gender_raw: str | None,
) -> str | None:
    vp_key = _sanitize_preset_key(
        voice_profile_raw, DESIGN_VOICE_PROFILES, fallback="custom"
    )
    vp = DESIGN_VOICE_PROFILES[vp_key]
    parts: list[str] = []

    if vp_key == "custom":
        st = SPEAKING_STYLE_PRESETS[
            _sanitize_preset_key(style_raw, SPEAKING_STYLE_PRESETS, fallback="default")
        ]
        pi = st.get("instruct")
        pi = pi if isinstance(pi, str) and pi.strip() else None
        g = _normalized_gender(gender_raw)
        if g:
            parts.append(g)
        if pi:
            parts.append(pi)
    else:
        p_ins = vp.get("instruct")
        if isinstance(p_ins, str) and p_ins.strip():
            parts.append(p_ins.strip())
        else:
            g = _normalized_gender(gender_raw)
            if g:
                parts.append(g)

    ui = (user_instruct or "").strip()
    if ui:
        parts.append(ui)
    return ", ".join(parts) if parts else None


def _design_voice_speed_override(voice_profile_raw: str | None) -> float | None:
    vp_key = _sanitize_preset_key(
        voice_profile_raw, DESIGN_VOICE_PROFILES, fallback="custom"
    )
    sp = DESIGN_VOICE_PROFILES[vp_key].get("speed")
    return float(sp) if isinstance(sp, int | float) else None


def _clone_target_duration_seconds(model, ref_text: str, text: str, ref_wav_path: str) -> float | None:
    """Align clone length with reference WAV + text ratio (fixes 6+ min bug when ref transcript is short/wrong)."""
    import torchaudio

    ref_sec: float | None = None
    try:
        w, sr = torchaudio.load(ref_wav_path)
        if w.dim() > 1 and w.size(0) > 1:
            w = w.mean(dim=0, keepdim=True)
        ref_sec = w.shape[1] / float(sr)
    except (OSError, RuntimeError):
        # torchaudio backend not available — fall back to stdlib wave (WAV only)
        try:
            import wave as _wave
            with _wave.open(ref_wav_path, "rb") as _wf:
                ref_sec = _wf.getnframes() / float(_wf.getframerate())
        except Exception:
            return None
    if ref_sec is None or ref_sec <= 0.05:
        return None

    est = model.duration_estimator
    rw = float(est.calculate_total_weight(ref_text.strip()))
    tw = float(est.calculate_total_weight(text.strip()))
    if tw <= 0:
        return None

    # If the transcript is much shorter than the audio implies, don't let ratio explode.
    min_rw = max(12.0, ref_sec * 7.0)
    rw_eff = max(rw, min_rw)
    pred_sec = ref_sec * (tw / rw_eff)
    pred_sec = max(0.35, min(pred_sec, 600.0))
    return float(pred_sec)


def _audio_tensor_to_wav_bytes(audio, sample_rate: int) -> bytes:
    """Convert a float32 audio signal to 16-bit PCM WAV bytes using stdlib wave.

    Accepts either a torch.Tensor OR a numpy.ndarray (some omnivoice versions
    return numpy from ``model.generate``). Works with no external codec
    dependencies. Shape can be (channels, samples) or (samples,) — mixed to mono.
    """
    import io
    import wave as _wave
    import numpy as np

    try:
        import torch
        is_torch_tensor = isinstance(audio, torch.Tensor)
    except ImportError:
        is_torch_tensor = False

    if is_torch_tensor:
        t = audio.detach()
        if t.dim() > 1:
            t = t.mean(dim=0) if t.size(0) > 1 else t.squeeze(0)
        arr = t.clamp(-1.0, 1.0).cpu().numpy()
    else:
        arr = np.asarray(audio)
        if arr.ndim > 1:
            arr = arr.mean(axis=0) if arr.shape[0] > 1 else arr.squeeze(0)
        arr = np.clip(arr, -1.0, 1.0)

    pcm = (arr * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class _GenProgress:
    """Live terminal progress bar while model.generate() runs.

    Usage::
        with _GenProgress("Voice Clone", est_sec=14.0):
            audio = model.generate(...)
    """

    _SPIN = ["|", "/", "-", "\\"]
    _BAR_W = 22

    def __init__(self, mode: str, est_sec: float | None = None):
        self._mode = mode
        self._est = est_sec
        self._t0 = 0.0
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._t0 = time.time()
        est_str = f"  (est. ~{self._est:.0f}s)" if self._est else ""
        print(f"[OmniVoice] Generating {self._mode}…{est_str}", flush=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, *_):
        self._done.set()
        self._thread.join(timeout=2.0)
        elapsed = time.time() - self._t0
        label = "done" if exc_type is None else "FAILED"
        # Overwrite the last spinner line with the final result
        print(
            f"\r[OmniVoice] {self._mode} {label} in {elapsed:.1f}s" + " " * 30,
            flush=True,
        )

    def _loop(self):
        idx = 0
        while not self._done.wait(0.3):
            elapsed = time.time() - self._t0
            spin = self._SPIN[idx % len(self._SPIN)]
            if self._est and self._est > 1.0:
                frac = min(elapsed / self._est, 0.99)
                filled = int(frac * self._BAR_W)
                bar = "#" * filled + "." * (self._BAR_W - filled)
                pct = int(frac * 100)
                line = (
                    f"\r[OmniVoice] {spin} [{bar}] {pct:2d}%  {elapsed:5.1f}s"
                )
            else:
                line = f"\r[OmniVoice] {spin} {elapsed:5.1f}s"
            print(line, end="", flush=True)
            idx += 1


def _get_device_dtype():
    global _device_info
    import torch

    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        cuda_ver = torch.version.cuda or "unknown"
        _device_info = f"GPU: {gpu_name} | CUDA {cuda_ver}"
        print(f"[OmniVoice] {_device_info}", flush=True)
        return "cuda:0", torch.float16

    # NVIDIA GPU detected by nvidia-smi but CUDA not usable — give actionable hint
    try:
        r = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            m = re.search(r"CUDA Version: (\d+\.\d+)", r.stdout)
            drv_cuda = m.group(1) if m else "unknown"
            _device_info = f"CPU (NVIDIA driver CUDA {drv_cuda} found but torch CUDA unavailable)"
            print(
                f"\n[OmniVoice] WARNING: NVIDIA GPU found (driver supports CUDA {drv_cuda})"
                f" but torch.cuda.is_available() = False.\n"
                f"  PyTorch was likely installed without CUDA support.\n"
                f"  Fix: open setup.bat and pick the matching CUDA build:\n"
                f"    driver CUDA >= 12.8  →  option 8 (CUDA 12.8)\n"
                f"    driver CUDA >= 12.4  →  option C (CUDA 12.4)\n"
                f"    driver CUDA >= 12.1  →  option B (CUDA 12.1)\n"
                f"    driver CUDA >= 11.8  →  option A (CUDA 11.8)\n"
                f"  Check your driver:  run  nvidia-smi  and look for 'CUDA Version'.\n",
                flush=True,
            )
        else:
            _device_info = "CPU (no NVIDIA GPU detected)"
            print("[OmniVoice] Running on CPU — no NVIDIA GPU detected.", flush=True)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _device_info = "CPU"
        print("[OmniVoice] Running on CPU.", flush=True)

    return "cpu", torch.float32


def _load_model_blocking() -> None:
    """Load weights once (runs in background thread)."""
    global _model, _load_error
    import traceback

    with _model_lock:
        if _model is not None:
            return
        try:
            from omnivoice import OmniVoice

            device, dtype = _get_device_dtype()
            _model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice",
                device_map=device,
                dtype=dtype,
            )
            _load_error = None
        except Exception as e:  # noqa: BLE001 — show error in UI
            tb = traceback.format_exc()
            print(tb, file=sys.stderr, flush=True)
            msg = str(e) + "\n\n--- Traceback (full log in this console window) ---\n" + tb
            if "null bytes" in str(e).lower():
                msg += (
                    "\n--- Fixes for null bytes (often after PC crash) ---\n"
                    "Open setup.bat and use the menu, or from cmd:\n"
                    "  setup.bat fixhttpx   |  setup.bat fixaccelerate  |  setup.bat deeprepair\n"
                    "Last resort: delete the .venv folder, then setup.bat install\n"
                )
            _load_error = msg[:20000]
            _model = None


def _ensure_load_started(force: bool = False) -> None:
    global _load_thread, _load_error
    if _load_thread is not None and _load_thread.is_alive():
        return
    if _model is not None:
        return
    if _load_error is not None and not force:
        return
    if force:
        _load_error = None
    _load_thread = threading.Thread(target=_load_model_blocking, daemon=True)
    _load_thread.start()


PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OmniVoice WebUI — HunterIsLive</title>
  <style>
    :root {
      --bg: #0c0e14;
      --surface: #141824;
      --border: #252a3a;
      --text: #e8eaef;
      --muted: #8b92a8;
      --accent: #6c9eff;
      --accent2: #a78bfa;
      --yt: #ff0033;
      --ok: #34d399;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, #1a1f35 0%, transparent 55%),
                  radial-gradient(900px 500px at 100% 0%, #251a35 0%, transparent 50%),
                  var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .wrap { max-width: 720px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
    header {
      text-align: center;
      padding: 1.25rem 0 1.5rem;
      border-bottom: 1px solid var(--border);
      margin-bottom: 1.5rem;
    }
    .badge {
      display: inline-block;
      font-size: 0.7rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 0.35rem;
    }
    h1 {
      font-size: 1.75rem;
      font-weight: 700;
      margin: 0 0 0.25rem;
      background: linear-gradient(120deg, var(--accent), var(--accent2));
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }
    .byline { color: var(--muted); font-size: 0.95rem; margin: 0; }
    .yt-banner {
      margin-top: 1.25rem;
      padding: 1rem 1.15rem;
      background: linear-gradient(135deg, #2a1218 0%, var(--surface) 100%);
      border: 1px solid #3d1f28;
      border-radius: 12px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 0.75rem 1rem;
    }
    .yt-banner p { margin: 0; font-size: 0.9rem; color: var(--text); }
    .yt-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      background: var(--yt);
      color: #fff !important;
      font-weight: 600;
      padding: 0.55rem 1.1rem;
      border-radius: 999px;
      text-decoration: none !important;
      font-size: 0.9rem;
      box-shadow: 0 4px 20px rgba(255, 0, 51, 0.35);
    }
    .yt-btn:hover { filter: brightness(1.08); text-decoration: none !important; }
    .yt-icon { width: 1.25rem; height: 1.25rem; fill: currentColor; }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1.25rem 1.35rem;
      margin-bottom: 1.25rem;
    }
    label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.35rem; }
    input[type="text"], textarea, select {
      width: 100%;
      padding: 0.65rem 0.75rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #0a0c12;
      color: var(--text);
      font: inherit;
    }
    select { cursor: pointer; }
    textarea { min-height: 100px; resize: vertical; }
    input[type="file"] {
      width: 100%;
      padding: 0.5rem 0;
      font-size: 0.85rem;
      color: var(--muted);
    }
    .row { margin-bottom: 1rem; }
    .row:last-child { margin-bottom: 0; }
    button[type="submit"] {
      width: 100%;
      margin-top: 0.5rem;
      padding: 0.85rem 1rem;
      font-size: 1rem;
      font-weight: 600;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      background: linear-gradient(120deg, var(--accent), #4f7ae8);
      color: #fff;
    }
    button[type="submit"]:disabled { opacity: 0.5; cursor: not-allowed; }
    .err {
      background: #2a1518;
      border: 1px solid #5c2a32;
      color: #fca5a5;
      padding: 0.85rem 1rem;
      border-radius: 10px;
      margin-bottom: 1rem;
      font-size: 0.9rem;
      white-space: pre-wrap;
    }
    .hint { font-size: 0.8rem; color: var(--muted); margin-top: 0.35rem; }
    footer {
      text-align: center;
      margin-top: 2rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 0.85rem;
    }
    .status { font-size: 0.85rem; color: var(--ok); margin-top: 0.75rem; }
    audio { width: 100%; margin-top: 1rem; border-radius: 8px; }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      justify-content: center;
      margin: 0 0 1.25rem;
    }
    .tabs a {
      padding: 0.45rem 1rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 0.9rem;
      font-weight: 500;
    }
    .tabs a:hover { color: var(--text); border-color: var(--accent); }
    .tabs a.active {
      color: #fff;
      background: linear-gradient(120deg, var(--accent), #4f7ae8);
      border-color: transparent;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="badge">{% if page == 'clone' %}Local TTS · Zero-shot voice clone{% else %}Voice design · No reference audio{% endif %}</div>
      <h1>OmniVoice WebUI</h1>
      <p class="byline">Interface &amp; packaging by <strong>HunterIsLive</strong></p>
      <div class="yt-banner">
        <p>More tutorials &amp; AI tools on my channel — subscribe for updates.</p>
        <a class="yt-btn" href="{{ yt_url }}" target="_blank" rel="noopener noreferrer">
          <svg class="yt-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M23.5 6.2c-.3-1.1-1.1-1.9-2.2-2.2C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.3.5C1.6 4.3.8 5.1.5 6.2 0 8 0 12 0 12s0 4 .5 5.8c.3 1.1 1.1 1.9 2.2 2.2 1.8.5 9.3.5 9.3.5s7.5 0 9.3-.5c1.1-.3 1.9-1.1 2.2-2.2.5-1.8.5-5.8.5-5.8s0-4-.5-5.8zM9.5 15.5v-7l6 3.5-6 3.5z"/></svg>
          YouTube — HunterIsLive
        </a>
      </div>
    </header>

    <nav class="tabs" aria-label="Main pages">
      <a href="/" {% if page == 'clone' %}class="active" aria-current="page"{% endif %}>Voice clone</a>
      <a href="/sound-design" {% if page == 'design' %}class="active" aria-current="page"{% endif %}>Sound design</a>
    </nav>

    {% if load_error %}
    <div class="err">
      <p><strong>Model failed to load.</strong> Check the black console for the full traceback. Then open <strong>setup.bat</strong> and choose <strong>Deep repair</strong> (option 6), or check GPU drivers / HF_TOKEN / network.</p>
      <pre style="white-space:pre-wrap;font-size:0.75rem;max-height:42vh;overflow:auto;margin:0.75rem 0">{{ load_error }}</pre>
      <button type="button" id="retry-load-btn" style="padding:0.55rem 1rem;cursor:pointer;border-radius:8px;border:1px solid #5c2a32;background:#2a1518;color:#fca5a5;font-weight:600">Retry loading model</button>
    </div>
    <script>
      document.getElementById("retry-load-btn")?.addEventListener("click", async function() {
        this.disabled = true;
        await fetch("/api/retry-load", { method: "POST" });
        location.reload();
      });
    </script>
    {% elif not model_ready %}
    <div class="card" id="loader-card">
      <p class="status" id="loader-msg">Loading OmniVoice model… first run may download weights. This can take several minutes.</p>
      <p class="hint" id="device-hint">Device: <span id="device-label">{{ device_info }}</span></p>
      <p class="hint">You can subscribe on YouTube while you wait — link above.</p>
    </div>
    {% endif %}
    {% if model_ready and not load_error %}
    <p class="hint" style="text-align:center;margin-bottom:0.5rem">Device: {{ device_info }}</p>
    {% endif %}

    <div class="card" id="main-card" {% if not model_ready or load_error %}style="display:none"{% endif %}>
      {% if page == 'clone' %}
      <form id="gen-form" method="post" action="/generate" enctype="multipart/form-data">
        <div class="row">
          <label for="ref_audio">Reference audio (WAV — short clip of the voice to clone)</label>
          <input id="ref_audio" name="ref_audio" type="file" accept=".wav,audio/wav,audio/x-wav" required />
          <p class="hint">Use a clear recording; match the transcription below.</p>
        </div>
        <div class="row">
          <label for="ref_text">Reference transcription</label>
          <input id="ref_text" name="ref_text" type="text"
            placeholder="Exact words spoken in the WAV — wrong or very short text here makes output too long and messy" />
        </div>
        <div class="row">
          <label for="voice_gender_clone">Voice gender</label>
          <select id="voice_gender_clone" name="voice_gender" aria-describedby="hint-gender-clone">
            <option value="" selected>Unspecified</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
          </select>
          <p class="hint" id="hint-gender-clone">Optional tag merged with speaking style (official model tags).</p>
        </div>
        <div class="row">
          <label for="speaking_style">Speaking style</label>
          <select id="speaking_style" name="speaking_style" aria-describedby="hint-speaking-clone">
            {% for key in speaking_keys %}
            <option value="{{ key }}">{{ speaking_presets[key].label }}</option>
            {% endfor %}
          </select>
          <p class="hint" id="hint-speaking-clone">Narrator, storyteller, etc. use official voice tags plus pacing — helps long lines sound more controlled.</p>
        </div>
        <div class="row">
          <label for="quality_preset_clone">Generation quality</label>
          <select id="quality_preset_clone" name="quality_preset" aria-describedby="hint-quality-clone">
            {% for key in quality_keys %}
            <option value="{{ key }}"{% if key == 'balanced' %} selected{% endif %}>{{ quality_presets[key].label }}</option>
            {% endfor %}
          </select>
          <p class="hint" id="hint-quality-clone">Higher quality uses more steps and smaller audio chunks (better for long text, slower).</p>
        </div>
        <div class="row">
          <label for="text">Text to speak</label>
          <textarea id="text" name="text" required
            placeholder="Type what you want the cloned voice to say...">Hello, this is a test of zero-shot voice cloning.</textarea>
        </div>
        <button type="submit" id="submit-btn" {% if load_error or not model_ready %}disabled{% endif %}>Generate speech</button>
        <p class="hint">First generation may take longer while the model warms up. Runs on your machine only.</p>
      </form>
      {% else %}
      <form id="design-form" method="post" action="/generate-design">
        <div class="row">
          <label for="design_voice">Voice character</label>
          <select id="design_voice" name="design_voice" aria-describedby="hint-design-voice">
            {% for key in design_voice_keys %}
            <option value="{{ key }}">{{ design_voice_presets[key].label }}</option>
            {% endfor %}
          </select>
          <p class="hint" id="hint-design-voice">Pick a preset voice, or Custom to use Speaking style + gender below. Some presets already include male/female.</p>
        </div>
        <div class="row">
          <label for="voice_gender_design">Voice gender</label>
          <select id="voice_gender_design" name="voice_gender" aria-describedby="hint-gender-design">
            <option value="" selected>Unspecified</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
          </select>
          <p class="hint" id="hint-gender-design">Used when Voice character is <strong>Custom</strong> or <strong>Neutral</strong>. Ignored for fixed male/female presets to avoid tag conflicts.</p>
        </div>
        <div class="row">
          <label for="speaking_style_design">Speaking style</label>
          <select id="speaking_style_design" name="speaking_style" aria-describedby="hint-speaking-design">
            {% for key in speaking_keys %}
            <option value="{{ key }}">{{ speaking_presets[key].label }}</option>
            {% endfor %}
          </select>
          <p class="hint" id="hint-speaking-design">Used when Voice character is <strong>Custom</strong> (narrator, excited, …). Preset voices use their own tags instead.</p>
        </div>
        <div class="row">
          <label for="quality_preset_design">Generation quality</label>
          <select id="quality_preset_design" name="quality_preset" aria-describedby="hint-quality-design">
            {% for key in quality_keys %}
            <option value="{{ key }}"{% if key == 'balanced' %} selected{% endif %}>{{ quality_presets[key].label }}</option>
            {% endfor %}
          </select>
          <p class="hint" id="hint-quality-design">Use Higher quality for long paragraphs.</p>
        </div>
        <div class="row">
          <label for="design-text">Text to speak</label>
          <textarea id="design-text" name="text" required rows="5"
            placeholder="What you want spoken — any supported language.">Hello, this is voice design mode without a reference recording.</textarea>
        </div>
        <div class="row">
          <label for="instruct">Extra voice tags (optional)</label>
          <input id="instruct" name="instruct" type="text"
            placeholder="e.g. british accent — added on top of the speaking style" />
          <p class="hint">Official tags only (gender, age, pitch, whisper, accent…). Leave empty to use only the dropdown. Conflicting tags may error.</p>
        </div>
        <div class="row">
          <label for="language">Language (optional)</label>
          <input id="language" name="language" type="text" placeholder="English, Hindi, en, hi — or leave empty" />
          <p class="hint">Helps quality when set; empty uses language-agnostic mode.</p>
        </div>
        <button type="submit" id="submit-btn" {% if load_error or not model_ready %}disabled{% endif %}>Generate speech</button>
        <p class="hint">No WAV upload needed — describes the voice in text instead of cloning a sample.</p>
      </form>
      {% endif %}
      <div id="result"></div>
    </div>

    <footer>
      <p>OmniVoice model: <a href="https://huggingface.co/k2-fsa/OmniVoice" target="_blank" rel="noopener">k2-fsa/OmniVoice</a></p>
      <p>WebUI by HunterIsLive — <a href="{{ yt_url }}" target="_blank" rel="noopener noreferrer">youtube.com/@HunterIsLive-18</a></p>
    </footer>
  </div>
  <script>
    const form = document.getElementById("gen-form") || document.getElementById("design-form");
    const btn = document.getElementById("submit-btn");
    const result = document.getElementById("result");
    const mainCard = document.getElementById("main-card");
    const loaderCard = document.getElementById("loader-card");

    async function pollStatus() {
      if (!loaderCard || mainCard.style.display !== "none") return;
      try {
        const r = await fetch("/api/status");
        const j = await r.json();
        if (j.error) {
          location.reload();
          return;
        }
        const lbl = document.getElementById("device-label");
        if (lbl && j.device) lbl.textContent = j.device;
        if (j.ready) {
          loaderCard.style.display = "none";
          mainCard.style.display = "block";
          btn.disabled = false;
        }
      } catch (_) { /* ignore */ }
    }
    if (loaderCard) setInterval(pollStatus, 2000);

    if (form) form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (btn.disabled) return;
      btn.disabled = true;
      result.innerHTML = "<p class=\\"status\\">Generating… this may take a minute.</p>";
      try {
        const fd = new FormData(form);
        const action = form.getAttribute("action") || "/generate";
        const res = await fetch(action, { method: "POST", body: fd });
        if (!res.ok) {
          const t = await res.text();
          result.innerHTML = "<div class=\\"err\\">" + (t || res.statusText) + "</div>";
          btn.disabled = false;
          return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        result.innerHTML = "<p class=\\"status\\">Done — play or save below.</p><audio controls src=\\"" + url + "\\"></audio>";
      } catch (err) {
        result.innerHTML = "<div class=\\"err\\">" + err.message + "</div>";
      }
      btn.disabled = false;
    });
  </script>
</body>
</html>
"""


def _render_ui(page: str):
    _ensure_load_started()
    return render_template_string(
        PAGE_HTML,
        page=page,
        yt_url=YOUTUBE_CHANNEL_URL,
        load_error=_load_error,
        model_ready=_model is not None,
        device_info=_device_info,
        speaking_keys=SPEAKING_STYLE_ORDER,
        quality_keys=QUALITY_ORDER,
        speaking_presets=SPEAKING_STYLE_PRESETS,
        quality_presets=QUALITY_PRESETS,
        design_voice_keys=DESIGN_VOICE_ORDER,
        design_voice_presets=DESIGN_VOICE_PROFILES,
    )


@_app.route("/")
def index():
    return _render_ui("clone")


@_app.route("/sound-design")
def sound_design():
    return _render_ui("design")


@_app.route("/api/status")
def api_status():
    _ensure_load_started()
    return jsonify(
        ready=_model is not None,
        error=bool(_load_error),
        device=_device_info,
    )


@_app.route("/api/retry-load", methods=["POST"])
def api_retry_load():
    """Clear last load error and start a fresh background load (after setup.bat repairs)."""
    global _load_thread
    if _load_thread is not None and _load_thread.is_alive():
        return jsonify(ok=False, message="Load already in progress"), 409
    _ensure_load_started(force=True)
    return jsonify(ok=True)


@_app.route("/generate", methods=["POST"])
def generate():
    _ensure_load_started()
    if _load_error:
        return Response(_load_error, status=503, mimetype="text/plain")
    if _model is None:
        return Response(
            "Model is still loading. Wait a few seconds and try again.",
            status=503,
            mimetype="text/plain",
        )

    ref_file = request.files.get("ref_audio")
    if not ref_file or not ref_file.filename:
        return Response("Missing reference audio file.", status=400, mimetype="text/plain")

    text = (request.form.get("text") or "").strip()
    ref_text = (request.form.get("ref_text") or "").strip()
    if not text:
        return Response("Missing text to speak.", status=400, mimetype="text/plain")
    if not ref_text:
        return Response(
            "Reference transcription is required — type the exact words spoken in the WAV. "
            "Wrong or missing text makes cloning much longer and worse.",
            status=400,
            mimetype="text/plain",
        )

    suffix = Path(ref_file.filename).suffix.lower() or ".wav"
    if suffix not in (".wav", ".wave"):
        return Response("Please upload a WAV file.", status=400, mimetype="text/plain")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = tmp.name
    tmp.close()
    gen_kw, speed = _resolve_style_and_quality(
        request.form.get("speaking_style"),
        request.form.get("quality_preset"),
    )
    clone_instruct = _instruct_for_clone(
        request.form.get("speaking_style"),
        request.form.get("voice_gender"),
    )

    try:
        ref_file.save(tmp_path)
        call_kw: dict = {
            "text": text,
            "ref_audio": tmp_path,
            "ref_text": ref_text,
            **gen_kw,
        }
        if clone_instruct:
            call_kw["instruct"] = clone_instruct
        dur = _clone_target_duration_seconds(_model, ref_text, text, tmp_path)
        if dur is not None:
            call_kw["duration"] = dur
        elif speed is not None:
            call_kw["speed"] = speed

        preview = text[:70].replace("\n", " ") + ("…" if len(text) > 70 else "")
        print(f'[OmniVoice] Text: "{preview}"', flush=True)
        try:
            with _GenProgress("Voice Clone", est_sec=dur):
                with _model_lock:
                    audio = _model.generate(**call_kw)
        except ValueError as e:
            return Response(
                "Invalid style for this mode:\n" + str(e),
                status=400,
                mimetype="text/plain",
            )
        wav_bytes = _audio_tensor_to_wav_bytes(audio[0], 24000)
        return Response(
            wav_bytes,
            mimetype="audio/wav",
            headers={"Content-Disposition": "inline; filename=omnivoice_out.wav"},
        )
    except Exception as e:  # noqa: BLE001
        return Response(str(e), status=500, mimetype="text/plain")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@_app.route("/generate-design", methods=["POST"])
def generate_design():
    """Voice design / auto voice: no reference audio (OmniVoice ``instruct`` mode)."""
    _ensure_load_started()
    if _load_error:
        return Response(_load_error, status=503, mimetype="text/plain")
    if _model is None:
        return Response(
            "Model is still loading. Wait a few seconds and try again.",
            status=503,
            mimetype="text/plain",
        )

    text = (request.form.get("text") or "").strip()
    if not text:
        return Response("Missing text to speak.", status=400, mimetype="text/plain")

    instruct_combined = _instruct_for_design(
        request.form.get("speaking_style"),
        request.form.get("instruct"),
        voice_profile_raw=request.form.get("design_voice"),
        gender_raw=request.form.get("voice_gender"),
    )

    lang_raw = (request.form.get("language") or "").strip()
    language = None
    if lang_raw and lang_raw.lower() not in ("auto", "none", "default"):
        language = lang_raw

    gen_kw, speed_style = _resolve_style_and_quality(
        request.form.get("speaking_style"),
        request.form.get("quality_preset"),
    )
    speed_prof = _design_voice_speed_override(request.form.get("design_voice"))
    speed = speed_prof if speed_prof is not None else speed_style

    call_kw: dict = {"text": text, **gen_kw}
    if instruct_combined:
        call_kw["instruct"] = instruct_combined
    if language:
        call_kw["language"] = language
    if speed is not None:
        call_kw["speed"] = speed

    preview = text[:70].replace("\n", " ") + ("…" if len(text) > 70 else "")
    print(f'[OmniVoice] Text: "{preview}"', flush=True)
    try:
        try:
            with _GenProgress("Voice Design"):
                with _model_lock:
                    audio = _model.generate(**call_kw)
        except ValueError as e:
            return Response(
                "Invalid voice style tags:\n" + str(e),
                status=400,
                mimetype="text/plain",
            )
        wav_bytes = _audio_tensor_to_wav_bytes(audio[0], 24000)
        return Response(
            wav_bytes,
            mimetype="audio/wav",
            headers={"Content-Disposition": "inline; filename=omnivoice_design.wav"},
        )
    except Exception as e:  # noqa: BLE001
        return Response(str(e), status=500, mimetype="text/plain")


def _open_browser_later():
    time.sleep(1.25)
    webbrowser.open(f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/")


def main() -> int:
    _ensure_load_started()
    print(f"OmniVoice WebUI — http://{DEFAULT_HOST}:{DEFAULT_PORT}/")
    print("Press Ctrl+C to stop.")
    threading.Thread(target=_open_browser_later, daemon=True).start()
    _app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
