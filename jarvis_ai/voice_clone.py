"""Reference-audio voice cloning using Chatterbox TTS.

This module is intentionally isolated from the main listener. The model is
large and slow on CPU, so `mouth.py` runs this in a subprocess with a timeout.
"""
import argparse
from pathlib import Path

import torchaudio as ta

from . import config


def reference_audio() -> str:
    preferred = Path(config.CLONE_TTS_REFERENCE)
    if preferred.exists():
        return str(preferred)
    for item in config.VOICE_REFERENCE_AUDIO:
        path = Path(item)
        if path.exists():
            return str(path)
    raise FileNotFoundError("No voice reference audio found.")


def synthesize(text: str, out_path: str, reference_path: str | None = None) -> str:
    from chatterbox.tts import ChatterboxTTS

    ref = reference_path or reference_audio()
    device = config.CLONE_TTS_DEVICE
    model_dir = Path(config.CLONE_TTS_MODEL_DIR)
    if model_dir.exists():
        model = ChatterboxTTS.from_local(model_dir, device=device)
    else:
        model = ChatterboxTTS.from_pretrained(device=device)
    wav = model.generate(
        text,
        audio_prompt_path=ref,
        exaggeration=config.CLONE_TTS_EXAGGERATION,
        cfg_weight=config.CLONE_TTS_CFG_WEIGHT,
        temperature=config.CLONE_TTS_TEMPERATURE,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ta.save(str(out), wav, model.sr)
    return str(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--reference")
    args = parser.parse_args()
    print(synthesize(args.text, args.out, args.reference), flush=True)


if __name__ == "__main__":
    main()
