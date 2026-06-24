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


def _write(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype(np.int16).tobytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60, help="number of clips to record")
    parser.add_argument("--seconds", type=float, default=2.0, help="seconds per clip")
    parser.add_argument("--output", default="jarvis_ai/voices/wake_negative")
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
    for index in range(args.count):
        clip = sd.rec(frames, samplerate=native, channels=1, dtype="int16", device=device)
        sd.wait()
        clip = clip.reshape(-1).astype(np.float32)
        if native != RATE:
            divisor = np.gcd(native, RATE)
            clip = resample_poly(clip, RATE // divisor, native // divisor)
        path = output / f"negative_{index + 1:03d}.wav"
        _write(path, np.clip(clip, -32768, 32767))
        print(f"Saved {path.name}", flush=True)


def _supports(device, rate: int) -> bool:
    try:
        sd.check_input_settings(device=device, samplerate=rate, channels=1, dtype="int16")
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
