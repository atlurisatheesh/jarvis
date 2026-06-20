"""Create a small upload bundle for Colab/Kaggle voice cloning.

Run from the project root:
    python tools/prepare_voice_gpu_bundle.py
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICES = ROOT / "jarvis_ai" / "voices"
OUT = ROOT / "voice_gpu_bundle.zip"

REFERENCE_CANDIDATES = [
    VOICES / "leha_reference_mix.wav",
    VOICES / "leha_reference.wav",
    ROOT / "WhatsApp%20Video%202026-02-20%20at%208.26.37%20PM_audio_cleaned.mp3",
    ROOT / "WhatsApp%20Video%202026-02-13%20at%208.59.02%20PM_audio_cleaned.mp3",
]

PROMPTS = [
    "Hello Sir, I am Leha. I am ready to help you.",
    "I heard you. Tell me what you need.",
    "Done, Sir.",
    "I am listening.",
    "The system is ready.",
    "I can help with music, YouTube, reminders, files, and answers.",
]


def main() -> None:
    files = [path for path in REFERENCE_CANDIDATES if path.exists()]
    if not files:
        raise SystemExit("No reference audio found. Add audio to jarvis_ai/voices first.")

    manifest = {
        "assistant_name": "Leha",
        "reference_files": [path.name for path in files],
        "recommended_reference": files[0].name,
        "prompts": PROMPTS,
        "note": (
            "Use this only with audio you own or have permission to clone. "
            "GPU generation is fast; local CPU generation is slow."
        ),
    }

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("prompts.txt", "\n".join(PROMPTS) + "\n")
        for path in files:
            zf.write(path, f"refs/{path.name}")

    print(f"Created {OUT}")
    print("Upload this zip to the Colab/Kaggle notebook.")


if __name__ == "__main__":
    main()
