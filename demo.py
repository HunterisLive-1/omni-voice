"""Minimal OmniVoice demo matching README usage."""
from __future__ import annotations

import os
import sys

REF_AUDIO = os.environ.get("REF_AUDIO", "ref.wav")
REF_TEXT = os.environ.get("REF_TEXT", "Transcription of the reference audio.")
OUT_WAV = os.environ.get("OUT_WAV", "out.wav")
TEXT = os.environ.get(
    "OMNIVOICE_TEXT",
    "Hello, this is a test of zero-shot voice cloning.",
)


def main() -> int:
    if not os.path.isfile(REF_AUDIO):
        print(f"Missing reference audio: {REF_AUDIO}")
        print("Add a short WAV file as ref.wav or set REF_AUDIO to its path.")
        print("Set REF_TEXT to the spoken transcription of that audio.")
        return 1

    import torch
    import torchaudio
    from omnivoice import OmniVoice

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device.startswith("cuda") else torch.float32

    print(f"Device: {device}, dtype: {dtype}")
    print("Loading k2-fsa/OmniVoice (first run may download weights)...")

    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice",
        device_map=device,
        dtype=dtype,
    )

    print("Generating...")
    audio = model.generate(
        text=TEXT,
        ref_audio=REF_AUDIO,
        ref_text=REF_TEXT,
    )

    torchaudio.save(OUT_WAV, audio[0], 24000)
    print(f"Saved: {OUT_WAV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
