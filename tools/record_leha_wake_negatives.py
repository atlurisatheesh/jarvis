"""Record private non-wake audio for evaluating the Leha wake detector.

The recording never leaves this laptop. Do not say "Leha" while recording.
Include normal conversation, TV/music at realistic volume, and room noise.
"""
from __future__ import annotations

import argparse
import sys
import wave
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
DEFAULT_MIN_RMS = 0.001
DEFAULT_MIN_PEAK = 0.005


def _write(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype(np.int16).tobytes())


def _quality(samples: np.ndarray) -> tuple[float, float]:
    scaled = samples.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(scaled ** 2))) if len(scaled) else 0.0
    peak = float(np.max(np.abs(scaled))) if len(scaled) else 0.0
    return rms, peak


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60, help="number of clips to record")
    parser.add_argument("--seconds", type=float, default=2.0, help="seconds per clip")
    parser.add_argument("--output", default="jarvis_ai/voices/wake_negative")
    parser.add_argument("--min-rms", type=float, default=DEFAULT_MIN_RMS)
    parser.add_argument("--min-peak", type=float, default=DEFAULT_MIN_PEAK)
    args = parser.parse_args()
    if args.count < 1 or args.seconds <= 0:
        raise SystemExit("--count and --seconds must be positive")

    device = resolve_device(config.MIC_DEVICE)
    native = next((rate for rate in _capture_rates(device) if _supports(device, rate)), None)
    if native is None:
        raise SystemExit(f"Could not open microphone {device!r}")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    frames = int(native * args.seconds)
    print(f"Recording {args.count} negative clips at {native} Hz into {output}.")
    print("Do not say Leha. Capture everyday speech, TV/music, and room noise.")
    input("Press Enter to begin. ")
    saved = 0
    attempts = 0
    max_attempts = args.count * 4
    while saved < args.count and attempts < max_attempts:
        attempts += 1
        clip = sd.rec(frames, samplerate=native, channels=1, dtype="int16", device=device)
        sd.wait()
        clip = clip.reshape(-1).astype(np.float32)
        if native != RATE:
            divisor = np.gcd(native, RATE)
            clip = resample_poly(clip, RATE // divisor, native // divisor)
        clip = np.clip(clip, -32768, 32767)
        rms, peak = _quality(clip)
        if rms < args.min_rms or peak < args.min_peak:
            print(f"Rejected quiet negative (RMS {rms:.4f}, peak {peak:.4f})", flush=True)
            continue
        path = output / f"negative_{saved + 1:03d}.wav"
        _write(path, clip)
        saved += 1
        print(f"Saved {path.name} (RMS {rms:.4f}, peak {peak:.4f})", flush=True)
    if saved < args.count:
        raise SystemExit(f"Only saved {saved}/{args.count} valid clips after {attempts} attempts.")


def _supports(device, rate: int) -> bool:
    try:
        sd.check_input_settings(device=device, samplerate=rate, channels=1, dtype="int16")
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
