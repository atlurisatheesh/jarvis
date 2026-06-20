"""Install downloaded GPU voice outputs into the local Leha project.

Run from the project root after downloading `leha_gpu_outputs.zip`:
    python tools/install_voice_gpu_outputs.py path\to\leha_gpu_outputs.zip
"""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICES = ROOT / "jarvis_ai" / "voices"
INSTALLED = VOICES / "gpu_outputs"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", help="Downloaded leha_gpu_outputs.zip from Colab/Kaggle")
    args = parser.parse_args()

    zip_path = Path(args.zip_path).expanduser().resolve()
    if not zip_path.exists():
        raise SystemExit(f"Not found: {zip_path}")

    if INSTALLED.exists():
        shutil.rmtree(INSTALLED)
    INSTALLED.mkdir(parents=True)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(INSTALLED)

    wavs = sorted(INSTALLED.glob("*.wav"))
    settings_path = INSTALLED / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        settings = []

    print(f"Installed GPU voice outputs to {INSTALLED}")
    if wavs:
        print("Sample files:")
        for wav in wavs[:10]:
            print(f"  {wav}")
    if settings:
        print("\nAvailable generation settings:")
        for item in settings:
            print(
                f"  {item['name']}: "
                f"exaggeration={item['exaggeration']}, "
                f"cfg_weight={item['cfg_weight']}, "
                f"temperature={item['temperature']}"
            )

    print(
        "\nFor live cloned voice, set TTS_ENGINE='clone' in jarvis_ai/config.py. "
        "On this CPU laptop it will still be slow; use a warm GPU endpoint for instant live cloning."
    )


if __name__ == "__main__":
    main()
