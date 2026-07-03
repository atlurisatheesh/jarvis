"""Guided Leha wake-word data collection and evaluation.

This tool automates the safe parts of improving the local wake model:

- records owner wake clips with quality checks
- generates strong non-wake negatives locally
- audits the recorded positives
- builds a train/held-out dataset
- optionally trains and evaluates a candidate model

It deliberately does not enable the model. The runtime approval gate still
requires the eval report to pass before Leha can use a custom ONNX wake model.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis_ai import config
from jarvis_ai.audio import _capture_rates, resolve_device

RATE = 16_000
MIN_RMS = 0.005
MIN_PEAK = 0.03

POSITIVE_PROMPTS = [
    ("normal", "Leha"),
    ("normal", "Hey Leha"),
    ("normal", "Leha listen"),
    ("soft", "Leha"),
    ("fast", "Leha"),
    ("far", "Leha"),
    ("tired", "Leha"),
]

NEGATIVE_PHRASES = [
    "Leela", "Layla", "Lena", "later", "layer", "leader", "lila",
    "hello", "hey there", "open YouTube", "close YouTube", "play music",
    "what time is it", "open file explorer", "where am I", "thank you",
    "hey Siri", "Alexa", "hey Google", "Jarvis", "computer",
]


def _write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(np.clip(samples, -32768, 32767).astype(np.int16).tobytes())


def _quality(samples: np.ndarray) -> tuple[float, float]:
    scaled = samples.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(scaled * scaled))) if len(scaled) else 0.0
    peak = float(np.max(np.abs(scaled))) if len(scaled) else 0.0
    return rms, peak


def _native_rate(device) -> int:
    for candidate in _capture_rates(device):
        try:
            sd.check_input_settings(device=device, samplerate=candidate, channels=1, dtype="int16")
            return candidate
        except Exception:
            continue
    raise RuntimeError(f"Could not open microphone {device!r} at a supported rate.")


def _record_clip(device, native: int, seconds: float) -> np.ndarray:
    frames = int(native * seconds)
    audio = sd.rec(frames, samplerate=native, channels=1, dtype="int16", device=device)
    sd.wait()
    clip = audio.reshape(-1).astype(np.float32)
    if native != RATE:
        divisor = math.gcd(native, RATE)
        clip = resample_poly(clip, RATE // divisor, native // divisor)
    return np.clip(clip, -32768, 32767).astype(np.int16)


def _beep() -> None:
    try:
        import winsound
        winsound.Beep(880, 160)
    except Exception:
        print("\a", end="", flush=True)


def collect_positive(count: int, seconds: float, out_dir: Path) -> dict:
    device = resolve_device(config.MIC_DEVICE)
    native = _native_rate(device)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[positive] microphone={device!r} native_rate={native}Hz")
    print("[positive] You only need to say the prompt after each beep.")
    print("[positive] Vary distance/tone when the style says soft, fast, far, or tired.")
    time.sleep(2)

    saved = 0
    attempts = 0
    rejected = []
    while saved < count and attempts < count * 4:
        attempts += 1
        style, phrase = POSITIVE_PROMPTS[saved % len(POSITIVE_PROMPTS)]
        print(f"[{saved + 1:03d}/{count:03d}] style={style} say: {phrase!r}")
        for n in (3, 2, 1):
            print(n, flush=True)
            time.sleep(0.45)
        _beep()
        clip = _record_clip(device, native, seconds)
        rms, peak = _quality(clip)
        if rms < MIN_RMS or peak < MIN_PEAK:
            rejected.append({"attempt": attempts, "rms": rms, "peak": peak, "style": style})
            print(f"  rejected quiet clip rms={rms:.4f} peak={peak:.4f}; move closer or speak clearer")
            time.sleep(0.8)
            continue
        path = out_dir / f"leha_{saved + 1:03d}.wav"
        _write_wav(path, clip)
        saved += 1
        print(f"  saved {path.name} rms={rms:.4f} peak={peak:.4f}")
        time.sleep(0.8)

    report = {
        "requested": count,
        "saved": saved,
        "attempts": attempts,
        "rejected": rejected,
        "output": str(out_dir),
    }
    (out_dir / "collection_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if saved < count:
        raise SystemExit(f"Only saved {saved}/{count} valid clips. Re-run from a quieter/closer position.")
    return report


async def _edge_tts_clip(text: str, voice: str, rate_str: str) -> np.ndarray | None:
    try:
        import edge_tts
        import soundfile as sf
        import tempfile
    except ImportError:
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        await edge_tts.Communicate(text, voice, rate=rate_str).save(str(tmp_path))
        data, sr = sf.read(str(tmp_path), dtype="float32")
        if data.ndim > 1:
            data = data[:, 0]
        if sr != RATE:
            divisor = math.gcd(sr, RATE)
            data = resample_poly(data, RATE // divisor, sr // divisor).astype(np.float32)
        if len(data) < RATE:
            padded = np.zeros(RATE, dtype=np.float32)
            offset = (RATE - len(data)) // 2
            padded[offset:offset + len(data)] = data
            data = padded
        else:
            start = max(0, (len(data) - RATE) // 2)
            data = data[start:start + RATE]
        return np.clip(data * 32767, -32768, 32767).astype(np.int16)
    except Exception:
        return None
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


async def generate_negatives(count: int, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    voices = [
        "en-IN-NeerjaNeural", "en-IN-PrabhatNeural",
        "en-US-AriaNeural", "en-US-GuyNeural", "en-GB-LibbyNeural",
    ]
    saved = 0
    failures = 0
    random.seed(42)

    while saved < count:
        if saved % 4 == 0:
            # White/pink-ish room noise and silence teach the model not to wake
            # on non-speech speaker/mic texture.
            gain = random.uniform(0.002, 0.07)
            clip = (np.random.randn(RATE).astype(np.float32) * gain * 32767).astype(np.int16)
        else:
            phrase = random.choice(NEGATIVE_PHRASES)
            voice = random.choice(voices)
            rate_str = random.choice(["-10%", "-5%", "+0%", "+5%", "+10%"])
            clip = await _edge_tts_clip(phrase, voice, rate_str)
            if clip is None:
                failures += 1
                continue
            if random.random() < 0.7:
                noise = np.random.randn(len(clip)).astype(np.float32) * random.uniform(80, 600)
                clip = np.clip(clip.astype(np.float32) + noise, -32768, 32767).astype(np.int16)
        saved += 1
        _write_wav(out_dir / f"negative_{saved:04d}.wav", clip)

    report = {"requested": count, "saved": saved, "failures": failures, "output": str(out_dir)}
    (out_dir / "generation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _run(cmd: list[str]) -> int:
    print("[run]", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def audit_and_build(positive_dir: Path, negative_dir: Path, dataset_dir: Path) -> None:
    audit_report = ROOT / "processed" / "guided_wake_positive_audit.json"
    code = _run([
        sys.executable, "tools/audit_leha_wake_dataset.py",
        str(positive_dir),
        "--report", str(audit_report),
    ])
    if code != 0:
        raise SystemExit(code)

    # Reuse the existing builder's standard positive dirs by copying the new
    # collection into a dedicated source directory it already scans.
    target = ROOT / "jarvis_ai" / "voices" / "wake_leha_guided"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(positive_dir, target)

    # Keep generated negatives available to training tools and future audits.
    guided_neg = ROOT / "processed" / "guided_wake_negatives"
    if guided_neg.exists():
        shutil.rmtree(guided_neg)
    shutil.copytree(negative_dir, guided_neg)

    # Build the repo's standard train/held-out dataset. It adds additional
    # synthetic and local negatives, which is helpful for robustness.
    code = _run([
        sys.executable, "tools/build_leha_wake_dataset.py",
        "--out", str(dataset_dir),
        "--negatives", "500",
        "--tts-negatives", "200",
        "--min-positive-rms", str(MIN_RMS),
    ])
    if code != 0:
        raise SystemExit(code)

    # Add this guided run's generated distractors/noise into the same dataset.
    # Use a held-out split so evaluation still sees examples not mixed only into
    # training. These are all non-wake clips, so they improve false-wake safety.
    added_train = 0
    added_heldout = 0
    train_neg = dataset_dir / "train" / "negative"
    heldout_neg = dataset_dir / "heldout" / "negative"
    for idx, src in enumerate(sorted(negative_dir.glob("*.wav"))):
        target_dir = heldout_neg if idx % 5 == 0 else train_neg
        prefix = "guided_heldout" if idx % 5 == 0 else "guided_train"
        shutil.copy2(src, target_dir / f"{prefix}_{idx:04d}.wav")
        if idx % 5 == 0:
            added_heldout += 1
        else:
            added_train += 1

    manifest_path = dataset_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    manifest["guided_negative_train_added"] = added_train
    manifest["guided_negative_heldout_added"] = added_heldout
    manifest["negative_train"] = len(list(train_neg.glob("*.wav")))
    manifest["negative_heldout"] = len(list(heldout_neg.glob("*.wav")))
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def maybe_train(dataset_dir: Path, epochs: int) -> None:
    output = ROOT / "processed" / "leha_wake_model_guided.onnx"
    code = _run([
        sys.executable, "tools/train_and_evaluate_leha_wake.py",
        "--skip-generate",
        "--data", str(dataset_dir),
        "--output", str(output),
        "--epochs", str(epochs),
    ])
    if code != 0:
        print("[train] Candidate did not pass. Keeping production wake model disabled.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Guided safe Leha wake improvement")
    parser.add_argument("--positives", type=int, default=120)
    parser.add_argument("--negatives", type=int, default=400)
    parser.add_argument("--seconds", type=float, default=1.8)
    parser.add_argument("--train", action="store_true", help="train/evaluate after collecting data")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--skip-positive", action="store_true", help="only generate negatives/build from existing positives")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    positive_dir = ROOT / "jarvis_ai" / "voices" / f"wake_leha_guided_{stamp}"
    negative_dir = ROOT / "processed" / f"wake_negative_guided_{stamp}"
    dataset_dir = ROOT / "processed" / f"leha_wake_dataset_guided_{stamp}"

    summary = {"started": stamp}
    if not args.skip_positive:
        summary["positive"] = collect_positive(args.positives, args.seconds, positive_dir)
    else:
        positive_dir = ROOT / "jarvis_ai" / "voices" / "wake_leha_guided"
        summary["positive"] = {"skipped": True, "using": str(positive_dir)}

    summary["negative"] = asyncio.run(generate_negatives(args.negatives, negative_dir))
    audit_and_build(positive_dir, negative_dir, dataset_dir)
    summary["dataset"] = str(dataset_dir)

    if args.train:
        maybe_train(dataset_dir, args.epochs)
        summary["trained"] = True
    else:
        summary["trained"] = False

    report = ROOT / "processed" / f"guided_wake_improvement_{stamp}.json"
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[done] report: {report}")
    print("[done] Production wake model was NOT enabled. Enable only after approved eval.")


if __name__ == "__main__":
    main()
