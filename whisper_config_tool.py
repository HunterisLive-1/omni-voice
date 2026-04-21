"""Whisper HF model config for Web UI auto-transcribe — used by setup.bat."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "webui_data" / "whisper_model.txt"
DEFAULT = "openai/whisper-large-v3-turbo"


def read_model() -> str:
    if not CFG.is_file():
        return DEFAULT
    try:
        for line in CFG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except OSError:
        pass
    return DEFAULT


def cmd_save() -> None:
    if len(sys.argv) < 3:
        print("usage: whisper_config_tool.py save <huggingface_model_id>", file=sys.stderr)
        raise SystemExit(2)
    m = sys.argv[2].strip()
    if not m:
        print("Empty model id", file=sys.stderr)
        raise SystemExit(2)
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(m + "\n", encoding="utf-8")
    print("Saved Whisper model:", m)


def cmd_show() -> None:
    print(read_model())


def cmd_download() -> None:
    from huggingface_hub import snapshot_download

    m = read_model()
    print("Downloading", m, "...")
    snapshot_download(m)
    print("Done.")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: whisper_config_tool.py save|show|download", file=sys.stderr)
        raise SystemExit(2)
    op = sys.argv[1].lower()
    if op == "save":
        cmd_save()
    elif op == "show":
        cmd_show()
    elif op == "download":
        cmd_download()
    else:
        print("Unknown command:", op, file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
