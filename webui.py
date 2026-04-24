"""
OmniVoice local Web UI — opens in your browser when you run run.bat.

VRAM (6–8 GB GPUs): Whisper ASR auto-loads on CPU so TTS keeps GPU memory.
  OMNIVOICE_WHISPER_DEVICE=cpu|cuda  — override auto
  OMNIVOICE_WHISPER_AUTO_CPU_VRAM_MIB=7800  — auto-CPU below this MiB total VRAM
"""
from __future__ import annotations

# Optional: load a project ``.env`` (API keys, OMNIVOICE_PORT, etc.). Works without
# ``python-dotenv``; install it with: pip install python-dotenv  or  setup.bat install
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import json
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

# Web UI “update available” banner — same repo as setup.bat / update.bat
PROJECT_ROOT = Path(__file__).resolve().parent
GITHUB_UPDATE_OWNER = "HunterisLive-1"
GITHUB_UPDATE_REPO = "omni-voice"
GITHUB_UPDATE_BRANCH = "main"

# Local data: reference transcript cache (SHA256 → text) and optional design voice lock WAV.
WEBUI_DATA_DIR = Path(__file__).resolve().parent / "webui_data"
# Voice clone: user reference WAV must not exceed this (avoids long-clip / pydub issues).
REF_AUDIO_MAX_DURATION_SEC = 15.0
REF_MIN_WARN_SEC = 3.0
DESIGN_LOCK_WAV = WEBUI_DATA_DIR / "design_voice_lock.wav"
WHISPER_MODEL_FILE = WEBUI_DATA_DIR / "whisper_model.txt"

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
_omnivoice_audio_utils_patched: bool = False
_omnivoice_whisper_device_patched: bool = False

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

