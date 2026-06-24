"""Create a filtered local training bundle from recorded Leha wake clips.

The bundle remains under processed/, which is excluded from Git. It is safe to
inspect before deciding whether to upload it to a private GPU workspace.
"""

from __future__ import annotations

import json
import shutil
import sys
import wave
import zipfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "processed" / "wake_leha_training"
MIN_RMS = 0.006
MIN_SECONDS = 0.20
MAX_SECONDS = 3.0


def inspect(path: Path) -> tuple[int, float, float]:
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    return rate, len(audio) / rate, float(np.sqrt(np.mean(audio**2)) / 32768.0)


def _collect(pattern: str) -> list[Path]:
    return [path for folder in sorted((ROOT / "jarvis_ai" / "voices").glob(pattern)) for path in folder.glob("*.wav")]


def main() -> None:
    positive_sources = _collect("wake_leha*")
    negative_sources = _collect("wake_negative*")
    if not positive_sources:
        raise SystemExit("No positive Leha recordings found under jarvis_ai/voices/wake_leha*")
    if not negative_sources:
        raise SystemExit("No negative recordings found. Run tools/record_leha_wake_negatives.py first.")

    positive = DESTINATION / "positive"
    negative = DESTINATION / "negative"
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    positive.mkdir(parents=True)
    negative.mkdir(parents=True)

    manifest = []
    for source in sorted(positive_sources):
        rate, seconds, rms = inspect(source)
        valid = rate == 16_000 and MIN_SECONDS <= seconds <= MAX_SECONDS and rms >= MIN_RMS
        manifest.append(
            {
                "label": "positive",
                "source": source.name,
                "sample_rate": rate,
                "seconds": round(seconds, 3),
                "rms": round(rms, 5),
                "usable": valid,
            }
        )
        if valid:
            shutil.copy2(source, positive / f"{source.parent.name}_{source.name}")

    for source in sorted(negative_sources):
        rate, seconds, rms = inspect(source)
        valid = rate == 16_000 and MIN_SECONDS <= seconds <= MAX_SECONDS and rms >= MIN_RMS
        manifest.append(
            {
                "label": "negative",
                "source": source.name,
                "sample_rate": rate,
                "seconds": round(seconds, 3),
                "rms": round(rms, 5),
                "usable": valid,
            }
        )
        if valid:
            shutil.copy2(source, negative / f"{source.parent.name}_{source.name}")

    usable = sum(item["usable"] and item["label"] == "positive" for item in manifest)
    usable_negative = sum(item["usable"] and item["label"] == "negative" for item in manifest)
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (DESTINATION / "README.txt").write_text(
        "Leha local wake-word training data.\n"
        f"Usable positive clips: {usable}.\n"
        f"Usable negative clips: {usable_negative}.\n"
        "Keep this bundle private. Hold out at least 10 positive and 30 negative "
        "clips for post-training evaluation.\n",
        encoding="utf-8",
    )

    archive = ROOT / "processed" / "leha_wake_training_bundle.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in DESTINATION.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(DESTINATION.parent))

    print(f"Prepared {usable} positive and {usable_negative} negative clips in {DESTINATION}")
    print(f"Created private local archive: {archive}")
    if usable < 40 or usable_negative < 100:
        raise SystemExit("Need at least 40 positive and 100 negative clips before training.")


if __name__ == "__main__":
    main()
