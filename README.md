# OmniVoice — Multilingual Zero-Shot TTS · Web UI (Windows)

<p align="center">
  <img width="200" height="200" alt="OmniVoice" src="https://zhu-han.github.io/omnivoice/pics/omnivoice.jpg" />
</p>

<p align="center">
  <a href="https://huggingface.co/k2-fsa/OmniVoice"><img src="https://img.shields.io/badge/Hugging%20Face-Model-FFD21E" alt="Hugging Face Model"></a>
  &nbsp;
  <a href="https://huggingface.co/spaces/k2-fsa/OmniVoice"><img src="https://img.shields.io/badge/Hugging%20Face-Space-blue" alt="Hugging Face Space"></a>
  &nbsp;
  <a href="https://huggingface.co/papers/2604.00688"><img src="https://img.shields.io/badge/arXiv-Paper-B31B1B.svg" alt="arXiv"></a>
  &nbsp;
  <a href="https://github.com/k2-fsa/OmniVoice"><img src="https://img.shields.io/badge/Upstream-k2--fsa%2FOmniVoice-181717?logo=GitHub" alt="Upstream"></a>
  &nbsp;
  <a href="https://www.youtube.com/@HunterIsLive-18"><img src="https://img.shields.io/badge/YouTube-HunterIsLive-FF0000?logo=youtube&logoColor=white" alt="YouTube"></a>
</p>

---

## What is OmniVoice?

**OmniVoice** is a massively multilingual **zero-shot Text-to-Speech (TTS)** model supporting **600+ languages**, with:

- **Voice Cloning** — clone any voice from a short WAV reference
- **Voice Design** — generate a voice from text descriptions (e.g. "female, young adult, american accent")
- Fast inference · no fine-tuning needed