# ``num_step`` = diffusion steps (default in omnivoice is 32). Official README:
# use 16 for faster inference; RTF ~0.025 in papers is H20 + batch infer — not a
# single RTX 3050 request. See https://github.com/k2-fsa/OmniVoice/issues/7
QUALITY_PRESETS: dict[str, dict] = {
    "fast": {
        "label": "Faster preview (recommended on 6 GB GPUs)",
        "gen": {
            "num_step": 16,
            "audio_chunk_duration": 18.0,
            "audio_chunk_threshold": 40.0,
        },
    },
    "balanced": {
        "label": "Balanced (default 32 steps)",
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


def _form_checkbox_on(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "on", "true", "yes")


def _normalize_chunking_text(text: str) -> str:
    """Map Hindi/Sanskrit danda to a period so ``chunk_text_punctuation`` can split."""
    if not text:
        return text
    t = text.replace("\u0965", ". ")  # ॥
    t = t.replace("\u0964", ". ")  # ।
    return t


def _is_hindi_language_hint(language: str | None) -> bool:
    if not language:
        return False
    s = language.strip().lower()
    return "hindi" in s or s in ("hi", "hin")


def _ref_cache_path(content_hash: str) -> Path:
    d = WEBUI_DATA_DIR / "ref_transcript_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{content_hash}.txt"


def _ref_cache_read(content_hash: str) -> str | None:
    p = _ref_cache_path(content_hash)
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _ref_cache_write(content_hash: str, transcript: str) -> None:
    try:
        _ref_cache_path(content_hash).write_text(transcript.strip(), encoding="utf-8")
    except OSError:
        pass


def _ref_cache_write_dual(raw_hash: str, proc_hash: str, transcript: str) -> None:
    """Persist transcript under both raw and processed WAV hashes (same clip, two keys)."""
    tx = transcript.strip()
    if not tx:
        return
    _ref_cache_write(raw_hash, tx)
    if proc_hash != raw_hash:
        _ref_cache_write(proc_hash, tx)


def _unload_asr_if_loaded(model) -> None:
    """Drop Whisper pipeline so TTS can use more VRAM (e.g. RTX 3050 6 GB). Safe to call often."""
    if getattr(model, "_asr_pipe", None) is None:
        return
    try:
        pipe = model._asr_pipe
        del pipe
    except Exception:
        pass
    model._asr_pipe = None
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    print("[OmniVoice] Whisper ASR unloaded; GPU memory freed for voice generation.", flush=True)


def _sha256_file(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _reference_wav_duration_sec(path: str) -> float | None:
    """Audio length in seconds (``wave`` first, then ``torchaudio``)."""
    import wave

    try:
        with wave.open(path, "rb") as wf:
            r = wf.getframerate()
            n = wf.getnframes()
            if r > 0 and n >= 0:
                return n / float(r)
    except (wave.Error, OSError, EOFError):
        pass
    try:
        import torchaudio

        w, sr = torchaudio.load(path)
        if sr <= 0:
            return None
        return w.shape[-1] / float(sr)
    except (RuntimeError, OSError):
        return None


def _reject_clone_reference_if_too_long(path: str) -> Response | None:
    """Return a 400 :class:`~flask.Response` if clone reference is too long."""
    d = _reference_wav_duration_sec(path)
    if d is None:
        return Response(
            "Could not read the reference WAV duration. Use a standard PCM .wav file.\n\n"
            "रेफरेंस WAV की लंबाई नहीं पढ़ी जा सकी — कृपया सामान्य PCM .wav उपयोग करें।",
            status=400,
            mimetype="text/plain",
        )
    if d > REF_AUDIO_MAX_DURATION_SEC:
        lim = REF_AUDIO_MAX_DURATION_SEC
        return Response(
            f"Reference audio is too long ({d:.1f}s). Maximum allowed is {lim:g} seconds.\n"
            f"This Web UI only accepts short clips so voice cloning stays reliable.\n"
            f"Trim your WAV to {lim:g}s or less, then upload again.\n\n"
            f"आपका रेफरेंस ऑडियो बहुत लंबा है ({d:.1f} सेकंड)। अधिकतम {lim:g} सेकंड की क्लिप अपलोड करें।\n"
            f"छोटा WAV ट्रिम करके फिर से चुनें।",
            status=400,
            mimetype="text/plain",
        )
    return None


def _whisper_model_name() -> str:
    """HF model id for reference auto-transcribe (multilingual Whisper; supports Hindi)."""
    if WHISPER_MODEL_FILE.is_file():
        try:
            for line in WHISPER_MODEL_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
        except OSError:
            pass
    env = (os.environ.get("OMNIVOICE_WHISPER_MODEL") or "").strip()
    if env:
        return env
    return "openai/whisper-large-v3-turbo"


def _ensure_whisper_pipeline(model) -> None:
    """Load Whisper ASR once; uses ``webui_data/whisper_model.txt`` or ``OMNIVOICE_WHISPER_MODEL``."""
    if getattr(model, "_asr_pipe", None) is not None:
        return
    mid = _whisper_model_name()
    print(f"[OmniVoice] Loading Whisper ASR: {mid}", flush=True)
    model.load_asr_model(model_name=mid)


def _patch_omnivoice_audio_utils() -> None:
    """Work around ``'Tensor' object has no attribute 'astype'`` in omnivoice.

    Upstream ``omnivoice.utils.audio`` uses ``.astype`` after NumPy ops that can
    return a PyTorch ``Tensor`` on some CPU stacks (NumPy↔torch ufunc interop).
    Affected paths: ``tensor_to_audiosegment``, ``audiosegment_to_tensor``, and
    the pydub fallback in ``load_audio``.
    """
    global _omnivoice_audio_utils_patched
    if _omnivoice_audio_utils_patched:
        return
    import numpy as np
    import torch
    import torchaudio
    from pydub import AudioSegment

    import omnivoice.utils.audio as ov_audio

    def tensor_to_audiosegment(tensor: torch.Tensor, sample_rate: int):
        if not isinstance(tensor, torch.Tensor):
            raise TypeError("tensor_to_audiosegment expects a torch.Tensor")
        buf = tensor.detach().cpu().float().contiguous().numpy()
        audio_np = np.asarray(buf, dtype=np.float64)
        audio_np = np.clip(
            np.rint(audio_np * 32768.0),
            -32768,
            32767,
        ).astype(np.int16)
        if audio_np.shape[0] > 1:
            audio_np = audio_np.transpose(1, 0).flatten()
        audio_bytes = audio_np.tobytes()
        return AudioSegment(
            data=audio_bytes,
            sample_width=2,
            frame_rate=sample_rate,
            channels=tensor.shape[0],
        )

    def audiosegment_to_tensor(aseg: AudioSegment) -> torch.Tensor:
        raw = np.array(aseg.get_array_of_samples(), dtype=np.float64, copy=True)
        audio_data = (raw / 32768.0).astype(np.float32)
        if aseg.channels == 1:
            return torch.from_numpy(audio_data).unsqueeze(0)
        return torch.from_numpy(audio_data.reshape(-1, aseg.channels).T)

    def load_audio(audio_path: str, sampling_rate: int) -> torch.Tensor:
        try:
            waveform, prompt_sampling_rate = torchaudio.load(
                audio_path, backend="soundfile"
            )
        except (RuntimeError, OSError):
            aseg = AudioSegment.from_file(audio_path)
            raw = np.array(aseg.get_array_of_samples(), dtype=np.float64, copy=True)
            audio_data = (raw / 32768.0).astype(np.float32)
            if aseg.channels == 1:
                waveform = torch.from_numpy(audio_data).unsqueeze(0)
            else:
                waveform = torch.from_numpy(
                    audio_data.reshape(-1, aseg.channels).T
                )
            prompt_sampling_rate = aseg.frame_rate

        if prompt_sampling_rate != sampling_rate:
            waveform = torchaudio.functional.resample(
                waveform,
                orig_freq=prompt_sampling_rate,
                new_freq=sampling_rate,
            )
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        return waveform

    ov_audio.tensor_to_audiosegment = tensor_to_audiosegment  # type: ignore[method-assign]
    ov_audio.audiosegment_to_tensor = audiosegment_to_tensor  # type: ignore[method-assign]
    ov_audio.load_audio = load_audio  # type: ignore[method-assign]
    _omnivoice_audio_utils_patched = True
    print(
        "[OmniVoice] Patched omnivoice.utils.audio (tensor<->pydub) for CPU NumPy/PyTorch interop.",
        flush=True,
    )


def _preprocess_reference_wav(
    in_path: str, out_path: str, target_sr: int
) -> tuple[list[str], float]:
    """Mono, resample to model rate. Returns (warnings, duration sec).

    Long clips are rejected at upload for voice clone (see
    :data:`REF_AUDIO_MAX_DURATION_SEC`); we do not trim here so pydub silence
    paths are avoided for reference preprocessing.
    """
    import torchaudio

    warnings: list[str] = []
    w, sr = torchaudio.load(in_path)
    if w.dim() == 1:
        w = w.unsqueeze(0)
    if w.size(0) > 1:
        w = w.mean(dim=0, keepdim=True)
    if sr != target_sr:
        w = torchaudio.functional.resample(w, sr, target_sr)
    dur = w.shape[1] / float(target_sr)
    if dur < REF_MIN_WARN_SEC:
        warnings.append(
            f"Reference audio is only {dur:.1f}s; 3–15s of clear speech is recommended."
        )
    torchaudio.save(out_path, w, target_sr)
    return warnings, dur


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


def _wall_clock_estimate_for_progress(
    predicted_output_sec: float | None,
    device_info: str,
    *,
    num_step: int | None = None,
) -> float | None:
    """Turn predicted *WAV length* (sec) into a rough wall time for the progress bar."""
    if predicted_output_sec is None or predicted_output_sec < 0.05:
        return None
    p = float(predicted_output_sec)
    di = (device_info or "").lower()
    if "cpu" in di and "cuda" not in di:
        mult = 22.0
    else:
        mult = 6.0
    w = max(40.0, p * mult)
    ns = int(num_step) if num_step is not None else 32
    if ns > 0:
        w *= float(ns) / 32.0
    return min(w, 1200.0)


def _unwrap_single_container(x, max_depth: int = 8) -> object:
    """Unwrap ``[[tensor]]`` / ``(tensor,)`` so we operate on the inner segment."""
    t = x
    d = 0
    while d < max_depth and isinstance(t, (list, tuple)) and len(t) == 1:
        t = t[0]
        d += 1
    return t


def _is_torchish(x) -> bool:
    """True for PyTorch tensors (any ``torch`` build) and similar."""
    if x is None:
        return False
    name = type(x).__name__
    if name in ("Tensor", "Parameter", "BatchedTensor") or name.endswith("Tensor"):
        return True
    module = getattr(type(x), "__module__", "") or ""
    if module.startswith("torch"):
        return True
    return all(hasattr(x, a) for a in ("detach", "cpu", "numpy"))


def _torchish_to_numpy_float32_1d(t) -> "np.ndarray":
    """Convert a single tensor to 1D float32 numpy in ~[-1, 1] (no ``.astype`` on Tensor)."""
    import numpy as np

    t2 = t.detach()
    if t2.dim() > 1:
        t2 = t2.mean(dim=0) if t2.size(0) > 1 else t2.squeeze(0)
    t2 = t2.clamp(-1.0, 1.0).float().cpu().contiguous()
    # Prefer ``np.asarray(tensor)`` over ``.numpy()`` so we always get a real ndarray
    # (avoids odd torch/numpy stacks). Never chain ``np.clip``/``rint`` on a bare Tensor:
    # NumPy 2 ufuncs may return ``torch.Tensor``, then ``.astype`` fails.
    return np.ravel(np.asarray(t2, dtype=np.float32))


def _to_numpy_mono_1d(audio) -> "np.ndarray":
    """Model waveform → 1D float32 numpy. Safe when multiple ``torch`` copies are loaded
    (``isinstance(x, torch.Tensor)`` can lie), and when ``np.asarray`` yields an object array.
    """
    import numpy as np

    t = _unwrap_single_container(audio)
    for _ in range(4):
        if not _is_torchish(t):
            break
        t = _torchish_to_numpy_float32_1d(t)
    if not isinstance(t, np.ndarray):
        t = np.asarray(t, dtype=np.float32)
    if t.dtype == object:
        parts: list = []
        for x in t.ravel():
            u = _unwrap_single_container(x)
            if _is_torchish(u):
                parts.append(_torchish_to_numpy_float32_1d(u))
            else:
                parts.append(np.ravel(np.asarray(u, dtype=np.float32)))
        t = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
    if t.ndim > 1:
        t = t.mean(axis=0) if t.shape[0] > 1 else t.squeeze(0)
    # Final safety: tensor may have slipped through object-array path on CPU
    if _is_torchish(t) or (hasattr(t, "detach") and not isinstance(t, np.ndarray)):
        t = _torchish_to_numpy_float32_1d(t)
    elif not isinstance(t, np.ndarray):
        t = np.asarray(t, dtype=np.float32)
    t = np.clip(np.asarray(t, dtype=np.float32), -1.0, 1.0)
    if t.ndim == 0:
        t = t.reshape(1)
    return t.ravel()


def _coerce_model_generate_out(gout) -> object:
    """``generate()`` returns ``(audio0, …)`` or, on some versions, a tensor directly."""
    if gout is None:
        raise ValueError("Model returned no audio")
    if isinstance(gout, (list, tuple)) and len(gout) == 0:
        raise ValueError("Model returned empty audio")
    o = gout[0] if isinstance(gout, (list, tuple)) else gout
    if o is None:
        raise ValueError("Model returned no audio")
    return _unwrap_single_container(o)


def _coerce_wav_float_numpy(audio) -> "np.ndarray":
    """Force model output to 1D float32 :class:`numpy.ndarray` in ~[-1, 1].

    Some Windows CPU stacks leave a :class:`torch.Tensor` after ``np.asarray`` (no
    ``__array__`` / NumPy dispatch), which then makes ``(arr * …).astype(…)`` fail
    with ``'Tensor' object has no attribute 'astype'``.
    """
    import numpy as np

    arr: object = _to_numpy_mono_1d(audio)
    for _ in range(8):
        if (
            isinstance(arr, np.ndarray)
            and arr.dtype != np.dtype("O")
            and np.issubdtype(arr.dtype, np.number)
        ):
            # Second ``asarray`` forces a NumPy-owned buffer (not a Tensor view).
            out = np.ravel(np.asarray(arr, dtype=np.float32, order="C"))
            np.clip(out, -1.0, 1.0, out=out)
            return out
        if _is_torchish(arr):
            arr = _torchish_to_numpy_float32_1d(arr)
            continue
        mod = getattr(type(arr), "__module__", "") or ""
        if mod.startswith("torch") and callable(getattr(arr, "numpy", None)):
            arr = _torchish_to_numpy_float32_1d(arr)
            continue
        try:
            import torch as _torch
        except ImportError:
            _torch = None
        if _torch is not None and isinstance(arr, _torch.Tensor):
            arr = _torchish_to_numpy_float32_1d(arr)
            continue
        arr = np.asarray(arr, dtype=np.float32)

    try:
        seq = arr.tolist() if hasattr(arr, "tolist") else arr
        arr = np.ravel(np.asarray(seq, dtype=np.float32))
        if arr.size and (
            isinstance(arr, np.ndarray)
            and arr.dtype != np.dtype("O")
            and np.issubdtype(arr.dtype, np.number)
        ):
            np.clip(arr, -1.0, 1.0, out=arr)
            return arr
    except (TypeError, ValueError):
        pass

    raise RuntimeError(
        "Could not convert generated audio to NumPy (tensor→numpy failed). "
        "Try: pip install -U numpy torch -- or report torch and numpy versions."
    )


def _audio_tensor_to_wav_bytes(audio, sample_rate: int) -> bytes:
    """Convert a float32 audio signal to 16-bit PCM WAV bytes using stdlib wave.

    Accepts either a torch.Tensor OR a numpy.ndarray (some omnivoice versions
    return numpy from ``model.generate``). Works with no external codec
    dependencies. Shape can be (channels, samples) or (samples,) — mixed to mono.
    """
    import io
    import wave as _wave
    import numpy as np

    arr = _coerce_wav_float_numpy(audio)
    # NumPy ufuncs on a ``torch.Tensor`` can return Tensor (NumPy 2 interop); then
    # ``.astype(np.int16)`` raises. Force a host ndarray before any ufunc chain.
    arr = np.asarray(arr, dtype=np.float64)
    pcm = np.clip(np.rint(arr * 32767.0), -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class _GenProgress:
    """Live terminal progress bar while model.generate() runs.

    * ``output_sec`` = model's predicted *audio* length (same idea as generate duration).
    * ``bar_wall_sec`` = rough *wall-clock* budget for the bar (decode is much slower
      than real-time; do not use output_sec for the bar).

    Usage::
        with _GenProgress("Voice Clone", output_sec=22.0, bar_wall_sec=130.0):
            audio = model.generate(...)
    """

    _SPIN = ["|", "/", "-", "\\"]
    _BAR_W = 22

    def __init__(
        self,
        mode: str,
        *,
        output_sec: float | None = None,
        bar_wall_sec: float | None = None,
    ) -> None:
        self._mode = mode
        self._out = output_sec
        self._bar = bar_wall_sec
        self._t0 = 0.0
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._t0 = time.time()
        bits: list[str] = []
        if self._out and self._out > 0.1:
            bits.append(f"audio ~{self._out:.0f}s out")
        if self._bar and self._bar > 1.0:
            bits.append(f"~{self._bar:.0f}s compute est.")
        est_str = f"  ({' · '.join(bits)})" if bits else ""
        print(f"[OmniVoice] Generating {self._mode}...{est_str}", flush=True)
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

    @staticmethod
    def _bar_fraction(elapsed: float, initial_wall: float) -> float:
        """0..0.99; if we're past the estimate, stretch the target so the bar can move on."""
        if initial_wall <= 1.0:
            return 0.0
        denom = initial_wall
        if elapsed > denom * 0.88:
            denom = max(denom, elapsed / 0.9 + 3.0)
        return min(elapsed / denom, 0.99)

    def _loop(self):
        idx = 0
        while not self._done.wait(0.3):
            elapsed = time.time() - self._t0
            spin = self._SPIN[idx % len(self._SPIN)]
            if self._bar and self._bar > 1.0:
                frac = self._bar_fraction(elapsed, self._bar)
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
                f"    driver CUDA >= 12.8  ->  option 8 (CUDA 12.8)\n"
                f"    driver CUDA >= 12.4  ->  option C (CUDA 12.4)\n"
                f"    driver CUDA >= 12.1  ->  option B (CUDA 12.1)\n"
                f"    driver CUDA >= 11.8  ->  option A (CUDA 11.8)\n"
                f"  Check your driver:  run  nvidia-smi  and look for 'CUDA Version'.\n",
                flush=True,
            )
        else:
            _device_info = "CPU (no NVIDIA GPU detected)"
            print("[OmniVoice] Running on CPU — no NVIDIA GPU detected.", flush=True)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _device_info = "CPU"
        print("[OmniVoice] Running on CPU.", flush=True)

    print(
        "[OmniVoice] CPU mode: float32, tensor-to-numpy conversion active.",
        flush=True,
    )
    return "cpu", torch.float32


def _resolve_whisper_pipeline_device(model) -> tuple[object, object]:
    """Where to run Whisper: CPU saves ~1–2 GiB VRAM for OmniVoice TTS on 6 GB cards.

    Env:
      ``OMNIVOICE_WHISPER_DEVICE`` — ``cpu`` | ``cuda`` | empty (auto).
      ``OMNIVOICE_WHISPER_AUTO_CPU_VRAM_MIB`` — auto uses CPU when total VRAM is
      below this many MiB (default 7800 ≈ treat 6–7 GiB cards as small).
    """
    import torch

    env = (os.environ.get("OMNIVOICE_WHISPER_DEVICE") or "").strip().lower()
    if env == "cpu":
        return "cpu", torch.float32
    if env in ("cuda", "gpu", "cuda:0"):
        dev = getattr(model, "device", None) or (
            "cuda:0" if torch.cuda.is_available() else "cpu"
        )
        dt = torch.float16 if str(dev).startswith("cuda") else torch.float32
        return dev, dt

    if not torch.cuda.is_available():
        return "cpu", torch.float32

    try:
        mib_th = int(os.environ.get("OMNIVOICE_WHISPER_AUTO_CPU_VRAM_MIB", "7800"))
        total_b = torch.cuda.get_device_properties(0).total_memory
        if total_b < mib_th * 1024 * 1024:
            tot_gib = total_b / (1024.0**3)
            print(
                f"[OmniVoice] GPU has ~{tot_gib:.1f} GiB VRAM (<{mib_th} MiB auto threshold) — "
                "Whisper runs on CPU so TTS keeps GPU memory (avoids slow shared-RAM spill). "
                "Force GPU ASR: OMNIVOICE_WHISPER_DEVICE=cuda",
                flush=True,
            )
            return "cpu", torch.float32
    except Exception:
        pass

    dev = getattr(model, "device", "cuda:0")
    dt = torch.float16 if str(dev).startswith("cuda") else torch.float32
    return dev, dt


def _patch_omnivoice_whisper_device_policy() -> None:
    """Replace ``OmniVoice.load_asr_model`` so Whisper can use CPU on low-VRAM GPUs."""
    global _omnivoice_whisper_device_patched
    if _omnivoice_whisper_device_patched:
        return
    import logging

    import torch
    from omnivoice import OmniVoice

    _log = logging.getLogger("omnivoice.models.omnivoice")

    def load_asr_model(self, model_name: str = "openai/whisper-large-v3-turbo"):
        from transformers import pipeline as hf_pipeline

        dev, asr_dtype = _resolve_whisper_pipeline_device(self)
        _log.info("Loading ASR model %s ...", model_name)
        self._asr_pipe = hf_pipeline(
            "automatic-speech-recognition",
            model=model_name,
            dtype=asr_dtype,
            device_map=dev,
        )
        _log.info("ASR model loaded on %s.", dev)

    OmniVoice.load_asr_model = load_asr_model  # type: ignore[method-assign]
    _omnivoice_whisper_device_patched = True


def _load_model_blocking() -> None:
    """Load weights once (runs in background thread)."""
    global _model, _load_error
    import traceback

    with _model_lock:
        if _model is not None:
            return
        try:
            _patch_omnivoice_audio_utils()
            from omnivoice import OmniVoice

            _patch_omnivoice_whisper_device_policy()
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
    .update-strip {
      display: none;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 0.5rem 1rem;
      margin-bottom: 1.1rem;
      padding: 0.75rem 1rem;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0f1219;
      font-size: 0.88rem;
      text-align: left;
    }
    .update-strip.show { display: flex; }
    .update-strip.outdated {
      border-color: #a16207;
      background: linear-gradient(135deg, #1a1508 0%, #0f1219 100%);
      color: #fcd34d;
    }
    .update-strip.current {
      border-color: #14532d;
      background: linear-gradient(135deg, #0c1a12 0%, #0f1219 100%);
      color: #86efac;
    }
    .update-strip .update-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem 0.65rem;
      align-items: center;
      justify-content: center;
    }
    .update-strip button.update-btn {
      width: auto;
      margin: 0;
      padding: 0.45rem 0.95rem;
      font-size: 0.85rem;
      background: linear-gradient(120deg, var(--accent), #4f7ae8);
    }
    .update-strip a.update-link {
      color: #93c5fd;
      font-weight: 500;
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
          <p class="hint">Maximum length <strong>{{ ref_audio_max_sec|int }} seconds</strong> — longer files are not accepted (trim first). Clear speech; match the transcription below.<br />
            <span lang="hi">अधिकतम {{ ref_audio_max_sec|int }} सेकंड — इससे लंबी फ़ाइल स्वीकार नहीं; पहले ट्रिम करें।</span></p>
          <p class="hint" id="ref-audio-duration-hint" aria-live="polite"></p>
        </div>
        <div class="row">
          <label><input type="checkbox" name="auto_transcribe_ref" value="1" checked /> Auto-transcribe reference (Whisper — recommended)</label>
          <p class="hint">Runs ASR once per WAV; the transcript is saved under <code>webui_data/ref_transcript_cache/</code> (by file hash). Same reference file again = no Whisper re-run. Paste a manual transcript below to skip ASR.</p>
        </div>
        <div class="row">
          <label for="ref_text">Reference transcription (optional if auto-transcribe is on)</label>
          <input id="ref_text" name="ref_text" type="text"
            placeholder="Exact words in the WAV — leave empty when using auto-transcribe" />
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
          <p class="hint" id="hint-quality-clone">Speed is mostly <strong>diffusion steps</strong> (<code>num_step</code>): use <strong>Faster preview</strong> on GPUs like RTX 3050. “Balanced” = model default (32 steps). Higher quality = more steps, slower.</p>
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
          <p class="hint">Helps quality when set; empty uses language-agnostic mode. Hindi uses slightly slower pacing when detected.</p>
        </div>
        <div class="row">
          <label><input type="checkbox" name="use_design_voice_lock" value="1" /> Use saved design voice (consistent timbre)</label>
          <p class="hint">Reuses the WAV you saved below as reference audio — same character across sessions, like locking a designed voice.</p>
        </div>
        <div class="row">
          <label><input type="checkbox" name="save_design_voice_lock" value="1" /> After this run, save output as my design voice</label>
          <p class="hint">Generate once with the voice you like, check this, then later enable &quot;Use saved design voice&quot; for consistency.</p>
        </div>
        <button type="submit" id="submit-btn" {% if load_error or not model_ready %}disabled{% endif %}>Generate speech</button>
        <p class="hint">No WAV upload needed — describes the voice in text instead of cloning a sample.</p>
      </form>
      {% endif %}
      <div id="result"></div>
    </div>

    <footer>
      <div id="update-strip" class="update-strip show" role="status" aria-live="polite">
        <span id="update-strip-msg">Checking for updates…</span>
        <div class="update-actions">
          <a id="update-repo-link" class="update-link" href="https://github.com/HunterisLive-1/omni-voice" target="_blank" rel="noopener">GitHub</a>
          <button type="button" id="update-run-btn" class="update-btn" style="display:none">Run update</button>
        </div>
      </div>
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

    const refIn = document.getElementById("ref_audio");
    const refHint = document.getElementById("ref-audio-duration-hint");
    const REF_MAX = {{ ref_audio_max_sec }};
    if (refIn && refHint) {
      refIn.addEventListener("change", async function () {
        refHint.textContent = "";
        refHint.className = "hint";
        const f = this.files && this.files[0];
        if (!f) return;
        try {
          const buf = await f.arrayBuffer();
          const AC = window.AudioContext || window.webkitAudioContext;
          if (!AC) {
            refHint.textContent = "Cannot check length in this browser; the server will verify.";
            return;
          }
          const ctx = new AC();
          const audioBuf = await ctx.decodeAudioData(buf.slice(0));
          ctx.close();
          const d = audioBuf.duration;
          if (d > REF_MAX + 0.05) {
            refHint.className = "hint err";
            refHint.innerHTML = "Not accepted: " + d.toFixed(1) + "s (max " + REF_MAX + "s). Trim the WAV and choose again. / स्वीकार नहीं: अधिकतम " + REF_MAX + " सेकंड।";
            this.value = "";
          } else {
            refHint.textContent = "Duration: " + d.toFixed(1) + "s — OK (max " + REF_MAX + "s).";
          }
        } catch (_) {
          refHint.textContent = "Could not read duration in browser; the server will verify.";
        }
      });
    }

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
        const w = res.headers.get("X-OmniVoice-Warn");
        let extra = "";
        if (w) extra = "<p class=\\"hint\\"><strong>Note:</strong> " + w.replace(/</g, "&lt;") + "</p>";
        result.innerHTML = "<p class=\\"status\\">Done — play or save below.</p>" + extra + "<audio controls src=\\"" + url + "\\"></audio>";
      } catch (err) {
        result.innerHTML = "<div class=\\"err\\">" + err.message + "</div>";
      }
      btn.disabled = false;
    });

    (function updateBanner() {
      const strip = document.getElementById("update-strip");
      const msg = document.getElementById("update-strip-msg");
      const runBtn = document.getElementById("update-run-btn");
      const link = document.getElementById("update-repo-link");
      if (!strip || !msg) return;
      async function refresh() {
        try {
          const r = await fetch("/api/update-check");
          const j = await r.json();
          if (!j.ok) {
            strip.className = "update-strip show";
            msg.textContent = "Could not check for updates.";
            return;
          }
          if (link && j.repo_html) link.href = j.repo_html;
          strip.className = "update-strip show";
          if (j.update_available === true) {
            strip.classList.add("outdated");
            msg.textContent = "Update available — you have " + (j.local_short || "?") + ", GitHub main is " + (j.remote_short || "?") + ".";
          } else if (j.update_available === false) {
            strip.classList.add("current");
            msg.textContent = "You are on the latest version (" + (j.local_short || j.remote_short || "") + ").";
          } else {
            msg.textContent = j.hint || "Run update.bat in the project folder to sync with GitHub.";
          }
          if (runBtn) {
            runBtn.style.display = j.can_run_update ? "inline-block" : "none";
            runBtn.disabled = false;
          }
        } catch (_) {
          strip.className = "update-strip show";
          msg.textContent = "Could not check for updates (browser or network).";
        }
      }
      refresh();
      if (runBtn) {
        runBtn.addEventListener("click", async function () {
          if (this.disabled) return;
          this.disabled = true;
          try {
            const r = await fetch("/api/run-update", { method: "POST" });
            const j = await r.json();
            alert(j.message || (j.ok ? "OK" : "Failed"));
          } catch (e) {
            alert(e && e.message ? e.message : String(e));
          }
          this.disabled = false;
        });
      }
    })();
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
        ref_audio_max_sec=REF_AUDIO_MAX_DURATION_SEC,
    )


def _local_git_head_sha() -> str | None:
    ref = PROJECT_ROOT / ".git" / "refs" / "heads" / GITHUB_UPDATE_BRANCH
    if ref.is_file():
        try:
            s = ref.read_text(encoding="utf-8").strip()
            if len(s) >= 7:
                return s
        except OSError:
            pass
    run_kw: dict = {
        "args": ["git", "rev-parse", "HEAD"],
        "cwd": str(PROJECT_ROOT),
        "capture_output": True,
        "text": True,
        "timeout": 6,
    }
    if sys.platform == "win32":
        run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        r = subprocess.run(**run_kw)
        if r.returncode == 0 and (r.stdout or "").strip():
            return (r.stdout or "").strip()
    except OSError:
        pass
    return None


def _github_latest_commit_sha() -> str | None:
    import urllib.error
    import urllib.request

    url = (
        f"https://api.github.com/repos/{GITHUB_UPDATE_OWNER}/{GITHUB_UPDATE_REPO}"
        f"/commits/{GITHUB_UPDATE_BRANCH}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OmniVoice-WebUI/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.load(resp)
        sha = data.get("sha")
        if isinstance(sha, str) and len(sha) >= 7:
            return sha
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def _client_is_trusted_localhost(req) -> bool:
    a = (req.remote_addr or "").strip().lower()
    if a in ("127.0.0.1", "::1", "localhost"):
        return True
    if a.startswith("127.") or a.startswith("::ffff:127."):
        return True
    return False


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


@_app.route("/api/update-check")
def api_update_check():
    """Compare local git HEAD with GitHub main (public API)."""
    repo_html = f"https://github.com/{GITHUB_UPDATE_OWNER}/{GITHUB_UPDATE_REPO}"
    can_run = _client_is_trusted_localhost(request)
    local = _local_git_head_sha()
    remote = _github_latest_commit_sha()
    local_s = (local or "")[:7] if local else None
    remote_s = (remote or "")[:7] if remote else None

    if not remote:
        return jsonify(
            ok=True,
            local_sha=local,
            local_short=local_s,
            remote_sha=None,
            remote_short=None,
            update_available=None,
            hint="Could not reach GitHub (offline or rate limit). You can still run update.bat manually.",
            repo_html=repo_html,
            can_run_update=can_run,
        )
    if not local:
        return jsonify(
            ok=True,
            local_sha=None,
            local_short=None,
            remote_sha=remote,
            remote_short=remote_s,
            update_available=None,
            hint=f"Latest on GitHub main: {remote_s}. If you used a ZIP, run update.bat in the project folder to sync.",
            repo_html=repo_html,
            can_run_update=can_run,
        )

    same = local[:40] == remote[:40] if len(local) >= 40 and len(remote) >= 40 else local == remote
    return jsonify(
        ok=True,
        local_sha=local,
        local_short=local_s,
        remote_sha=remote,
        remote_short=remote_s,
        update_available=(not same),
        hint=None,
        repo_html=repo_html,
        can_run_update=can_run,
    )


@_app.route("/api/run-update", methods=["POST"])
def api_run_update():
    """Open update.bat (Windows) — only from localhost; user restarts run.bat after."""
    if not _client_is_trusted_localhost(request):
        return jsonify(
            ok=False,
            message="Updates can only be started from this PC (open the Web UI at 127.0.0.1).",
        ), 403
    bat = PROJECT_ROOT / "update.bat"
    if not bat.is_file():
        return jsonify(
            ok=False,
            message="update.bat not found in the project folder.",
        ), 404
    if sys.platform != "win32":
        return jsonify(
            ok=False,
            message="One-click update is for Windows. Otherwise: git pull or re-download from GitHub.",
        ), 400
    try:
        os.startfile(str(bat))  # noqa: S606
    except OSError as e:
        return jsonify(ok=False, message=str(e)), 500
    return jsonify(
        ok=True,
        message=(
            "update.bat should open in a new window. When it finishes, stop this Web UI "
            "(Ctrl+C in the black console) and start run.bat again."
        ),
    )


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

    text = _normalize_chunking_text((request.form.get("text") or "").strip())
    ref_text = (request.form.get("ref_text") or "").strip()
    auto_transcribe = _form_checkbox_on(request.form.get("auto_transcribe_ref"))
    if not text:
        return Response("Missing text to speak.", status=400, mimetype="text/plain")
    if not auto_transcribe and not ref_text:
        return Response(
            "Either enable auto-transcribe or paste the exact words spoken in the WAV.",
            status=400,
            mimetype="text/plain",
        )

    suffix = Path(ref_file.filename).suffix.lower() or ".wav"
    if suffix not in (".wav", ".wave"):
        return Response("Please upload a WAV file.", status=400, mimetype="text/plain")

    tmp_raw = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_raw_path = tmp_raw.name
    tmp_raw.close()
    tmp_proc = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp_proc_path = tmp_proc.name
    tmp_proc.close()
    gen_kw, speed = _resolve_style_and_quality(
        request.form.get("speaking_style"),
        request.form.get("quality_preset"),
    )
    clone_instruct = _instruct_for_clone(
        request.form.get("speaking_style"),
        request.form.get("voice_gender"),
    )
    warn_hdr: list[str] = []

    try:
        ref_file.save(tmp_raw_path)
        reject = _reject_clone_reference_if_too_long(tmp_raw_path)
        if reject is not None:
            return reject
        sr = int(getattr(_model, "sampling_rate", None) or 24000)
        pre_warnings, _dur = _preprocess_reference_wav(tmp_raw_path, tmp_proc_path, sr)
        warn_hdr.extend(pre_warnings)

        raw_hash = _sha256_file(tmp_raw_path)
        proc_hash = _sha256_file(tmp_proc_path)
        cached_tr: str | None = None
        if auto_transcribe:
            cached_tr = _ref_cache_read(raw_hash) or _ref_cache_read(proc_hash)
            if cached_tr:
                print(
                    "[OmniVoice] Using cached reference transcript (same WAV as a prior run).",
                    flush=True,
                )

        call_kw: dict = {**gen_kw, "text": text}
        if clone_instruct:
            call_kw["instruct"] = clone_instruct

        ref_for_dur: str | None = None
        est_sec: float | None = None

        if auto_transcribe and ref_text:
            # Expert override: skip ASR but keep preprocessing/trim.
            call_kw["ref_audio"] = tmp_proc_path
            call_kw["ref_text"] = ref_text
            ref_for_dur = ref_text
        elif auto_transcribe and cached_tr:
            call_kw["ref_audio"] = tmp_proc_path
            call_kw["ref_text"] = cached_tr
            ref_for_dur = cached_tr
        elif auto_transcribe:
            with _model_lock:
                _ensure_whisper_pipeline(_model)
                vcp = _model.create_voice_clone_prompt(
                    ref_audio=tmp_proc_path,
                    ref_text=None,
                    preprocess_prompt=True,
                )
            _ref_cache_write_dual(raw_hash, proc_hash, vcp.ref_text)
            call_kw["voice_clone_prompt"] = vcp
            ref_for_dur = vcp.ref_text
        else:
            call_kw["ref_audio"] = tmp_proc_path
            call_kw["ref_text"] = ref_text
            ref_for_dur = ref_text

        if ref_for_dur:
            est_sec = _clone_target_duration_seconds(
                _model, ref_for_dur, text, tmp_proc_path
            )
            if est_sec is not None:
                call_kw["duration"] = est_sec
            elif speed is not None:
                call_kw["speed"] = speed
        elif speed is not None:
            call_kw["speed"] = speed

        preview = text[:70].replace("\n", " ") + ("…" if len(text) > 70 else "")
        print(f'[OmniVoice] Text: "{preview}"', flush=True)
        _ns_est = int(gen_kw.get("num_step") or 32)
        wall = _wall_clock_estimate_for_progress(
            est_sec, _device_info, num_step=_ns_est
        )
        try:
            with _GenProgress(
                "Voice Clone",
                output_sec=est_sec,
                bar_wall_sec=wall,
            ):
                with _model_lock:
                    _unload_asr_if_loaded(_model)
                    audio = _model.generate(**call_kw)
        except ValueError as e:
            return Response(
                "Invalid style for this mode:\n" + str(e),
                status=400,
                mimetype="text/plain",
            )
        wav_bytes = _audio_tensor_to_wav_bytes(_coerce_model_generate_out(audio), sr)
        headers = {
            "Content-Disposition": "inline; filename=omnivoice_out.wav",
        }
        if warn_hdr:
            headers["X-OmniVoice-Warn"] = " ".join(warn_hdr)[:900]
        return Response(wav_bytes, mimetype="audio/wav", headers=headers)
    except Exception as e:  # noqa: BLE001
        return Response(str(e), status=500, mimetype="text/plain")
    finally:
        for p in (tmp_raw_path, tmp_proc_path):
            try:
                os.unlink(p)
            except OSError:
                pass


@_app.route("/generate-design", methods=["POST"])
def generate_design():
    """Voice design, optional Hindi pacing, optional locked reference (saved WAV)."""
    _ensure_load_started()
    if _load_error:
        return Response(_load_error, status=503, mimetype="text/plain")
    if _model is None:
        return Response(
            "Model is still loading. Wait a few seconds and try again.",
            status=503,
            mimetype="text/plain",
        )

    text = _normalize_chunking_text((request.form.get("text") or "").strip())
    if not text:
        return Response("Missing text to speak.", status=400, mimetype="text/plain")

    use_lock = _form_checkbox_on(request.form.get("use_design_voice_lock"))
    save_lock = _form_checkbox_on(request.form.get("save_design_voice_lock"))
    if use_lock and not DESIGN_LOCK_WAV.is_file():
        return Response(
            "No saved design voice found. Generate once with “Save output as my design voice” checked, "
            "then enable “Use saved design voice”.",
            status=400,
            mimetype="text/plain",
        )

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
    if _is_hindi_language_hint(language):
        speed = float(speed) * 0.88 if speed is not None else 0.88

    sr = int(getattr(_model, "sampling_rate", None) or 24000)
    warn_hdr: list[str] = []
    tmp_proc_path: str | None = None
    est_sec: float | None = None

    try:
        if use_lock:
            tmp_proc = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp_proc_path = tmp_proc.name
            tmp_proc.close()
            lock_path = str(DESIGN_LOCK_WAV.resolve())
            raw_lock_hash = _sha256_file(lock_path)
            pre_warnings, _ = _preprocess_reference_wav(lock_path, tmp_proc_path, sr)
            warn_hdr.extend(pre_warnings)
            proc_lock_hash = _sha256_file(tmp_proc_path)
            cached_tr = _ref_cache_read(raw_lock_hash) or _ref_cache_read(
                proc_lock_hash
            )
            if cached_tr:
                print(
                    "[OmniVoice] Using cached design-lock reference transcript.",
                    flush=True,
                )

            call_kw: dict = {**gen_kw, "text": text}
            if instruct_combined:
                call_kw["instruct"] = instruct_combined
            if language:
                call_kw["language"] = language

            ref_for_dur: str | None = None
            if cached_tr:
                call_kw["ref_audio"] = tmp_proc_path
                call_kw["ref_text"] = cached_tr
                ref_for_dur = cached_tr
            else:
                with _model_lock:
                    _ensure_whisper_pipeline(_model)
                    vcp = _model.create_voice_clone_prompt(
                        ref_audio=tmp_proc_path,
                        ref_text=None,
                        preprocess_prompt=True,
                    )
                _ref_cache_write_dual(raw_lock_hash, proc_lock_hash, vcp.ref_text)
                call_kw["voice_clone_prompt"] = vcp
                ref_for_dur = vcp.ref_text

            if ref_for_dur:
                est_sec = _clone_target_duration_seconds(
                    _model, ref_for_dur, text, tmp_proc_path
                )
                if est_sec is not None:
                    call_kw["duration"] = est_sec
                elif speed is not None:
                    call_kw["speed"] = speed
            elif speed is not None:
                call_kw["speed"] = speed
        else:
            call_kw = {"text": text, **gen_kw}
            if instruct_combined:
                call_kw["instruct"] = instruct_combined
            if language:
                call_kw["language"] = language
            if speed is not None:
                call_kw["speed"] = speed

        preview = text[:70].replace("\n", " ") + ("…" if len(text) > 70 else "")
        print(f'[OmniVoice] Text: "{preview}"', flush=True)
        label = "Voice Design (locked ref)" if use_lock else "Voice Design"
        _ns_d = int(gen_kw.get("num_step") or 32)
        wall = _wall_clock_estimate_for_progress(
            est_sec, _device_info, num_step=_ns_d
        )
        try:
            with _GenProgress(
                label,
                output_sec=est_sec,
                bar_wall_sec=wall,
            ):
                with _model_lock:
                    _unload_asr_if_loaded(_model)
                    audio = _model.generate(**call_kw)
        except ValueError as e:
            return Response(
                "Invalid voice style tags:\n" + str(e),
                status=400,
                mimetype="text/plain",
            )
        wav_bytes = _audio_tensor_to_wav_bytes(_coerce_model_generate_out(audio), sr)
        if save_lock:
            try:
                WEBUI_DATA_DIR.mkdir(parents=True, exist_ok=True)
                DESIGN_LOCK_WAV.write_bytes(wav_bytes)
                print(f"[OmniVoice] Saved design voice lock to {DESIGN_LOCK_WAV}", flush=True)
            except OSError as ose:
                warn_hdr.append(f"Could not save design voice lock: {ose}")

        headers = {"Content-Disposition": "inline; filename=omnivoice_design.wav"}
        if warn_hdr:
            headers["X-OmniVoice-Warn"] = " ".join(warn_hdr)[:900]
        return Response(wav_bytes, mimetype="audio/wav", headers=headers)
    except Exception as e:  # noqa: BLE001
        return Response(str(e), status=500, mimetype="text/plain")
    finally:
        if tmp_proc_path:
            try:
                os.unlink(tmp_proc_path)
            except OSError:
                pass


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
