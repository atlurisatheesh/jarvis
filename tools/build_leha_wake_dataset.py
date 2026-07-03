"""Build a train/held-out dataset for the private Leha wake model.

This tool keeps the approval test honest:
- recorded owner wake clips are copied into positive train/held-out splits
- negatives are generated from silence, noise, tones, and non-wake local audio
- similar-sounding phrases are synthesized when edge-tts is available

It does not deploy a model. Train and evaluate separately.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import shutil
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


ROOT = Path(__file__).resolve().parent.parent
RATE = 16_000
WINDOW = RATE

POSITIVE_DIRS = [
    ROOT / "jarvis_ai" / "voices" / "wake_leha",
    ROOT / "jarvis_ai" / "voices" / "wake_leha_continuous",
    ROOT / "jarvis_ai" / "voices" / "wake_leha_retry",
]

LOCAL_NEGATIVE_SOURCES = [
    ROOT / "jarvis_ai" / "voices" / "ref_a.wav",
    ROOT / "jarvis_ai" / "voices" / "ref_b.wav",
    ROOT / "jarvis_ai" / "voices" / "openvoice_source.wav",
    ROOT / "jarvis_ai" / "voices" / "openvoice_source_long.wav",
    ROOT / "jarvis_ai" / "voices" / "openvoice_source.mp3",
    ROOT / "jarvis_ai" / "voices" / "openvoice_source_long.mp3",
]

NEGATIVE_PHRASES = [
    "hello",
    "hey there",
    "what time is it",
    "play music",
    "open youtube",
    "stop music",
    "pause music",
    "close youtube",
    "how are you",
    "tell me the weather",
    "set a reminder",
    "call me later",
    "leader",
    "lena",
    "layla",
    "leela",
    "lila",
    "lisa",
    "lee ha",
    "hey siri",
    "alexa",
    "jarvis",
    "google",
]

TTS_VOICES = [
    "en-IN-NeerjaNeural",
    "en-IN-PrabhatNeural",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-GB-LibbyNeural",
]


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _load_audio(path: Path) -> np.ndarray | None:
    try:
        data, sr = sf.read(str(path), dtype="float32")
    except Exception:
        return None
    if data.ndim > 1:
        data = data[:, 0]
    if sr != RATE:
        divisor = math.gcd(sr, RATE)
        data = resample_poly(data, RATE // divisor, sr // divisor).astype(np.float32)
    peak = float(np.max(np.abs(data))) if len(data) else 0.0
    if peak > 1.0:
        data = data / peak
    return data.astype(np.float32)


def _window(audio: np.ndarray, start: int | None = None) -> np.ndarray:
    if len(audio) < WINDOW:
        out = np.zeros(WINDOW, dtype=np.float32)
        offset = (WINDOW - len(audio)) // 2
        out[offset : offset + len(audio)] = audio
        return out
    if start is None:
        start = max(0, (len(audio) - WINDOW) // 2)
    start = max(0, min(start, len(audio) - WINDOW))
    return audio[start : start + WINDOW].astype(np.float32)


def _write(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(audio, -1.0, 1.0), RATE, subtype="PCM_16")


def _copy_positive_splits(out: Path, heldout_ratio: float, min_positive_rms: float) -> dict:
    files: list[Path] = []
    for directory in POSITIVE_DIRS:
        files.extend(sorted(directory.glob("*.wav")))
    files = sorted(set(files))
    usable: list[tuple[Path, np.ndarray]] = []
    rejected = 0
    for src in files:
        audio = _load_audio(src)
        if audio is None:
            rejected += 1
            continue
        clipped = _window(audio)
        rms = float(np.sqrt(np.mean(clipped * clipped)))
        if rms < min_positive_rms:
            rejected += 1
            continue
        usable.append((src, clipped))

    random.shuffle(usable)
    heldout_count = max(5, int(len(usable) * heldout_ratio))
    heldout = usable[:heldout_count]
    train = usable[heldout_count:]

    for i, (_, audio) in enumerate(train):
        _write(out / "train" / "positive" / f"pos_{i:04d}.wav", audio)
    for i, (_, audio) in enumerate(heldout):
        _write(out / "heldout" / "positive" / f"pos_{i:04d}.wav", audio)

    return {
        "positive_train": len(train),
        "positive_heldout": len(heldout),
        "positive_rejected_low_rms": rejected,
        "min_positive_rms": min_positive_rms,
    }


def _tone(freq: float, gain: float = 0.12) -> np.ndarray:
    t = np.arange(WINDOW, dtype=np.float32) / RATE
    return gain * np.sin(2.0 * np.pi * freq * t).astype(np.float32)


def _generate_non_tts_negatives(out: Path, count: int) -> int:
    train_dir = out / "train" / "negative"
    heldout_dir = out / "heldout" / "negative"
    written = 0

    def emit(audio: np.ndarray, heldout: bool = False) -> None:
        nonlocal written
        target = heldout_dir if heldout else train_dir
        _write(target / f"neg_{written:05d}.wav", audio)
        written += 1

    for _ in range(max(20, count // 8)):
        emit(np.zeros(WINDOW, dtype=np.float32), heldout=(written % 5 == 0))
        emit((np.random.randn(WINDOW) * random.uniform(0.005, 0.08)).astype(np.float32), heldout=(written % 5 == 0))

    for freq in [120, 220, 440, 880, 1200, 2000]:
        emit(_tone(freq), heldout=(written % 5 == 0))

    for source in LOCAL_NEGATIVE_SOURCES:
        audio = _load_audio(source)
        if audio is None:
            continue
        windows = max(1, min(40, len(audio) // WINDOW))
        for _ in range(windows):
            start = random.randint(0, max(0, len(audio) - WINDOW))
            sample = _window(audio, start)
            if random.random() < 0.6:
                sample = sample + (np.random.randn(WINDOW) * random.uniform(0.002, 0.02)).astype(np.float32)
            emit(sample, heldout=(written % 5 == 0))

    while written < count:
        emit((np.random.randn(WINDOW) * random.uniform(0.002, 0.06)).astype(np.float32), heldout=(written % 5 == 0))

    return written


async def _edge_tts_clip(text: str, voice: str, rate: str) -> np.ndarray | None:
    try:
        import edge_tts
    except ImportError:
        return None

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp_path))
        audio = _load_audio(tmp_path)
        return _window(audio) if audio is not None else None
    except Exception:
        return None
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


async def _generate_tts_negatives(out: Path, count: int, start_index: int) -> int:
    train_dir = out / "train" / "negative"
    heldout_dir = out / "heldout" / "negative"
    written = 0
    for i in range(count):
        phrase = random.choice(NEGATIVE_PHRASES)
        voice = random.choice(TTS_VOICES)
        rate = random.choice(["-10%", "-5%", "+0%", "+5%", "+10%"])
        audio = await _edge_tts_clip(phrase, voice, rate)
        if audio is None:
            continue
        if random.random() < 0.7:
            audio = audio + (np.random.randn(WINDOW) * random.uniform(0.002, 0.015)).astype(np.float32)
        target = heldout_dir if i % 5 == 0 else train_dir
        _write(target / f"neg_tts_{start_index + written:05d}.wav", audio)
        written += 1
    return written


def _count_wavs(path: Path) -> int:
    return len(list(path.glob("*.wav")))


async def build(
    out: Path,
    negatives: int,
    tts_negatives: int,
    heldout_ratio: float,
    seed: int,
    min_positive_rms: float,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    _reset_dir(out / "train" / "positive")
    _reset_dir(out / "train" / "negative")
    _reset_dir(out / "heldout" / "positive")
    _reset_dir(out / "heldout" / "negative")

    manifest = _copy_positive_splits(out, heldout_ratio, min_positive_rms)
    non_tts_written = _generate_non_tts_negatives(out, negatives)
    tts_written = await _generate_tts_negatives(out, tts_negatives, non_tts_written)

    manifest.update(
        {
            "format": "leha-wake-train-heldout-v1",
            "sample_rate": RATE,
            "window_seconds": 1.0,
            "negative_non_tts_generated": non_tts_written,
            "negative_tts_generated": tts_written,
            "negative_train": _count_wavs(out / "train" / "negative"),
            "negative_heldout": _count_wavs(out / "heldout" / "negative"),
            "seed": seed,
        }
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Leha wake training and held-out data")
    parser.add_argument("--out", default=str(ROOT / "processed" / "leha_wake_dataset"))
    parser.add_argument("--negatives", type=int, default=500)
    parser.add_argument("--tts-negatives", type=int, default=100)
    parser.add_argument("--heldout-ratio", type=float, default=0.25)
    parser.add_argument("--min-positive-rms", type=float, default=0.005)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    manifest = asyncio.run(
        build(
            Path(args.out),
            args.negatives,
            args.tts_negatives,
            args.heldout_ratio,
            args.seed,
            args.min_positive_rms,
        )
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
