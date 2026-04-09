# OmniVoice — local TTS with Web UI (Windows-friendly)

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

## About

**OmniVoice** is a massively multilingual zero-shot text-to-speech (TTS) model (600+ languages), with voice cloning and voice design.

- **Weights & research:** [k2-fsa / OmniVoice](https://github.com/k2-fsa/OmniVoice) · [Hugging Face model `k2-fsa/OmniVoice`](https://huggingface.co/k2-fsa/OmniVoice)
- **This repo:** Community packaging — **Windows `setup.bat` / `run.bat`**, **Flask Web UI** (`webui.py`), and **`demo.py`**. Maintained by **[HunterIsLive](https://www.youtube.com/@HunterIsLive-18)**. Model science is upstream; see **Credits** below.

---

## Model weights (not in this GitHub repo)

GitHub rejects files **~2 GB+**. The main **`model.safetensors` (~2.45 GB)** and the full **`k2-fsa/OmniVoice`** tree live on **Hugging Face**, not here (see `.gitignore`).

> **This repo’s git history has no weight checkpoints** (no Git LFS model files). If an old clone still had the full HF history and `git push` tried to upload gigabytes: `git fetch origin` then `git reset --hard origin/main`.

| What | Where |
|------|--------|
| Model hub | **[huggingface.co/k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)** → **Files and versions** |
| Main checkpoint | **[model.safetensors (direct)](https://huggingface.co/k2-fsa/OmniVoice/resolve/main/model.safetensors)** |
| Full snapshot | `snapshot_download` or **`setup.bat`** → menu **`D`** / CLI **`setup.bat weights`** |

**First run:** `run.bat` / `webui.py` calls `OmniVoice.from_pretrained("k2-fsa/OmniVoice")` → downloads into the HF cache (often `%USERPROFILE%\.cache\huggingface\hub` on Windows).

**Prefetch (venv active):**

```bash
pip install -U "huggingface_hub>=0.20"
python -c "from huggingface_hub import snapshot_download; snapshot_download('k2-fsa/OmniVoice', repo_type='model')"
```

Or: [`huggingface-cli download k2-fsa/OmniVoice`](https://huggingface.co/docs/huggingface_hub/guides/cli)

---

## What’s in this repository

| File | Role |
|------|------|
| `setup.bat` | Create `.venv`, PyTorch, `omnivoice`, Flask; repair menu; **`D`** = HF weights; **`setup.bat weights`** |
| `run.bat` | Start Web UI (`setup.bat run`); extra args forward to setup |
| `webui.py` | **Voice clone** + **Sound design** Web UI |
| `demo.py` | Minimal CLI (needs `ref.wav`) |

Advanced usage (tags, phonemes, etc.): [official OmniVoice docs](https://github.com/k2-fsa/OmniVoice).

---

## Quick start (Windows)

1. Install [Python 3](https://www.python.org/downloads/) with **Add to PATH** (or use `py`).
2. Run **`setup.bat`**
   - No `.venv` yet → full install (**1** = CUDA 12.8, **2** = CPU).
   - `.venv` exists → **menu** (torch verify, fixes, **`D`** download weights, etc.). Or: **`setup.bat install`**
3. Run **`run.bat`** → browser at **`http://127.0.0.1:8765`** (port: env **`OMNIVOICE_PORT`**).
4. **Web UI tabs**
   - **Voice clone** — reference **WAV**, **exact transcript** (required), optional gender / style / quality, then **Generate**.
   - **Sound design** — **Voice character** preset or Custom, optional tags / language, **Generate**.

**Design tags (examples):** `male` / `female`, ages (`young adult`, …), pitch, `whisper`, `american accent`, etc. — [upstream list](https://github.com/k2-fsa/OmniVoice).

Set **[`HF_TOKEN`](https://huggingface.co/settings/tokens)** if the hub asks for access.

**Stop server:** console window → **Ctrl+C**.

---

## Manual install (any OS)

Use a fresh venv.

**1. PyTorch** — [pytorch.org](https://pytorch.org/get-started/locally/)

<details>
<summary>NVIDIA CUDA 12.8 (example)</summary>

```bash
pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
```

</details>

<details>
<summary>CPU / Apple Silicon (example)</summary>

```bash
pip install torch==2.8.0 torchaudio==2.8.0
```

</details>

**2. OmniVoice + Flask**

```bash
pip install omnivoice "flask>=3.0"
```

**3. Web UI**

```bash
python webui.py
```

**4. CLI demo** (put `ref.wav` next to `demo.py`)

```bash
python demo.py
```

---

## Python API (upstream-style)

```python
from omnivoice import OmniVoice
import torch
import torchaudio

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

**Voice design (no reference audio):**

```python
audio = model.generate(
    text="Hello from a designed voice.",
    instruct="female, young adult, moderate pitch, american accent",
    language="English",
)
torchaudio.save("out_design.wav", audio[0], 24000)
```

---

## Model highlights

- 600+ languages · voice clone · voice design · tags / control · fast inference (see upstream)

---

## Credits & upstream

- **Paper:** [OmniVoice (arXiv)](https://huggingface.co/papers/2604.00688)
- **Code / issues:** [github.com/k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
- **Demo:** [Hugging Face Space](https://huggingface.co/spaces/k2-fsa/OmniVoice)

**Packaging / Web UI:** [HunterIsLive](https://www.youtube.com/@HunterIsLive-18). Research bugs → **upstream** issues.

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

**OmniVoice** and upstream code: **Apache-2.0**. Extra scripts here (`setup.bat`, `run.bat`, `webui.py`, `demo.py`): same unless you add a different `LICENSE`.