**Model science & research:** [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)  
**This repo:** Community Windows packaging — `setup.bat`, `run.bat`, Flask Web UI (`webui.py`). Maintained by **[HunterIsLive](https://www.youtube.com/@HunterIsLive-18)**.

---

## Requirements

| Requirement | Details |
|---|---|
| **OS** | Windows 10/11 (Linux/macOS: manual install below) |
| **Python** | 3.9 – 3.12 — [python.org](https://www.python.org/downloads/) ✔ tick **"Add to PATH"** |
| **GPU (recommended)** | NVIDIA GPU with CUDA. CPU works but is slow. |
| **Disk space** | ~6 GB for model weights + ~3 GB for packages |
| **RAM** | 8 GB minimum, 16 GB recommended |

---

## Setup & Run — Windows (One-Click)

### Step 1 — Download / Clone this repo

```
git clone https://github.com/HunterIsLive/OmniVoice.git
cd OmniVoice
```

Or download as ZIP from GitHub → Extract.

---

### Step 2 — Run `setup.bat`

Double-click **`setup.bat`** in File Explorer (or run it in Command Prompt).

**First time (no `.venv` yet):**

```
setup.bat
```

It will:
1. Detect your NVIDIA GPU & CUDA version automatically
2. Ask you to confirm the PyTorch build (CUDA 12.8 / 11.8 / CPU)
3. Create a `.venv` virtual environment
4. Install PyTorch, OmniVoice, and Flask
5. Optionally download model weights from Hugging Face (~2.5 GB+)

> **If `.venv` already exists**, `setup.bat` opens a repair/tools menu instead.

---

### Step 3 — Run the Web UI

Double-click **`run.bat`**  
— or —

```
run.bat
```

Browser opens automatically at: **`http://127.0.0.1:8765`**

> To change the port, set environment variable: `set OMNIVOICE_PORT=9000` before running.

**Stop the server:** press `Ctrl+C` in the console window.

---

## Web UI Tabs

### Voice Clone
Replicate any voice from a short audio sample.

| Field | Description |
|---|---|
| **Reference WAV** | Upload a clear audio file (3–30 seconds, WAV preferred) |
| **Exact Transcript** | The exact words spoken in the reference audio (required) |
| **Text to Generate** | The text you want spoken in the cloned voice |
| **Gender / Style / Quality** | Optional adjustments |

### Sound Design
Generate a voice from a description — no reference audio needed.

| Field | Description |
|---|---|
| **Voice Character** | Pick a preset or choose Custom |
| **Description / Tags** | e.g. `female, young adult, moderate pitch, american accent` |
| **Language** | Target language for generation |

**Design tag examples:** `male` / `female`, `young adult` / `middle aged` / `elderly`, `whisper`, `high pitch`, `american accent`, `british accent` — see [upstream docs](https://github.com/k2-fsa/OmniVoice) for full list.

---

## Model Weights (not stored in this GitHub repo)

GitHub rejects files larger than ~2 GB. The main weight file **`model.safetensors` (~2.45 GB)** lives on **Hugging Face**, not here.

| What | Where |
|---|---|
| Model hub | [huggingface.co/k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) |
| Auto-download | `run.bat` / `webui.py` auto-downloads on first run via `OmniVoice.from_pretrained()` |
| Pre-download | `setup.bat` → menu option **`D`** — or — `setup.bat weights` |

**Weights cache location on Windows:** `%USERPROFILE%\.cache\huggingface\hub`

If Hugging Face asks for access, set your token:
```
set HF_TOKEN=hf_your_token_here
```
Get a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

---

## `setup.bat` Menu Reference

Run `setup.bat` after `.venv` is created to get this menu:

| Option | Action |
|---|---|
| `1` | Full install / upgrade (PyTorch + OmniVoice + Flask) |
| `2` | Start Web UI (same as `run.bat`) |
| `3` | Verify torch / CUDA |
| `4` | Fix httpx (null bytes error) |
| `5` | Fix accelerate |
| `6` | Deep repair (HF cache + packages) |
| `7` | Reinstall OmniVoice only |
| `8` | Reinstall PyTorch CUDA 12.8 (RTX 40/50 series, driver ≥ 527) |
| `9` | Reinstall PyTorch CPU |
| `A` | Reinstall PyTorch CUDA 11.8 (older GTX/RTX, driver ≥ 452) |
| `B` | Reinstall PyTorch CUDA 12.1 (driver ≥ 530) |
| `C` | Reinstall PyTorch CUDA 12.4 (RTX 30/40 series, driver ≥ 550) |
| `D` | Download / update model weights from Hugging Face |
| `0` | Exit |

**CLI shortcuts (no menu):**

```bat
setup.bat install       :: Full install
setup.bat weights       :: Download model weights
setup.bat verify        :: Check torch / CUDA
setup.bat fixhttpx      :: Fix httpx errors
setup.bat fixaccelerate :: Fix accelerate errors
setup.bat deeprepair    :: Full deep repair
setup.bat repairomni    :: Reinstall omnivoice only
setup.bat torchcu128    :: Switch to CUDA 12.8 torch
setup.bat torchcpu      :: Switch to CPU torch
```

---

## Manual Install (Linux / macOS / Advanced)

Use a fresh virtual environment.

**1. Create & activate venv**

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

**2. Install PyTorch** — [pytorch.org](https://pytorch.org/get-started/locally/)

<details>
<summary>NVIDIA CUDA 12.8 (RTX 40/50 series)</summary>

```bash
pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
```

</details>

<details>
<summary>CPU / Apple Silicon</summary>

```bash
pip install torch==2.8.0 torchaudio==2.8.0
```

</details>

**3. Install OmniVoice + Flask**

```bash
pip install omnivoice "flask>=3.0"
```

**4. Start Web UI**

```bash
python webui.py
```

**5. CLI demo** (place `ref.wav` next to `demo.py`)

```bash
python demo.py
```

---

## Python API

**Voice Cloning:**

```python
from omnivoice import OmniVoice
import torch, torchaudio

model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cuda:0",
    dtype=torch.float16,
)

audio = model.generate(
    text="Hello, this is a test of zero-shot voice cloning.",
    ref_audio="ref.wav",
    ref_text="Transcription of the reference audio.",
)
torchaudio.save("out.wav", audio[0], 24000)
```

**Voice Design (no reference audio):**

```python
audio = model.generate(
    text="Hello from a designed voice.",
    instruct="female, young adult, moderate pitch, american accent",
    language="English",
)
torchaudio.save("out_design.wav", audio[0], 24000)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `setup.bat` closes instantly | Open CMD in folder → `setup.bat install` |
| CUDA not available after install | Run `setup.bat` → pick the right CUDA option for your driver |
| `httpx` / null bytes error | `setup.bat fixhttpx` |
| `accelerate` error | `setup.bat fixaccelerate` |
| Model download fails | Set `HF_TOKEN` → `setup.bat weights` |
| Broken packages / weird errors | `setup.bat deeprepair` |
| Still broken | Delete `.venv` folder → `setup.bat install` |

Check your CUDA driver version: open CMD and run `nvidia-smi`.

---

## Files in This Repo

| File | Purpose |
|---|---|
| `setup.bat` | One-click install, repair menu, weight download |
| `run.bat` | Start the Web UI |
| `webui.py` | Flask Web UI — Voice Clone + Sound Design |
| `demo.py` | Minimal CLI demo (needs `ref.wav`) |
| `requirements.txt` | Python packages (used by `setup.bat`) |

---

## Credits & Upstream

- **Paper:** [OmniVoice (arXiv 2604.00688)](https://huggingface.co/papers/2604.00688)
- **Upstream code / issues:** [github.com/k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
- **Live demo:** [Hugging Face Space](https://huggingface.co/spaces/k2-fsa/OmniVoice)

**Windows packaging / Web UI:** [HunterIsLive](https://www.youtube.com/@HunterIsLive-18)  
Model science bugs → open issues at **upstream** repo.

---

## Citation

```bibtex
@article{zhu2026omnivoice,
      title={OmniVoice: Towards Omnilingual Zero-Shot Text-to-Speech with Diffusion Language Models},
      author={Zhu, Han and Ye, Lingxuan and Kang, Wei and Yao, Zengwei and Guo, Liyong and Kuang, Fangjun and Han, Zhifeng and Zhuang, Weiji and Lin, Long and Povey, Daniel},
      journal={arXiv preprint arXiv:2604.00688},
      year={2026}
}
```

---

## License

**OmniVoice** model and upstream code: **Apache-2.0**  
Scripts in this repo (`setup.bat`, `run.bat`, `webui.py`, `demo.py`): **Apache-2.0**
