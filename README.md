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

**OmniVoice** is a massively multilingual zero-shot text-to-speech (TTS) model (600+ languages), with voice cloning and voice design. The **weights and research** come from the [k2-fsa / OmniVoice](https://github.com/k2-fsa/OmniVoice) project and the [Hugging Face model `k2-fsa/OmniVoice`](https://huggingface.co/k2-fsa/OmniVoice).

**This repository** is an **open-source, community-oriented package**: one-click **Windows setup**, a **local Web UI** (Flask), and a small **CLI demo** so more people can run inference on their own machine. Packaging and UI are by **[HunterIsLive](https://www.youtube.com/@HunterIsLive-18)**; the underlying model and science are **not** authored here—see **Credits** below.

### Model weights (large files — not on GitHub)

GitHub blocks files **larger than about 2 GB**. The main checkpoint **`model.safetensors` (~2.45 GB)** and the rest of **`k2-fsa/OmniVoice`** are hosted on **Hugging Face**, not in this repo (see `.gitignore`).

**This GitHub repo’s git history does not contain weights** (no Git LFS checkpoints). If you previously cloned a copy that was still tied to the full Hugging Face model history and `git push` tried to upload gigabytes, update with: `git fetch origin` then `git reset --hard origin/main` (after the maintainer has force-pushed the slim branch).

| What | Where to get it |
|------|-----------------|
| Full model repo (recommended) | **[huggingface.co/k2-fsa/OmniVoice](https://huggingface.co/k2-fsa/OmniVoice)** — open **Files and versions** and use the UI, or use the download commands below. |
| Direct link: main weights | **[model.safetensors](https://huggingface.co/k2-fsa/OmniVoice/resolve/main/model.safetensors)** (large download) |
| All files (snapshot) | Same repo — e.g. `config.json`, tokenizer, `audio_tokenizer/` weights; use `snapshot_download` or **setup.bat** (below). |

**Automatic download:** the first time you run **`run.bat`** / **`webui.py`**, `OmniVoice.from_pretrained("k2-fsa/OmniVoice")` downloads into your machine’s Hugging Face cache (often `%USERPROFILE%\.cache\huggingface\hub` on Windows).

**Prefetch (Windows, after `setup.bat` install):**

- Run **`setup.bat`**, choose **`D`** — *Download / update model weights from Hugging Face*, or from a terminal: **`setup.bat weights`**.
- At the end of a full install, setup may ask **Download OmniVoice weights now?** — answer **`y`** to download before the first Web UI run.

**Prefetch (any OS, with venv active):**

```bash
pip install -U "huggingface_hub>=0.20"
python -c "from huggingface_hub import snapshot_download; snapshot_download('k2-fsa/OmniVoice', repo_type='model')"
```

Or with the [HF CLI](https://huggingface.co/docs/huggingface_hub/guides/cli): `huggingface-cli download k2-fsa/OmniVoice`

---

## What you get in this repo

| Item | Purpose |
|------|--------|
| `setup.bat` | First run: creates `.venv` and installs PyTorch, `omnivoice`, Flask; optional **HF weight download**. Menu: repairs, **`D`** = download/update **`k2-fsa/OmniVoice`** weights. CLI: `setup.bat weights`. |
| `run.bat` | Starts the Web UI (`setup.bat run`). You can pass args through to setup, e.g. `run.bat verify`. |
| `webui.py` | Local Web UI: **Voice clone** (reference WAV) and **Sound design** (describe the voice in text, no WAV) |
| `demo.py` | Minimal command-line example (needs `ref.wav`) |

For **advanced usage** (voice design, non-verbal tags, phonemes, etc.), follow the **[official OmniVoice documentation](https://github.com/k2-fsa/OmniVoice)**.

---

## Quick start (Windows)

1. Install **[Python 3](https://www.python.org/downloads/)** and enable **“Add Python to PATH”** (or use the `py` launcher).
2. Double-click **`setup.bat`**  
   - **No `.venv` yet:** full install (choose **1** = NVIDIA CUDA 12.8, **2** = CPU).  
   - **`.venv` already exists:** a **menu** appears (verify torch, fix null-byte packages, deep repair, reinstall PyTorch, full `install`, etc.). From a terminal you can also run **`setup.bat install`** to refresh everything without the menu.
3. Double-click **`run.bat`** — the browser should open at **`http://127.0.0.1:8765`** (change port with env var `OMNIVOICE_PORT` if needed).
4. In the Web UI, use the tabs at the top:
   - **Voice clone** — upload a short **reference `.wav`**, enter the **exact transcription** of that clip (required; wrong text makes output much longer and worse), optional **Voice gender**, **Speaking style**, **Generation quality**, then **text to speak** and **Generate**. Length is calibrated from the WAV + text so it stays closer to sound-design timing.
   - **Sound design** — choose **Voice character** (preset male/female voices or Custom), optional **Voice gender** (for Custom / Neutral), **Speaking style** (when Custom), **Generation quality**, **text to speak**, optional **Extra voice tags** and **Language**. Preset characters already include gender where noted.

**Sound design tags (English examples):** gender (`male`, `female`), age (`child`, `teenager`, `young adult`, `middle-aged`, `elderly`), pitch (`very low pitch` … `very high pitch`), `whisper`, accents such as `american accent` or `british accent`. Chinese dialect tags are supported for Chinese text. Invalid tags return an error in the UI — see the [upstream OmniVoice docs](https://github.com/k2-fsa/OmniVoice) for the full list.

If Hugging Face asks for access to the model, set a **[Hugging Face token](https://huggingface.co/settings/tokens)** as **`HF_TOKEN`** in your environment.

**Stop the server:** focus the black console window and press **Ctrl+C**.

---

## Manual install (any OS, matches upstream README)

Use a fresh virtual environment (`venv`, `conda`, etc.).

**1. Install PyTorch** — pick GPU or CPU from [pytorch.org](https://pytorch.org/get-started/locally/). Examples:

<details>
<summary>NVIDIA GPU (CUDA 12.8 example)</summary>

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

**2. Install OmniVoice and (for this repo’s Web UI) Flask**

```bash
pip install omnivoice "flask>=3.0"
```

**3. Run the Web UI**

```bash
python webui.py
```

**4. Or run the CLI demo** (place `ref.wav` next to `demo.py`)

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
)  # list of torch.Tensor, 24 kHz

torchaudio.save("out.wav", audio[0], 24000)
```

**Voice design (no reference audio):**

```python
audio = model.generate(
    text="Hello from a designed voice.",
    instruct="female, young adult, moderate pitch, american accent",
    language="English",  # optional; omit for language-agnostic mode
)
torchaudio.save("out_design.wav", audio[0], 24000)
```

---

## Key features (model)

- **600+ languages** in zero-shot TTS  
- **Voice cloning** from short reference audio  
- **Voice design** via speaker attributes (see upstream docs)  
- **Fine-grained control** (e.g. `[laughter]`, pronunciation hints)  
- **Fast inference** — reported RTF down to ~0.025  

---

## Credits & upstream

- **Paper:** [OmniVoice: Towards Omnilingual Zero-Shot Text-to-Speech with Diffusion Language Models](https://huggingface.co/papers/2604.00688)  
- **Official code & issues:** [github.com/k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)  
- **Demo space:** [Hugging Face Space](https://huggingface.co/spaces/k2-fsa/OmniVoice)  

**This fork/packaging:** Web UI, batch installers, and README structure maintained for easier local use by **[HunterIsLive](https://www.youtube.com/@HunterIsLive-18)**. For **model bugs and research questions**, prefer the **upstream** issue tracker.

Upstream community channels (WeChat, etc.) are listed on the [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) README.

---

## Citation

If you use OmniVoice in research, cite the original work:

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

The **OmniVoice model** and original project are released under **Apache-2.0** (see upstream). The **extra scripts** in this repository (`setup.bat`, `run.bat`, `webui.py`, `demo.py`) are provided under the same **Apache-2.0** license for simplicity and compatibility with the model—unless you add a separate `LICENSE` file that states otherwise.
#   o m n i - v o i c e 
 
 